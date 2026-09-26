"""Teacher page rendering. PyMuPDF stays inside this adapter."""
from uuid import uuid4

from ..coordinate import page_pixel_size
from ..pdf_native import sha256_file
from ..vision_policy import page_space

PREVIEW_CONFIG = {"scale": 1.5, "max_width": 4096, "max_height": 4096, "max_pixels": 8_000_000,
                  "version": "review-page-preview-v1"}


class PyMuPdfPagePreviewRenderer:
    def render(self, source, page, output, config=None):
        import pymupdf

        config = config or PREVIEW_CONFIG
        width, height = page_pixel_size(page_space(page), scale=config["scale"])
        if (min(width, height) <= 0 or width > config["max_width"] or
                height > config["max_height"] or width * height > config["max_pixels"]):
            raise ValueError("preview_limits_exceeded")
        with pymupdf.open(source) as pdf:
            actual = pdf[page["page_index"]]
            if (actual.rotation != page["rotation"] or list(actual.cropbox) != page["cropbox"] or
                    list(actual.mediabox) != page["mediabox"]):
                raise ValueError("pdf_page_metadata_mismatch")
            pix = actual.get_pixmap(matrix=pymupdf.Matrix(config["scale"], config["scale"]),
                                    colorspace=pymupdf.csRGB, alpha=False, annots=True)
            if pix.width != width or pix.height != height:
                raise ValueError("preview_dimensions_mismatch")
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_name(f".{uuid4()}.png")
            temp.write_bytes(pix.tobytes("png"))
            temp.replace(output)
        return {"preview_width": width, "preview_height": height, "sha256": sha256_file(output),
                "scale": config["scale"], "renderer_version": pymupdf.VersionBind}
