"""Chart annotation schema for `get_chart_screenshot`.

Annotations are drawn by the AgentScreenshot EA on the throwaway chart it
opens per request, so `ChartClose` discards them and nothing can leak onto a
chart the user has open. This module owns the public schema, the role palette
and serialization to the bridge wire format; it deliberately imports nothing
from the MT5 adapter so it stays trivially unit testable.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from mt5_mcp.errors import MT5Error
from mt5_mcp.types import ErrorDetail

MAX_ANNOTATIONS = 16
MAX_TEXT_LEN = 128

Role = Literal["resistance", "support", "note", "neutral"]
ColorName = Literal["red", "lime", "yellow", "gray", "white", "aqua", "orange", "magenta"]
Corner = Literal["top_left", "top_right", "bottom_left", "bottom_right"]

# MQL5 `color` is a BGR integer, not RGB. red = RGB(255,0,0) = BGR 0x0000FF.
COLOR_BGR: dict[str, int] = {
    "red": 0x0000FF,
    "lime": 0x00FF00,
    "yellow": 0x00FFFF,
    "gray": 0x808080,
    "white": 0xFFFFFF,
    "aqua": 0xFFFF00,
    "orange": 0x00A5FF,
    "magenta": 0xFF00FF,
}

# role -> (default color name, MQL5 ENUM_LINE_STYLE: STYLE_SOLID=0, STYLE_DASH=2)
ROLE_PALETTE: dict[str, tuple[str, int]] = {
    "resistance": ("red", 0),
    "support": ("lime", 0),
    "note": ("yellow", 0),
    "neutral": ("gray", 2),
}

# MQL5 ENUM_BASE_CORNER ordering is not clockwise; map explicitly.
CORNER_ID: dict[str, int] = {
    "top_left": 0,      # CORNER_LEFT_UPPER
    "bottom_left": 1,   # CORNER_LEFT_LOWER
    "bottom_right": 2,  # CORNER_RIGHT_LOWER
    "top_right": 3,     # CORNER_RIGHT_UPPER
}


class _AnnotationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role = "note"
    color: ColorName | None = None

    @field_validator("text", check_fields=False)
    @classmethod
    def _check_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if any(ch in v for ch in ("|", "\r", "\n")):
            raise ValueError("must not contain '|', carriage return or line feed")
        if not 1 <= len(v) <= MAX_TEXT_LEN:
            raise ValueError(f"must be 1 to {MAX_TEXT_LEN} characters")
        return v

    @field_validator("price", "price1", "price2", check_fields=False)
    @classmethod
    def _check_price(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be a finite number")
        return v


class HLine(_AnnotationBase):
    """Horizontal price level spanning the full chart width."""
    type: Literal["hline"]
    price: Decimal
    text: str | None = None


class VLine(_AnnotationBase):
    """Vertical time marker spanning the full chart height."""
    type: Literal["vline"]
    time: datetime
    text: str | None = None


class ChartText(_AnnotationBase):
    """Free-placed text anchored to a (time, price) point on the chart."""
    type: Literal["text"]
    time: datetime
    price: Decimal
    text: str


class ScreenLabel(_AnnotationBase):
    """Text pinned to a chart corner, independent of the visible price range."""
    type: Literal["label"]
    corner: Corner = "top_left"
    text: str


class TrendLine(_AnnotationBase):
    """Diagonal line between two (time, price) points. Does not extend as a ray."""
    type: Literal["trendline"]
    time1: datetime
    price1: Decimal
    time2: datetime
    price2: Decimal
    text: str | None = None


Annotation = Annotated[
    Union[HLine, VLine, ChartText, ScreenLabel, TrendLine],
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[list[Annotation]] = TypeAdapter(list[Annotation])


def validate_annotations(raw: object) -> list[Annotation]:
    """Validate caller-supplied annotations into models, or raise INVALID_ANNOTATION.

    Rejects the whole call rather than dropping bad entries: a silently skipped
    annotation is invisible in a PNG, so the agent would go on to describe a
    level that was never drawn.
    """
    if raw is None:
        return []
    if isinstance(raw, list) and len(raw) > MAX_ANNOTATIONS:
        raise MT5Error(ErrorDetail(
            code="INVALID_ANNOTATION",
            message=(
                f"Too many annotations: {len(raw)}. "
                f"At most {MAX_ANNOTATIONS} are allowed per screenshot."
            ),
            retryable=False,
            requires_human=False,
            details={"count": len(raw), "max": MAX_ANNOTATIONS},
        ))
    try:
        return _ADAPTER.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        # loc looks like (2, 'hline', 'role'); index first, model tag second.
        loc = first.get("loc", ())
        index = loc[0] if loc and isinstance(loc[0], int) else None
        field = ".".join(str(p) for p in loc[1:]) or "annotation"
        where = f"annotations[{index}]" if index is not None else "annotations"
        raise MT5Error(ErrorDetail(
            code="INVALID_ANNOTATION",
            message=f"{where}: {field} {first.get('msg', 'is invalid')}",
            retryable=False,
            requires_human=False,
            details={"index": index, "field": field},
        )) from exc
