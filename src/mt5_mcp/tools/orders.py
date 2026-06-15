"""Order tools: get_orders (read), place_order, modify_order, cancel_order (mutating)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    epoch_to_utc, order_request_to_mt5_dict, order_result_from_mt5_response,
    order_from_raw,
)
from mt5_mcp.errors import MT5Error, invalid_request_error
from mt5_mcp.policy.consent import new_request_id
from mt5_mcp.policy.preflight import PreflightInputs
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    ApprovalPreview, ErrorDetail, Order, OrderRequest, Quote,
)


def _to_decimal(value: str, *, field: str) -> Decimal:
    """Parse a Decimal-shaped tool argument, surfacing parse failures as
    INVALID_REQUEST instead of an envelope-swallowed INTERNAL_ERROR.

    Callers handle None/falsy themselves so optional vs required semantics
    stay at the call site.
    """
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MT5Error(invalid_request_error(
            field=field, value=value, reason=f"not a valid decimal ({exc})",
        )) from exc


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    @error_envelope
    def get_orders(symbol: str | None = None) -> list[Order]:
        """Pending orders, optionally filtered to a single symbol."""
        ctx = get_context()
        if symbol:
            raws = ctx.client.call(lambda m: m.orders_get(symbol=symbol))
        else:
            raws = ctx.client.call(lambda m: m.orders_get())
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [order_from_raw(r, broker_offset_minutes=offset) for r in raws]

    @mcp.tool()
    @error_envelope
    def place_order(
        symbol: str,
        side: str,
        type: str,
        volume: str,
        price: str | None = None,
        stop_limit_price: str | None = None,
        sl: str | None = None,
        tp: str | None = None,
        deviation: int = 10,
        comment: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Place a market or pending order. Optional SL / TP / deviation.

        When `policy.auto_approve_notional` is set > 0, orders whose notional is
        at or above it return an ApprovalPreview; retry with
        approval_confirmed=true and the same request fields to proceed. At the
        default of 0 the gate is off and orders auto-execute. Pass
        `idempotency_key` (UUIDv4 recommended) to dedupe retries within
        `idempotency.ttl_seconds`.
        """
        ctx = get_context()
        req = OrderRequest(
            symbol=symbol, side=side, type=type,
            volume=_to_decimal(volume, field="volume"),
            price=_to_decimal(price, field="price") if price else None,
            stop_limit_price=_to_decimal(stop_limit_price, field="stop_limit_price") if stop_limit_price else None,
            sl=_to_decimal(sl, field="sl") if sl else None,
            tp=_to_decimal(tp, field="tp") if tp else None,
            deviation=deviation, comment=comment,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        # Adapter prep - raises MT5Error caught by error_envelope.
        info = ctx.symbols.get(symbol)
        ctx.symbols.validate_volume(symbol, req.volume)
        if req.price is not None:
            req = req.model_copy(update={
                "price": ctx.symbols.quantise_price(symbol, req.price)
            })
        filling = ctx.symbols.pick_filling_mode(symbol, order_type=req.type)

        # Resolve a reference price for notional + fill-price.
        if req.price is not None:
            ref_price = req.price
            tick = None
        else:
            tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
            if tick is None:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=f"No tick data for {symbol}; market may be closed.",
                    retryable=True, requires_human=False,
                    details={"symbol": symbol},
                ))
            ref_price = Decimal(str(tick.ask if req.side == "buy" else tick.bid))

        notional = req.volume * ref_price

        cfg = ctx.config
        # Opt-in consent gate. The default auto_approve_notional=0 disables it
        # (full-open: orders auto-execute). Set it > 0 to require approval on
        # orders whose notional is at or above the threshold; orders below it
        # still auto-approve.
        requires_approval = (
            cfg.policy.auto_approve_notional > 0
            and notional >= cfg.policy.auto_approve_notional
        )

        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        # Resolve a live tick for the approval preview the human will see. Market
        # orders already hold `tick` (and fail above if it's missing); priced /
        # pending orders start with tick=None, so fetch one here. If quotes are
        # out we can't render a preview - refuse gracefully instead of letting
        # build_preview dereference a None tick (turning it into INTERNAL_ERROR).
        preview_tick = tick
        if requires_approval and preview_tick is None:
            preview_tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
            if preview_tick is None:
                raise MT5Error(ErrorDetail(
                    code="SYMBOL_NOT_ENABLED",
                    message=(f"No tick data for {symbol}; cannot present approval "
                             f"preview for this order. Retry when quotes resume."),
                    retryable=True, requires_human=False,
                    details={"symbol": symbol},
                ))

        def build_preview() -> ApprovalPreview:
            t = preview_tick
            return ApprovalPreview(
                request_id=new_request_id(),
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"{req.side.upper()} {req.volume} {symbol} @ {req.type} "
                         f"(~{notional} {currency})"),
                action="place_order", symbol=symbol,
                notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(t.bid)), ask=Decimal(str(t.ask)),
                    time=epoch_to_utc(t.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        preflight = PreflightInputs(notional=notional)
        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))

        with ctx.policy.guard(
            "place_order", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=ref_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5_dict = order_request_to_mt5_dict(
                req, symbol_info=info, filling_mode=filling,
                price=ref_price, mt5=ctx.client.mt5,
            )
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="place_order", symbol=symbol,
                request_volume=req.volume,
                mt5_module=ctx.client.mt5,
            )

    @mcp.tool()
    @error_envelope
    def modify_order(
        ticket: int,
        sl: str | None = None,
        tp: str | None = None,
        price: str | None = None,
        expiration: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Modify SL/TP on a position or price/expiration on a pending order.

        When the consent gate is armed (`policy.auto_approve_notional` > 0),
        widening or removing an existing SL/TP requires approval; tightening
        always auto-approves. At the default of 0 the gate is off and every
        modify auto-executes.
        """
        from datetime import datetime as _dt
        from mt5_mcp.types import ModifyOrderRequest
        from mt5_mcp.errors import invalid_ticket_error

        ctx = get_context()
        req = ModifyOrderRequest(
            ticket=ticket,
            sl=_to_decimal(sl, field="sl") if sl is not None else None,
            tp=_to_decimal(tp, field="tp") if tp is not None else None,
            price=_to_decimal(price, field="price") if price is not None else None,
            expiration=_dt.fromisoformat(expiration.replace("Z", "+00:00"))
                       if expiration else None,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        # Look up the position first; fall back to pending order.
        positions = ctx.client.call(lambda m: m.positions_get(ticket=ticket))
        orders = ctx.client.call(lambda m: m.orders_get(ticket=ticket))
        is_position = bool(positions)
        is_order = bool(orders) and not is_position
        if not is_position and not is_order:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="order"))

        target = positions[0] if is_position else orders[0]
        symbol = target.symbol
        info = ctx.symbols.get(symbol)

        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is not None:
            current_price = Decimal(str(tick.bid))
        else:
            # Quote outage: fall back to the target's last-known broker price so
            # widening detection and notional aren't computed against zero.
            fallback = getattr(target, "price_current", None) or getattr(target, "price_open", 0)
            current_price = Decimal(str(fallback or 0))

        # Gate logic: only when widening / removing SL or TP on a position.
        old_sl = Decimal(str(getattr(target, "sl", 0) or 0))
        old_tp = Decimal(str(getattr(target, "tp", 0) or 0))

        def _is_widening(old: Decimal, new: Decimal | None) -> bool:
            if new is None:
                return False
            if old != 0 and new == 0:
                return True  # removal
            if old == 0:
                return False  # adding when none was set is tightening
            return abs(current_price - new) > abs(current_price - old)

        widening = (
            (req.sl is not None and _is_widening(old_sl, req.sl))
            or (req.tp is not None and _is_widening(old_tp, req.tp))
        )
        cfg = ctx.config
        # Opt-in consent gate (master switch = auto_approve_notional > 0). With
        # the gate off (default 0, full-open) a widening/removing SL-TP change
        # auto-approves; set auto_approve_notional > 0 to require approval for it.
        requires_approval = (
            cfg.policy.auto_approve_notional > 0 and is_position and widening
        )
        # A widening change that needs approval requires a fresh quote for the
        # preview the human sees; refuse gracefully if quotes are out rather than
        # dereferencing a None tick in build_preview (mirrors close_position).
        if requires_approval and tick is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_ENABLED",
                message=(f"No tick data for {symbol}; cannot present approval "
                         f"preview for the SL/TP change. Retry when quotes resume."),
                retryable=True, requires_human=False,
                details={"symbol": symbol},
            ))

        volume = Decimal(str(getattr(target, "volume", getattr(target, "volume_current", 0))))
        notional = volume * current_price
        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            return ApprovalPreview(
                request_id=new_request_id(),
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"MODIFY ticket {ticket} {symbol} "
                         f"SL={req.sl} TP={req.tp} (~{notional} {currency})"),
                action="modify_order", symbol=symbol, notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)),
                    time=epoch_to_utc(tick.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))
        preflight = PreflightInputs(notional=notional)

        with ctx.policy.guard(
            "modify_order", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=current_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            if is_position:
                mt5_dict = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": symbol,
                    "position": int(ticket),
                    "sl": float(req.sl) if req.sl is not None else float(old_sl),
                    "tp": float(req.tp) if req.tp is not None else float(old_tp),
                }
            else:
                mt5_dict = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": int(ticket),
                    "price": float(req.price) if req.price is not None else float(target.price_open),
                    "sl": float(req.sl) if req.sl is not None else 0.0,
                    "tp": float(req.tp) if req.tp is not None else 0.0,
                }
                if req.expiration is not None:
                    # Specific expiry timestamp (mt5lib expects Unix seconds + ORDER_TIME_SPECIFIED).
                    mt5_dict["type_time"] = getattr(mt5, "ORDER_TIME_SPECIFIED", 2)
                    mt5_dict["type_expiration"] = int(req.expiration.timestamp())
                else:
                    mt5_dict["type_time"] = getattr(mt5, "ORDER_TIME_GTC", 0)
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="modify_order", symbol=symbol,
                request_volume=volume,
                mt5_module=ctx.client.mt5,
            )

    @mcp.tool()
    @error_envelope
    def cancel_order(
        ticket: int,
        idempotency_key: str | None = None,
    ) -> dict:
        """Cancel a pending order by ticket. No consent gate (reduces exposure)."""
        from mt5_mcp.types import CancelOrderRequest
        from mt5_mcp.errors import invalid_ticket_error

        ctx = get_context()
        req = CancelOrderRequest(ticket=ticket, idempotency_key=idempotency_key)
        orders = ctx.client.call(lambda m: m.orders_get(ticket=ticket))
        if not orders:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="order"))
        target = orders[0]
        symbol = target.symbol

        with ctx.policy.guard(
            "cancel_order", req,
            requires_approval=False,
            preflight_inputs=None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            mt5_dict = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(ticket),
            }
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="cancel_order", symbol=symbol,
                request_volume=Decimal(str(getattr(target, "volume_current", 0))),
                mt5_module=ctx.client.mt5,
            )
