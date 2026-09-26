"""Backend-neutral PDF coordinate and render-target helpers.

The native IR stores page bboxes in unrotated PDF point coordinates.  The
cropbox is the source viewport; rendering applies the page rotation clockwise
and produces a top-left, x-right/y-down pixel viewport.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from numbers import Real
from typing import Sequence


class CoordinateSpace(StrEnum):
    """Explicit units used by bbox values.

    The value range is deliberately *not* used to identify a coordinate
    space.  A pixel bbox can legitimately contain only 0 and 1, while a
    normalized bbox can contain the same numbers.
    """

    PDF_POINT = "pdf_point"
    PIXEL = "pixel"
    NORMALIZED = "normalized"
    NORMALIZED_1000 = "normalized_1000"


COORDINATE_CONTRACT_VERSION = "coordinate-contract.v2"
_EPSILON = 1e-9


def _space(value: CoordinateSpace | str) -> CoordinateSpace:
    try:
        return value if isinstance(value, CoordinateSpace) else CoordinateSpace(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported coordinate_space: {value!r}") from exc


def _finite_bbox(value: Sequence[float], name: str = "bbox") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{name} must contain four coordinates")
    if any(isinstance(v, bool) or not isinstance(v, Real) for v in value):
        raise ValueError(f"{name} must contain numeric coordinates")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def validate_bbox(value: Sequence[float], coordinate_space: CoordinateSpace | str,
                 *, bounds: Sequence[float] | None = None,
                 allow_zero_area: bool = False) -> list[float]:
    """Validate an explicit xyxy bbox without guessing its units."""
    space = _space(coordinate_space)
    box = _finite_bbox(value)
    x0, y0, x1, y1 = box
    limit = 1.0 if space is CoordinateSpace.NORMALIZED else 1000.0 if space is CoordinateSpace.NORMALIZED_1000 else None
    if limit is not None and (min(box) < -_EPSILON or max(box) > limit + _EPSILON):
        raise ValueError(f"{space.value} bbox is outside its declared range")
    if x1 < x0 or y1 < y0 or (not allow_zero_area and (x1 <= x0 or y1 <= y0)):
        raise ValueError("bbox must have positive width and height")
    if bounds is not None:
        bound = _finite_bbox(bounds, "bounds")
        if x0 < bound[0] - _EPSILON or y0 < bound[1] - _EPSILON or x1 > bound[2] + _EPSILON or y1 > bound[3] + _EPSILON:
            raise ValueError("bbox is outside the declared reference bounds")
    return box


def coordinate_bbox(value: Sequence[float], coordinate_space: CoordinateSpace | str,
                    **metadata: object) -> dict[str, object]:
    """Serialize a bbox with its units and contract version."""
    box = validate_bbox(value, coordinate_space)
    return {"coordinate_space": _space(coordinate_space).value,
            "coordinate_version": COORDINATE_CONTRACT_VERSION,
            "bbox": box, **metadata}


def pixel_to_normalized(bbox: Sequence[float], width: int | float, height: int | float) -> list[float]:
    if not math.isfinite(float(width)) or not math.isfinite(float(height)) or width <= 0 or height <= 0:
        raise ValueError("reference width and height must be positive")
    box = validate_bbox(bbox, CoordinateSpace.PIXEL,
                        bounds=[0, 0, float(width), float(height)])
    return [box[0] / width, box[1] / height, box[2] / width, box[3] / height]


def normalized_to_pixel(bbox: Sequence[float], width: int | float, height: int | float,
                        *, rounding: str = "floor_ceil") -> list[int]:
    if not math.isfinite(float(width)) or not math.isfinite(float(height)) or width <= 0 or height <= 0:
        raise ValueError("reference width and height must be positive")
    box = validate_bbox(bbox, CoordinateSpace.NORMALIZED)
    raw = [box[0] * width, box[1] * height, box[2] * width, box[3] * height]
    if rounding == "floor_ceil":
        result = [math.floor(raw[0]), math.floor(raw[1]), math.ceil(raw[2]), math.ceil(raw[3])]
    elif rounding == "round":
        result = [round(v) for v in raw]
    else:
        raise ValueError("rounding must be floor_ceil or round")
    return validate_bbox(result, CoordinateSpace.PIXEL,
                         bounds=[0, 0, float(width), float(height)])


def legacy_1000_to_normalized(bbox: Sequence[float]) -> list[float]:
    box = validate_bbox(bbox, CoordinateSpace.NORMALIZED_1000)
    return [value / 1000.0 for value in box]


def normalized_to_legacy_1000(bbox: Sequence[float]) -> list[float]:
    box = validate_bbox(bbox, CoordinateSpace.NORMALIZED)
    return [value * 1000.0 for value in box]


def clip_bbox(bbox: Sequence[float], bounds: Sequence[float],
              coordinate_space: CoordinateSpace | str) -> list[float]:
    """Clip an explicitly typed bbox and reject a zero-area result."""
    space = _space(coordinate_space)
    box = _finite_bbox(bbox)
    bound = validate_bbox(bounds, space, allow_zero_area=True)
    clipped = [max(bound[0], box[0]), max(bound[1], box[1]),
               min(bound[2], box[2]), min(bound[3], box[3])]
    return validate_bbox(clipped, space)


def _rect(value: Sequence[float], name: str) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError(f"{name} must contain four coordinates")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite coordinates")
    if result[2] < result[0] or result[3] < result[1]:
        raise ValueError(f"{name} must have non-negative extent")
    return result


@dataclass(frozen=True)
class PageCoordinateSpace:
    """The coordinate contract needed by a future page/crop renderer."""

    mediabox: tuple[float, float, float, float]
    cropbox: tuple[float, float, float, float]
    rotation: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mediabox", _rect(self.mediabox, "mediabox"))
        object.__setattr__(self, "cropbox", _rect(self.cropbox, "cropbox"))
        rotation = int(self.rotation) % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180, or 270 degrees")
        object.__setattr__(self, "rotation", rotation)
        if (self.cropbox[0] < self.mediabox[0] or self.cropbox[1] < self.mediabox[1]
                or self.cropbox[2] > self.mediabox[2] or self.cropbox[3] > self.mediabox[3]):
            raise ValueError("cropbox must be contained by mediabox")

    @property
    def crop_width(self) -> float:
        return self.cropbox[2] - self.cropbox[0]

    @property
    def crop_height(self) -> float:
        return self.cropbox[3] - self.cropbox[1]

    @property
    def rendered_width(self) -> float:
        return self.crop_height if self.rotation in (90, 270) else self.crop_width

    @property
    def rendered_height(self) -> float:
        return self.crop_width if self.rotation in (90, 270) else self.crop_height

    def as_dict(self) -> dict[str, object]:
        return {
            "id": "pdf-point-unrotated-page",
            "unit": "PDF_point",
            "origin": "top_left",
            "axis": "x_right_y_down",
            "bbox_space": "mediabox_unrotated",
            "cropbox": list(self.cropbox),
            "mediabox": list(self.mediabox),
            "rotation_degrees": self.rotation,
            "rotation_direction": "clockwise_for_rendered_view",
            "rendered_view": "cropbox_then_rotation",
        }


@dataclass(frozen=True)
class PixelBBox:
    x0: int
    y0: int
    x1: int
    y1: int
    clipped: bool
    scale: float

    def as_dict(self) -> dict[str, object]:
        return {"bbox": [self.x0, self.y0, self.x1, self.y1],
                "coordinate_space": CoordinateSpace.PIXEL.value,
                "clipped": self.clipped, "scale": self.scale}


def expand_bbox(bbox: Sequence[float], margin: float | Sequence[float],
                *, bounds: Sequence[float] | None = None) -> list[float]:
    """Expand a PDF-point bbox and optionally clip it to page bounds."""
    box = _rect(bbox, "bbox")
    if isinstance(margin, (int, float)):
        left = top = right = bottom = float(margin)
    else:
        if len(margin) != 4:
            raise ValueError("margin must be a number or four values")
        left, top, right, bottom = (float(v) for v in margin)
    if min(left, top, right, bottom) < 0:
        raise ValueError("margin values must be non-negative")
    expanded = [box[0] - left, box[1] - top, box[2] + right, box[3] + bottom]
    if bounds is not None:
        bound = _rect(bounds, "bounds")
        expanded = [max(bound[0], expanded[0]), max(bound[1], expanded[1]),
                    min(bound[2], expanded[2]), min(bound[3], expanded[3])]
    return expanded


def _rotate_local(box: tuple[float, float, float, float], width: float,
                  height: float, rotation: int) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    if rotation == 0:
        return box
    if rotation == 90:
        return height - y1, x0, height - y0, x1
    if rotation == 180:
        return width - x1, height - y1, width - x0, height - y0
    return y0, width - x1, y1, width - x0


def pdf_bbox_to_pixel(bbox: Sequence[float], page: PageCoordinateSpace, *,
                      scale: float = 1.0, margin: float | Sequence[float] = 0.0) -> PixelBBox:
    """Convert an unrotated PDF-point bbox to a clipped rendered pixel bbox.

    The source is clipped to the cropbox, translated to crop-local coordinates,
    rotated clockwise, then scaled.  Pixel edges use floor for the upper-left
    and ceil for the lower-right so the source region is not silently trimmed.
    """
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be positive")
    requested = expand_bbox(bbox, margin)
    source = expand_bbox(bbox, margin, bounds=page.cropbox)
    clipped = source != requested
    local = (source[0] - page.cropbox[0], source[1] - page.cropbox[1],
             source[2] - page.cropbox[0], source[3] - page.cropbox[1])
    rotated = _rotate_local(local, page.crop_width, page.crop_height, page.rotation)
    display = (page.rendered_width, page.rendered_height)
    pixel = [rotated[0] * scale, rotated[1] * scale,
             rotated[2] * scale, rotated[3] * scale]
    before = list(pixel)
    pixel = [max(0.0, min(display[0] * scale, pixel[0])),
             max(0.0, min(display[1] * scale, pixel[1])),
             max(0.0, min(display[0] * scale, pixel[2])),
             max(0.0, min(display[1] * scale, pixel[3]))]
    clipped = clipped or pixel != before
    if pixel[2] < pixel[0] or pixel[3] < pixel[1]:
        raise ValueError("bbox does not intersect the cropbox")
    return PixelBBox(math.floor(pixel[0]), math.floor(pixel[1]),
                     math.ceil(pixel[2]), math.ceil(pixel[3]), clipped, float(scale))


def pdf_to_pixel(bbox: Sequence[float], page: PageCoordinateSpace, *,
                 scale: float = 1.0, margin: float | Sequence[float] = 0.0) -> PixelBBox:
    """Named alias for the central PDF-point to pixel conversion."""
    return pdf_bbox_to_pixel(bbox, page, scale=scale, margin=margin)


def pixel_to_pdf(bbox: Sequence[float], page: PageCoordinateSpace, *,
                 scale: float = 1.0) -> list[float]:
    """Convert a rendered top-left pixel xyxy bbox back to PDF points."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be positive")
    width, height = page.rendered_width * scale, page.rendered_height * scale
    box = validate_bbox(bbox, CoordinateSpace.PIXEL, bounds=[0, 0, width, height])
    local = [v / scale for v in box]
    if page.rotation == 0:
        unrotated = local
    elif page.rotation == 90:
        unrotated = [local[1], page.crop_height - local[2],
                     local[3], page.crop_height - local[0]]
    elif page.rotation == 180:
        unrotated = [page.crop_width - local[2], page.crop_height - local[3],
                     page.crop_width - local[0], page.crop_height - local[1]]
    else:
        unrotated = [page.crop_width - local[3], local[0],
                     page.crop_width - local[1], local[2]]
    result = [unrotated[0] + page.cropbox[0], unrotated[1] + page.cropbox[1],
              unrotated[2] + page.cropbox[0], unrotated[3] + page.cropbox[1]]
    return validate_bbox(result, CoordinateSpace.PDF_POINT, bounds=page.cropbox)


def page_pixel_size(page: PageCoordinateSpace, *, scale: float = 1.0) -> tuple[int, int]:
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be positive")
    return math.ceil(page.rendered_width * scale), math.ceil(page.rendered_height * scale)
