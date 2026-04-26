"""Order tools: get_orders (read), place_order (mutating).

Phase 2 adds modify_order / cancel_order in subsequent tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    epoch_to_utc, order_request_to_mt5_dict, order_result_from_mt5_response,
    order_from_raw,
)
from mt5_mcp.errors import MT5Error
from mt5_mcp.policy.consent import new_request_id
from mt5_mcp.policy.preflight import PreflightInputs
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    ApprovalPreview, ErrorDetail, Order, OrderRequest, Quote,
)


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

        Above `policy.auto_approve_notional`, returns an ApprovalPreview;
        retry with approval_confirmed=true and the same request fields to
        proceed. Pass `idempotency_key` (UUIDv4 recommended) to dedupe
        retries within `idempotency.ttl_seconds`.
        """
        ctx = get_context()
        req = OrderRequest(
            symbol=symbol, side=side, type=type, volume=Decimal(volume),
            price=Decimal(price) if price else None,
            stop_limit_price=Decimal(stop_limit_price) if stop_limit_price else None,
            sl=Decimal(sl) if sl else None,
            tp=Decimal(tp) if tp else None,
            deviation=deviation, comment=comment,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        # Adapter prep — raises MT5Error caught by error_envelope.
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
        requires_approval = (
            cfg.policy.auto_approve_notional > 0
            and notional >= cfg.policy.auto_approve_notional
        )

        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            t = tick or ctx.client.call(lambda m: m.symbol_info_tick(symbol))
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
            )
