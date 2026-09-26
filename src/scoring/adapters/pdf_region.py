"""Region rendering backend; PyMuPDF objects never cross this boundary."""
from pathlib import Path
from typing import Protocol

from ..pdf_native import sha256_file
from ..vision_policy import crop_geometry


class PdfRegionRenderer(Protocol):
    def render(self, source: Path, page: dict, route: dict, config: dict, output: Path) -> dict: ...


class PyMuPdfRegionRenderer:
    def render(self, source, page, route, config, output):
        import pymupdf

        geometry = crop_geometry(page, route["crop"]["source_bbox"], route["region_type"], config)
        if geometry != route["crop"]:
            raise ValueError("crop_plan_mismatch")
        with pymupdf.open(source) as pdf:
            actual = pdf[route["page_index"]]
            if (actual.rotation != page["rotation"] or list(actual.cropbox) != page["cropbox"]
                    or list(actual.mediabox) != page["mediabox"]):
                raise ValueError("pdf_page_metadata_mismatch")
            # get_pixmap clip uses the displayed (rotated) page coordinates.
            # Coordinate utility has already performed crop-local rotation.
            scale = geometry["scale"]
            clip = pymupdf.Rect([v/scale for v in geometry["pixel_bbox"]])
            pix = actual.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                                    colorspace=pymupdf.csRGB, alpha=False, annots=True)
            if (pix.width > config["max_width"] or pix.height > config["max_height"]
                    or pix.width*pix.height > config["max_pixels"]):
                raise ValueError("render_limits_exceeded")
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_suffix(".tmp")
            temp.write_bytes(pix.tobytes("png"))
            temp.replace(output)
            return {**geometry, "width": pix.width, "height": pix.height,
                    "sha256": sha256_file(output), "renderer": "PyMuPDF", "renderer_version": pymupdf.VersionBind,
                    "source_pdf_sha256": sha256_file(source), "page_index": route["page_index"],
                    "region_id": route["region_id"], "layers": "page-images-text-vectors-annotations"}
