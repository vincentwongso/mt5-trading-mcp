"""Position tools: get_positions (read), close_position (mutating)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from mt5_mcp.adapter.conversions import (
    epoch_to_utc, order_result_from_mt5_response, position_from_raw,
)
from mt5_mcp.errors import MT5Error, invalid_ticket_error
from mt5_mcp.policy.consent import new_request_id
from mt5_mcp.policy.preflight import PreflightInputs
from mt5_mcp.server import get_context
from mt5_mcp.tools._common import error_envelope
from mt5_mcp.types import (
    ApprovalPreview, ClosePositionRequest, ErrorDetail, Position, Quote,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    @error_envelope
    def get_positions(symbol: str | None = None) -> list[Position]:
        """Open positions, optionally filtered to a single symbol."""
        ctx = get_context()
        if symbol:
            raws = ctx.client.call(lambda m: m.positions_get(symbol=symbol))
        else:
            raws = ctx.client.call(lambda m: m.positions_get())
        if raws is None:
            return []
        offset = ctx.client.broker_offset_minutes
        return [position_from_raw(r, broker_offset_minutes=offset) for r in raws]

    @mcp.tool()
    @error_envelope
    def close_position(
        ticket: int,
        volume: str | None = None,
        idempotency_key: str | None = None,
        approval_confirmed: bool = False,
        approval_request_id: str | None = None,
    ) -> dict:
        """Close an open position in full or part by ticket."""
        ctx = get_context()
        req = ClosePositionRequest(
            ticket=ticket,
            volume=Decimal(volume) if volume else None,
            idempotency_key=idempotency_key,
            approval_confirmed=approval_confirmed,
            approval_request_id=approval_request_id,
        )

        positions = ctx.client.call(lambda m: m.positions_get(ticket=ticket))
        if not positions:
            raise MT5Error(invalid_ticket_error(ticket=ticket, kind="position"))
        pos = positions[0]
        symbol = pos.symbol
        info = ctx.symbols.get(symbol)
        close_volume = req.volume or Decimal(str(pos.volume))

        tick = ctx.client.call(lambda m: m.symbol_info_tick(symbol))
        if tick is None:
            raise MT5Error(ErrorDetail(
                code="SYMBOL_NOT_ENABLED",
                message=f"No tick data for {symbol}; market may be closed.",
                retryable=True, requires_human=False,
                details={"symbol": symbol},
            ))
        is_buy_position = pos.type == ctx.client.mt5.POSITION_TYPE_BUY
        close_price = Decimal(str(tick.bid if is_buy_position else tick.ask))
        notional = close_volume * close_price
        # Estimated realised P&L on close (negative when realising a loss).
        sign = Decimal("1") if is_buy_position else Decimal("-1")
        realised = (close_price - Decimal(str(pos.price_open))) * close_volume * sign

        cfg = ctx.config
        requires_approval = (
            cfg.policy.auto_approve_notional > 0
            and notional >= cfg.policy.auto_approve_notional
        )
        account = ctx.client.call(lambda m: m.account_info())
        leverage = Decimal(str(account.leverage)) if account else Decimal("1")
        currency = account.currency if account else "USD"

        def build_preview() -> ApprovalPreview:
            return ApprovalPreview(
                request_id=new_request_id(),
                expires_at=datetime.now(timezone.utc)
                          + timedelta(seconds=cfg.policy.approval_ttl_seconds),
                summary=(f"CLOSE {close_volume} {symbol} @ ~{close_price} "
                         f"(~{notional} {currency})"),
                action="close_position", symbol=symbol, notional=notional,
                estimated_margin=notional / leverage,
                reference_quote=Quote(
                    symbol=symbol,
                    bid=Decimal(str(tick.bid)), ask=Decimal(str(tick.ask)),
                    time=epoch_to_utc(tick.time, ctx.client.broker_offset_minutes),
                ),
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
            )

        preflight = PreflightInputs(
            notional=notional,
            estimated_realised_loss_on_close=realised,
        )
        symbol_point = Decimal(str(getattr(info, "point", 0.00001)))

        with ctx.policy.guard(
            "close_position", req,
            requires_approval=requires_approval,
            preview_factory=build_preview if requires_approval else None,
            preflight_inputs=preflight,
            current_price=close_price if approval_confirmed else None,
            symbol_point=symbol_point if approval_confirmed else None,
        ) as g:
            if g.short_circuit is not None:
                return g.short_circuit
            mt5 = ctx.client.mt5
            mt5_dict = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(close_volume),
                "type": mt5.ORDER_TYPE_SELL if is_buy_position else mt5.ORDER_TYPE_BUY,
                "position": int(ticket),
                "price": float(close_price),
                "deviation": 10,
                "type_filling": ctx.symbols.pick_filling_mode(symbol, order_type="market"),
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 1),
                "magic": 0,
            }
            g.execute(lambda: ctx.client.call(lambda m: m.order_send(mt5_dict)))
            return g.finalize(
                order_result_from_mt5_response,
                request_echo=req.model_dump(mode="json", exclude={"idempotency_key"}),
                action="close_position", symbol=symbol,
                request_volume=close_volume,
            )
