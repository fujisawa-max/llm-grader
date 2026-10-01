"""Conservative visual-difference guidance for native model-answer extraction.

The low-resolution images are used only to locate ink added to a model-answer
copy of a question sheet. Text is still read from the original PDF text layer.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any


COMPARISON_SIZE = 64
BINARIZE_THRESHOLD = 240
SHIFT_TOLERANCE_CELLS = 1
PADDING_CELLS = 1
MIN_COMPONENT_CELLS = 2
MAX_DIFFERENCE_RATIO = 0.40
MAX_GEOMETRY_RELATIVE_DELTA = 0.03


def _render_binary(page: Any, size: int, threshold: int) -> tuple[list[list[bool]], float, float]:
    import pymupdf

    rect = page.rect
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(size / rect.width, size / rect.height),
        colorspace=pymupdf.csGRAY,
        alpha=False,
        annots=False,
    )
    samples = pixmap.samples
    grid: list[list[bool]] = []
    for y in range(size):
        source_y = min(pixmap.height - 1, int((y + 0.5) * pixmap.height / size))
        row = []
        for x in range(size):
            source_x = min(pixmap.width - 1, int((x + 0.5) * pixmap.width / size))
            row.append(samples[source_y * pixmap.stride + source_x] < threshold)
        grid.append(row)
    return grid, float(rect.width), float(rect.height)


def _dilate(grid: list[list[bool]], radius: int) -> list[list[bool]]:
    height, width = len(grid), len(grid[0]) if grid else 0
    result = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not grid[y][x]:
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        result[ny][nx] = True
    return result


def _components(mask: list[list[bool]]) -> list[list[tuple[int, int]]]:
    height, width = len(mask), len(mask[0]) if mask else 0
    seen: set[tuple[int, int]] = set()
    components = []
    for y in range(height):
        for x in range(width):
            if not mask[y][x] or (y, x) in seen:
                continue
            component = []
            pending = deque([(y, x)])
            seen.add((y, x))
            while pending:
                cy, cx = pending.popleft()
                component.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        point = (ny, nx)
                        if (0 <= ny < height and 0 <= nx < width and mask[ny][nx]
                                and point not in seen):
                            seen.add(point)
                            pending.append(point)
            components.append(component)
    return components


def _padded_boxes(mask: list[list[bool]], padding: int, min_cells: int) -> list[list[int]]:
    size = len(mask)
    boxes: list[list[int]] = []
    for component in _components(mask):
        if len(component) < min_cells:
            continue
        ys = [point[0] for point in component]
        xs = [point[1] for point in component]
        boxes.append([
            max(0, min(xs) - padding), max(0, min(ys) - padding),
            min(size, max(xs) + 1 + padding), min(size, max(ys) + 1 + padding),
        ])

    # Merge adjacent text fragments after padding, keeping unrelated regions
    # separate. Bounds use exclusive right/bottom edges.
    changed = True
    while changed:
        changed = False
        merged: list[list[int]] = []
        while boxes:
            current = boxes.pop()
            index = 0
            while index < len(boxes):
                other = boxes[index]
                if (current[0] <= other[2] and current[2] >= other[0]
                        and current[1] <= other[3] and current[3] >= other[1]):
                    current = [min(current[0], other[0]), min(current[1], other[1]),
                               max(current[2], other[2]), max(current[3], other[3])]
                    boxes.pop(index)
                    changed = True
                    index = 0
                else:
                    index += 1
            merged.append(current)
        boxes = merged
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def _overlaps(box: list[float] | None, other: list[float]) -> bool:
    return bool(box and len(box) == 4 and box[2] > other[0] and box[0] < other[2]
                and box[3] > other[1] and box[1] < other[3])


def compare_model_answer_pages(
    problem_pdf: Path,
    answer_pdf: Path,
    answer_ir: dict[str, Any],
    *,
    comparison_size: int = COMPARISON_SIZE,
    threshold: int = BINARIZE_THRESHOLD,
    shift_tolerance: int = SHIFT_TOLERANCE_CELLS,
    padding: int = PADDING_CELLS,
    min_component_cells: int = MIN_COMPONENT_CELLS,
    max_difference_ratio: float = MAX_DIFFERENCE_RATIO,
) -> dict[str, Any]:
    """Return selected answer span ids and auditable page-level diagnostics.

    A ``None`` value in ``allowed_element_ids_by_page`` means use ordinary text
    extraction for that page. A set means retain only spans overlapping newly
    added visual regions. Incompatible PDFs fail closed to ordinary extraction.
    """
    import pymupdf

    fallback = {
        "status": "fallback",
        "reason": None,
        "method": "native_text",
        "comparison_size": comparison_size,
        "threshold": threshold,
        "shift_tolerance_cells": shift_tolerance,
        "padding_cells": padding,
        "regions": [],
        "selected_span_count": 0,
        "allowed_element_ids_by_page": {},
        "page_diagnostics": [],
    }

    try:
        with pymupdf.open(str(problem_pdf)) as problem_doc, pymupdf.open(str(answer_pdf)) as answer_doc:
            if len(problem_doc) != len(answer_doc):
                fallback["reason"] = "page_count_mismatch"
                return fallback
            ir_pages = {int(page.get("page_index", index)): page
                        for index, page in enumerate(answer_ir.get("pages", []))}
            page_ids: dict[int, set[str] | None] = {}
            all_regions = []
            diagnostics = []
            selected_total = 0

            for page_index, (problem_page, answer_page) in enumerate(zip(problem_doc, answer_doc)):
                problem_rect, answer_rect = problem_page.rect, answer_page.rect
                dimensions = (problem_rect.width, problem_rect.height, answer_rect.width, answer_rect.height)
                if (problem_page.rotation or answer_page.rotation
                        or any(value <= 0 for value in dimensions)
                        or abs(problem_rect.width - answer_rect.width) / max(problem_rect.width, answer_rect.width) > MAX_GEOMETRY_RELATIVE_DELTA
                        or abs(problem_rect.height - answer_rect.height) / max(problem_rect.height, answer_rect.height) > MAX_GEOMETRY_RELATIVE_DELTA):
                    page_ids[page_index] = None
                    diagnostics.append({"page_index": page_index, "status": "fallback",
                                        "reason": "page_geometry_mismatch"})
                    continue

                problem_grid, _, _ = _render_binary(problem_page, comparison_size, threshold)
                answer_grid, answer_width, answer_height = _render_binary(answer_page, comparison_size, threshold)
                tolerant_problem = _dilate(problem_grid, shift_tolerance)
                diff = [[answer_grid[y][x] and not tolerant_problem[y][x]
                         for x in range(comparison_size)] for y in range(comparison_size)]
                diff_count = sum(sum(row) for row in diff)
                ratio = diff_count / float(comparison_size * comparison_size)
                if diff_count == 0 or ratio > max_difference_ratio:
                    page_ids[page_index] = None
                    diagnostics.append({"page_index": page_index, "status": "fallback",
                                        "reason": "no_added_region" if diff_count == 0 else "difference_area_too_large",
                                        "difference_ratio": round(ratio, 6)})
                    continue

                cell_boxes = _padded_boxes(diff, padding, min_component_cells)
                pdf_boxes = [[
                    round(box[0] * answer_width / comparison_size, 3),
                    round(box[1] * answer_height / comparison_size, 3),
                    round(box[2] * answer_width / comparison_size, 3),
                    round(box[3] * answer_height / comparison_size, 3),
                ] for box in cell_boxes]
                page_ir = ir_pages.get(page_index, {})
                selected_ids = {
                    str(element.get("element_id"))
                    for element in page_ir.get("elements", [])
                    if element.get("type") == "text" and element.get("element_id")
                    and any(_overlaps(element.get("bbox"), box) for box in pdf_boxes)
                }
                if not pdf_boxes or not selected_ids:
                    page_ids[page_index] = None
                    diagnostics.append({"page_index": page_index, "status": "fallback",
                                        "reason": "no_native_text_in_added_region",
                                        "difference_ratio": round(ratio, 6),
                                        "cell_regions": cell_boxes})
                    continue

                page_ids[page_index] = selected_ids
                selected_total += len(selected_ids)
                regions = [{"page_index": page_index, "cell_bbox": cell_box, "pdf_bbox": pdf_box}
                           for cell_box, pdf_box in zip(cell_boxes, pdf_boxes)]
                all_regions.extend(regions)
                diagnostics.append({"page_index": page_index, "status": "visual_difference",
                                    "difference_ratio": round(ratio, 6),
                                    "difference_cell_count": diff_count,
                                    "cell_regions": cell_boxes,
                                    "pdf_regions": pdf_boxes,
                                    "selected_span_count": len(selected_ids)})

            used = any(value is not None for value in page_ids.values())
            if not used:
                fallback["reason"] = "no_reliable_page_comparison"
                fallback["page_diagnostics"] = diagnostics
                return fallback
            return {
                "status": "used",
                "reason": None,
                "method": "visual_difference_guided_native_text",
                "comparison_size": comparison_size,
                "threshold": threshold,
                "shift_tolerance_cells": shift_tolerance,
                "padding_cells": padding,
                "regions": all_regions,
                "selected_span_count": selected_total,
                "allowed_element_ids_by_page": {
                    str(page_index): sorted(ids) if ids is not None else None
                    for page_index, ids in page_ids.items()
                },
                "page_diagnostics": diagnostics,
            }
    except (OSError, RuntimeError, ValueError) as exc:
        fallback["reason"] = "comparison_failed"
        fallback["detail"] = type(exc).__name__
        return fallback


def select_question_text_material(materials: list[Any]) -> Any | None:
    """Return a question sheet only when it is unique for this test."""
    question_sheets = [material for material in materials
                       if getattr(material, "material_type", None) == "question_sheet"]
    return question_sheets[0] if len(question_sheets) == 1 else None
