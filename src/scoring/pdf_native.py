"""PDF-native extraction behind a backend-neutral Document IR boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol


def native_vector_elements(drawings, page_index):
    """Stable native path evidence, including zero-area coordinate axes."""
    result = []
    for index, drawing in enumerate(drawings):
        rect = drawing.get("rect")
        if rect is None:
            continue
        horizontal = vertical = 0
        for item in drawing.get("items", []):
            if item[0] == "l":
                a, b = item[1:3]
                horizontal += int(abs(a.y-b.y) < 0.1 and abs(a.x-b.x) >= 1)
                vertical += int(abs(a.x-b.x) < 0.1 and abs(a.y-b.y) >= 1)
        result.append({"element_id": f"page-{page_index+1:04d}-drawing-{index:04d}",
            "type": "drawing", "bbox": [float(v) for v in rect], "reading_order": index,
            "source": "native_vector", "native": {"path_type": drawing.get("type"),
                "primitive_count": len(drawing.get("items", [])),
                "horizontal_lines": horizontal, "vertical_lines": vertical}})
    return result


IR_SCHEMA_VERSION = "question-document-ir.v1"
NORMALIZATION_VERSION = "conservative-v1"
QUALITY_SIGNAL_VERSION = "native-quality-v2"

# Keep this list intentionally small and configurable through the extractor
# options.  A font match is evidence for later review, not a semantic
# assertion that a span is mathematics.
DEFAULT_MATH_FONT_NAMES = (
    "cambriamath", "stix", "stix two math", "latin modern math",
    "xits math", "asana math",
)
MATH_TEXT_RE = re.compile(
    r"(?:π|∫|∑|∏|√|≤|≥|≠|≈|∞|\b(?:sin|cos|tan)\b\s*[A-Za-z𝑥𝑦π]|"
    r"[A-Za-z𝑥𝑦π]\s*[=+−×÷^_]\s*[A-Za-z0-9𝑥𝑦π])"
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_text(value: str) -> str:
    # Keep this intentionally conservative: whitespace only, no semantic rewrites.
    return " ".join(value.replace("\u00a0", " ").split())


def _bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        values = [float(value[i]) for i in range(4)]
    except (TypeError, ValueError, IndexError):
        return None
    return values if values[2] >= values[0] and values[3] >= values[1] else None


def _union(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(x[0] for x in boxes), min(x[1] for x in boxes),
            max(x[2] for x in boxes), max(x[3] for x in boxes)]


def _math_font_candidate(font: Any, names: tuple[str, ...]) -> bool:
    value = re.sub(r"\s+", " ", str(font or "").strip().lower())
    compact = value.replace(" ", "")
    return any(value == name or compact == name.replace(" ", "") for name in names)


def _horizontal_gap(left: list[float], right: list[float]) -> float:
    if left[2] < right[0]:
        return right[0] - left[2]
    if right[2] < left[0]:
        return left[0] - right[2]
    return 0.0


@dataclass
class DocumentIR:
    schema_version: str
    coordinate_space: dict[str, Any]
    source: dict[str, Any]
    parser: dict[str, Any]
    pages: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PdfNativeExtractor(Protocol):
    backend_name: str

    def extract(self, source_pdf: Path, *, source_sha256: str, material_id: str,
                output_dir: Path, options: dict[str, Any] | None = None) -> DocumentIR:
        """Extract native PDF information without invoking a vision model."""


class PyMuPdfNativeExtractor:
    """PyMuPDF implementation; no PyMuPDF objects escape this class."""

    backend_name = "pymupdf"

    def __init__(self, *, max_pages: int = 200):
        self.max_pages = max_pages

    @staticmethod
    def _span_element(page_index: int, block_index: int, line_index: int,
                      span_index: int, span: dict[str, Any], reading_order: int,
                      math_font_names: tuple[str, ...] = DEFAULT_MATH_FONT_NAMES) -> dict[str, Any]:
        text = str(span.get("text") or "")
        font = span.get("font")
        flags = []
        if not text.strip():
            flags.append("empty_text")
        if "�" in text:
            flags.append("replacement_character")
        math_font = _math_font_candidate(font, math_font_names)
        math_text = bool(MATH_TEXT_RE.search(text))
        math_like = math_font or math_text
        if math_like:
            flags.append("math_like_candidate")
        box = _bbox(span.get("bbox"))
        return {
            "element_id": f"page-{page_index + 1:04d}-span-{block_index:04d}-{line_index:04d}-{span_index:04d}",
            "type": "text",
            "bbox": box,
            "reading_order": reading_order,
            "native_text": text,
            "normalized_text": _normalise_text(text),
            "source": "pdf_text",
            "native": {
                "block_index": block_index,
                "line_index": line_index,
                "span_index": span_index,
                "font": font,
                "font_size": span.get("size"),
                "flags": span.get("flags"),
                "color": span.get("color"),
            },
            "quality_signals": {
                "character_count": len(text),
                "replacement_character_count": text.count("�"),
                "math_font_candidate": math_font,
                "math_text_candidate": math_text,
                "math_like_candidate": math_like,
                "superscript_candidate": False,
                "subscript_candidate": False,
            },
            "review_flags": flags,
        }

    @staticmethod
    def _apply_geometry_signals(elements: list[dict[str, Any]]) -> None:
        """Add conservative vertical-offset evidence without reordering spans."""
        text_elements = [e for e in elements if e.get("type") == "text" and e.get("bbox")]
        for element in text_elements:
            box = element["bbox"]
            size = float(element.get("native", {}).get("font_size") or 0)
            if size <= 0:
                continue
            # Only compare against nearby native math evidence.  This avoids
            # turning ordinary small Japanese annotations into math spans.
            neighbors = []
            for other in text_elements:
                if other is element or not other.get("quality_signals", {}).get("math_like_candidate"):
                    continue
                other_box = other["bbox"]
                if _horizontal_gap(box, other_box) > 24.0:
                    continue
                if min(box[3], other_box[3]) < max(box[1], other_box[1]) - 2:
                    continue
                neighbors.append(other)
            for other in neighbors:
                other_box = other["bbox"]
                other_size = float(other.get("native", {}).get("font_size") or 0)
                if other_size <= 0 or size > other_size * 0.9:
                    continue
                other_center = (other_box[1] + other_box[3]) / 2
                if box[3] <= other_center - other_size * 0.1:
                    element["quality_signals"]["superscript_candidate"] = True
                elif box[1] >= other_center + other_size * 0.1:
                    element["quality_signals"]["subscript_candidate"] = True
                if element["quality_signals"]["superscript_candidate"] or element["quality_signals"]["subscript_candidate"]:
                    element["review_flags"].append("vertical_offset_candidate")
                    break

    def extract(self, source_pdf: Path, *, source_sha256: str, material_id: str,
                output_dir: Path, options: dict[str, Any] | None = None) -> DocumentIR:
        import pymupdf

        options = options or {}
        configured_fonts = options.get("math_font_names", DEFAULT_MATH_FONT_NAMES)
        math_font_names = tuple(str(x) for x in configured_fonts)
        output_dir.mkdir(parents=True, exist_ok=True)
        images_dir = output_dir / "images" / "embedded"
        images_dir.mkdir(parents=True, exist_ok=True)
        pages: list[dict[str, Any]] = []
        embedded_seen: dict[int, str] = {}
        with pymupdf.open(str(source_pdf)) as document:
            if document.needs_pass:
                raise ValueError("encrypted PDF is not supported")
            if len(document) > self.max_pages:
                raise ValueError(f"PDF page count exceeds limit ({self.max_pages})")
            for page_index, page in enumerate(document):
                raw = page.get_text("dict")
                elements: list[dict[str, Any]] = []
                reading_order = 0
                text_blocks = 0
                replacement_count = 0
                characters = 0
                for block_index, block in enumerate(raw.get("blocks", [])):
                    if block.get("type") != 0:
                        continue
                    text_blocks += 1
                    for line_index, line in enumerate(block.get("lines", [])):
                        for span_index, span in enumerate(line.get("spans", [])):
                            element = self._span_element(page_index, block_index, line_index,
                                                         span_index, span, reading_order,
                                                         math_font_names)
                            reading_order += 1
                            characters += element["quality_signals"]["character_count"]
                            replacement_count += element["quality_signals"]["replacement_character_count"]
                            elements.append(element)

                self._apply_geometry_signals(elements)

                image_elements = []
                for image_index, image_info in enumerate(page.get_images(full=True)):
                    xref = int(image_info[0])
                    rects = page.get_image_rects(xref)
                    try:
                        extracted = document.extract_image(xref)
                    except Exception:
                        extracted = {}
                    image_hash = None
                    image_ref = None
                    if extracted.get("image"):
                        image_hash = hashlib.sha256(extracted["image"]).hexdigest()
                        image_ref = embedded_seen.get(xref)
                        if image_ref is None:
                            ext = re.sub(r"[^a-zA-Z0-9]+", "", str(extracted.get("ext") or "bin")) or "bin"
                            relative = Path("images") / "embedded" / f"xref-{xref}-{image_hash[:16]}.{ext}"
                            target = output_dir / relative
                            target.write_bytes(extracted["image"])
                            image_ref = relative.as_posix()
                            embedded_seen[xref] = image_ref
                    for rect_index, rect in enumerate(rects or [None]):
                        box = _bbox(rect)
                        image_elements.append({
                            "element_id": f"page-{page_index + 1:04d}-image-{image_index:04d}-{rect_index:02d}",
                            "type": "image",
                            "bbox": box,
                            "reading_order": None,
                            "native_text": None,
                            "normalized_text": None,
                            "source": "embedded_image",
                            "native": {"xref": xref, "width": extracted.get("width"),
                                       "height": extracted.get("height"), "format": extracted.get("ext")},
                            "artifact_ref": image_ref,
                            "sha256": image_hash,
                            "quality_signals": {"image_object": True},
                            "review_flags": [],
                        })
                drawing_boxes = []
                drawings = page.get_drawings()
                drawing_boxes = [box for d in drawings if (box := _bbox(d.get("rect")))]
                vector_elements = native_vector_elements(drawings, page_index)
                page_area = float(page.rect.width * page.rect.height) or 1.0
                image_boxes = [x["bbox"] for x in image_elements if x.get("bbox")]
                vector_bbox = _union(drawing_boxes)
                image_bbox = _union(image_boxes)
                flags = []
                if characters == 0:
                    flags.append("no_text_layer")
                if replacement_count:
                    flags.append("replacement_characters")
                if characters < 20 and (image_boxes or drawing_boxes):
                    flags.append("scanned_page_candidate")
                if image_bbox and (image_bbox[2] - image_bbox[0]) * (image_bbox[3] - image_bbox[1]) / page_area > 0.8:
                    flags.append("large_image_occupancy")
                has_text_layer = characters > 0
                scanned_page_candidate = characters < 20 and bool(image_boxes or drawing_boxes)
                large_image_occupancy = bool(
                    image_bbox and
                    (image_bbox[2] - image_bbox[0]) * (image_bbox[3] - image_bbox[1]) / page_area > 0.8
                )
                text_elements = [e for e in elements if e.get("type") == "text"]
                pages.append({
                    "page_index": page_index,
                    "width": float(page.rect.width),
                    "height": float(page.rect.height),
                    "rotation": int(page.rotation),
                    "cropbox": [float(x) for x in page.cropbox],
                    "mediabox": [float(x) for x in page.mediabox],
                    "elements": elements + image_elements,
                    "vector_elements": vector_elements,
                    "vector_summary": {"count": len(drawing_boxes), "bbox": vector_bbox,
                                        "occupancy": (sum(max(0, b[2]-b[0]) * max(0, b[3]-b[1]) for b in drawing_boxes) / page_area)},
                    "quality_signals": {
                        "has_text_layer": has_text_layer,
                        "no_text_layer": not has_text_layer,
                        "scanned_page_candidate": scanned_page_candidate,
                        "large_image_occupancy": large_image_occupancy,
                        "extracted_character_count": characters,
                        "replacement_character_count": replacement_count,
                        "text_block_count": text_blocks,
                        "image_count": len(image_elements),
                        "image_occupancy": ((max(0, image_bbox[2]-image_bbox[0]) * max(0, image_bbox[3]-image_bbox[1]) / page_area) if image_bbox else 0.0),
                        "vector_count": len(drawing_boxes),
                        "math_like_candidate_count": sum(
                            bool(e["quality_signals"].get("math_like_candidate")) for e in text_elements
                        ),
                        "math_font_candidate_count": sum(
                            bool(e["quality_signals"].get("math_font_candidate")) for e in text_elements
                        ),
                        "superscript_candidate_count": sum(
                            bool(e["quality_signals"].get("superscript_candidate")) for e in text_elements
                        ),
                        "subscript_candidate_count": sum(
                            bool(e["quality_signals"].get("subscript_candidate")) for e in text_elements
                        ),
                    },
                    "review_flags": flags,
                })
            config = {"options": options, "normalization_version": NORMALIZATION_VERSION,
                      "quality_signal_version": QUALITY_SIGNAL_VERSION,
                      "math_font_names": list(math_font_names),
                      "math_text_heuristic": "native-math-text-v2",
                      "geometry_heuristic": "vertical-offset-v1"}
            config["vector_evidence_version"] = "native-vector-paths-v1"
            parser = {"backend": self.backend_name, "library": "PyMuPDF",
                      "version": pymupdf.VersionBind, "config": config,
                      "config_hash": canonical_hash(config)}
            ir = DocumentIR(
                schema_version=IR_SCHEMA_VERSION,
                coordinate_space={"id": "pdf-point-unrotated-page", "origin": "top_left",
                                  "axis": "x_right_y_down", "unit": "PDF_point",
                                  "bbox_space": "mediabox_unrotated",
                                  "rotation": "page_rotation_degrees",
                                  "rotation_direction": "clockwise_for_rendered_view",
                                  "rendered_view": "cropbox_then_rotation",
                                  "basis": "page.cropbox and page.mediabox are included"},
                source={"sha256": source_sha256, "material_id": material_id,
                        "file_size_bytes": source_pdf.stat().st_size,
                        "page_count": len(pages)},
                parser=parser,
                pages=pages,
            )
        value = ir.as_dict()
        (output_dir / "document-ir.json").write_bytes(_json_bytes(value))
        pages_dir = output_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        for page in ir.pages:
            (pages_dir / f"page-{page['page_index'] + 1:04d}.json").write_bytes(_json_bytes(page))
        diagnostics_dir = output_dir.parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        (diagnostics_dir / "quality.json").write_bytes(_json_bytes({
            "schema_version": IR_SCHEMA_VERSION,
            "pages": [{"page_index": p["page_index"], "quality_signals": p["quality_signals"],
                        "review_flags": p["review_flags"]} for p in ir.pages],
        }))
        manifest = {"schema_version": IR_SCHEMA_VERSION, "source": ir.source,
                    "parser": ir.parser, "normalization_version": NORMALIZATION_VERSION,
                    "ir_sha256": canonical_hash(value)}
        (output_dir / "manifest.json").write_bytes(_json_bytes(manifest))
        return ir
