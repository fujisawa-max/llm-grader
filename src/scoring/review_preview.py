"""Hash-checked page previews and shared-contract pixel highlights."""
import json
from uuid import uuid4

from .adapters.pdf_preview import PREVIEW_CONFIG, PyMuPdfPagePreviewRenderer
from .adapters.pdf_region import PyMuPdfRegionRenderer
from .coordinate import pdf_bbox_to_pixel, page_pixel_size
from .pdf_native import canonical_hash, sha256_file
from .review_document import ReviewError, regions
from .vision_policy import page_space, crop_geometry, DEFAULT_POLICY, region_pdf_bbox


def page_preview(store, ir, draft, page_index):
    if type(page_index) is not int or not 0 <= page_index < len(ir["pages"]):
        raise ReviewError("invalid_page_index", 422)
    page = ir["pages"][page_index]
    try:
        source = store.path("source.pdf")
        if sha256_file(source) != ir["source"]["sha256"]:
            raise ReviewError("source_pdf_integrity_error")
        identity = {"source_pdf_sha256": ir["source"]["sha256"], "page_index": page_index,
                    "config": PREVIEW_CONFIG}
        key = canonical_hash(identity)
        output = store.path(f"review/previews/{key}.png")
        metadata = store.path(f"review/previews/{key}.json")
        if metadata.exists():
            value = json.loads(metadata.read_text())
            if value["identity"] != identity or sha256_file(output) != value["sha256"]:
                raise ReviewError("preview_integrity_error")
            if (value["scale"] != PREVIEW_CONFIG["scale"] or
                    (value["preview_width"], value["preview_height"]) != page_pixel_size(
                        page_space(page), scale=PREVIEW_CONFIG["scale"])):
                raise ReviewError("preview_integrity_error")
        else:
            value = {**PyMuPdfPagePreviewRenderer().render(source, page, output), "identity": identity}
            temp = metadata.with_name(f".{uuid4()}.json")
            temp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            temp.replace(metadata)
        highlights = []

        def append(kind, key, bbox):
            pixel = pdf_bbox_to_pixel(bbox, page_space(page), scale=value["scale"])
            highlights.append({"source_type": kind, "source_id": key,
                               "pixel_bbox": pixel.as_dict()["bbox"],
                               "pixel_coordinate_space": "pixel",
                               "source_bbox": bbox, "source_coordinate_space": "pdf_point"})

        for node in draft["nodes"]:
            for region in node["source_regions"]:
                if region["page_index"] == page_index:
                    append("node", node["stable_key"], region_pdf_bbox(region, page))
        for region in regions(draft):
            if region["page_index"] == page_index:
                append(region["region_type"], region["region_id"], region_pdf_bbox(region, page))
        return output, {**value, "page_index": page_index, "page_count": len(ir["pages"]),
                        "regions": highlights, "page_rotation": page["rotation"]}
    except (OSError, ValueError, KeyError, IndexError):
        raise ReviewError("preview_render_or_integrity_error") from None


def native_region_preview(store, ir, region):
    """Native-only review crop; never an inference artifact or routing change."""
    try:
        source = store.path("source.pdf")
        if sha256_file(source) != ir["source"]["sha256"]:
            raise ReviewError("source_pdf_integrity_error")
        page = ir["pages"][region["page_index"]]
        crop = crop_geometry(page, region_pdf_bbox(region, page), region["region_type"], DEFAULT_POLICY)
        route = {**region, "crop": crop}
        key = canonical_hash({"pdf": ir["source"]["sha256"], "region": region, "crop": crop})
        output = store.path(f"review/previews/native-{key}.png")
        metadata = store.path(f"review/previews/native-{key}.json")
        if metadata.exists():
            value = json.loads(metadata.read_text())
            if sha256_file(output) != value["sha256"]:
                raise ReviewError("preview_integrity_error")
        else:
            render_target = output.with_name(f".{uuid4()}.png")
            value = PyMuPdfRegionRenderer().render(source, page, route, DEFAULT_POLICY, render_target)
            render_target.replace(output)
            temp = metadata.with_name(f".{uuid4()}.json")
            temp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            temp.replace(metadata)
        return output
    except (OSError, ValueError, KeyError, IndexError):
        raise ReviewError("preview_render_or_integrity_error") from None
