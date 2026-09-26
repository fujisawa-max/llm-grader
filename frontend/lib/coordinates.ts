export type CoordinateSpace = "pdf_point" | "pixel" | "normalized" | "normalized_1000";
export type BBox = [number, number, number, number];

/** Convert a canonical normalized bbox to rendered pixels.
 * Units are selected from metadata; values are never classified by range.
 */
export function normalizedToPixel(bbox: BBox, width: number, height: number): BBox {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("invalid reference dimensions");
  }
  if (bbox.some(value => !Number.isFinite(value) || value < 0 || value > 1)) {
    throw new Error("invalid normalized bbox");
  }
  if (bbox[0] >= bbox[2] || bbox[1] >= bbox[3]) throw new Error("zero-area normalized bbox");
  return [bbox[0] * width, bbox[1] * height, bbox[2] * width, bbox[3] * height];
}

export function toPixel(bbox: BBox, coordinateSpace: CoordinateSpace,
  width: number, height: number): BBox {
  if (coordinateSpace === "normalized") return normalizedToPixel(bbox, width, height);
  if (coordinateSpace === "pixel") return bbox;
  if (coordinateSpace === "normalized_1000") {
    return normalizedToPixel(bbox.map(value => value / 1000) as BBox, width, height);
  }
  throw new Error("pdf_point requires the PDF renderer transform");
}
