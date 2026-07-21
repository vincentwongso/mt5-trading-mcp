"""Optional viewport levers for get_chart_screenshot.

Parallels ``annotations.py``: ``validate_viewport`` runs outside
``error_envelope`` and returns a typed ``Viewport``; ``serialize_viewport``
renders the wire fields. ``scale`` and ``bars`` both resolve to MT5's single
discrete ``CHART_SCALE`` knob, so they are mutually exclusive. ``end_time`` is
converted UTC -> broker time in ``serialize_viewport`` using the same
``utc_to_broker_epoch`` path annotations use, so scroll and annotations never
disagree about what a timestamp means.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail

_SCALE_MIN = 0
_SCALE_MAX = 5


@dataclass(frozen=True)
class Viewport:
    scale: int | None = None
    bars: int | None = None
    end_time: datetime | None = None
    price_min: float | None = None
    price_max: float | None = None

    def is_empty(self) -> bool:
        return (
            self.scale is None
            and self.bars is None
            and self.end_time is None
            and self.price_min is None
            and self.price_max is None
        )


EMPTY_VIEWPORT = Viewport()


def _invalid(message: str, **details: object) -> MT5Error:
    return MT5Error(ErrorDetail(
        code="INVALID_VIEWPORT",
        message=message,
        retryable=False,
        requires_human=False,
        details=details or None,
    ))


def _parse_end_time(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MT5Error(ErrorDetail(
            code="INVALID_TIMESTAMP",
            message=(
                f"end_time '{raw}' is not a valid ISO-8601 UTC timestamp "
                "(e.g. '2026-07-19T12:30:00Z')."
            ),
            retryable=False,
            requires_human=False,
            details={"end_time": raw},
        )) from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_viewport(
    *,
    scale: int | None,
    bars: int | None,
    end_time: str | None,
    price_min: float | None,
    price_max: float | None,
) -> Viewport:
    """Validate the optional framing levers into a Viewport, or raise.

    scale/bars are mutually exclusive; scale is 0-5; bars is positive; the
    price band is both-or-neither with max > min; end_time is ISO-8601 UTC.
    """
    if scale is not None and bars is not None:
        raise _invalid(
            "scale and bars both set: they control the same CHART_SCALE knob. "
            "Pass one or the other.",
            scale=scale, bars=bars,
        )
    if scale is not None and not (_SCALE_MIN <= scale <= _SCALE_MAX):
        raise _invalid(
            f"scale must be between {_SCALE_MIN} and {_SCALE_MAX}, got {scale}.",
            scale=scale,
        )
    if bars is not None and bars < 1:
        raise _invalid(f"bars must be a positive integer, got {bars}.", bars=bars)
    if (price_min is None) != (price_max is None):
        raise _invalid(
            "price_min and price_max must be set together to fix the price band.",
            price_min=price_min, price_max=price_max,
        )
    if price_min is not None and price_max is not None and price_max <= price_min:
        raise _invalid(
            f"price_max ({price_max}) must be greater than price_min ({price_min}).",
            price_min=price_min, price_max=price_max,
        )

    parsed_end = _parse_end_time(end_time) if end_time is not None else None
    return Viewport(
        scale=scale,
        bars=bars,
        end_time=parsed_end,
        price_min=price_min,
        price_max=price_max,
    )
