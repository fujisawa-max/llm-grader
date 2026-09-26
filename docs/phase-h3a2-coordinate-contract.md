# H.3-A answer coordinate contract

New answer extraction artifacts use the explicit `coordinate_space`
`normalized` contract. Bboxes remain xyxy (`[x0, y0, x1, y1]`), use a
top-left origin with x increasing right and y increasing down, and each value
is a float in the inclusive range 0.0–1.0 relative to the supplied source page
image. The reference image width and height are recorded with extraction
metadata.

The crop transform is deterministic: `x_pixel = x_normalized * source_width`
and `y_pixel = y_normalized * source_height`. The crop rectangle uses floor
for its upper-left and ceil for its lower-right, then applies the configured
source-pixel margin and clips to the source image. Requested and clipped pixel
rectangles remain in crop metadata; zero-area results are rejected.

The supported explicit spaces are `pdf_point` (the existing unrotated PDF
point/CropBox/MediaBox/rotation contract), `pixel` (source/rendered image
pixels), `normalized` (canonical 0.0–1.0), and `normalized_1000` (legacy 0–1000
model responses and historical artifacts). No coordinate unit is inferred from
the values.

Old model/checkpoint layouts are read at a compatibility boundary only when
their caller declares `normalized_1000`; conversion divides by 1000.0 into an
in-memory canonical layout. Raw model responses and old artifacts remain
unchanged. A new layout without explicit coordinate metadata is rejected as
`AMBIGUOUS_COORDINATE_SPACE`.

Ricoh H.3-A raw output is retained as returned by the model. Its normalized view
is validated as `normalized` and carries `coordinate_version:
coordinate-contract.v2`; raw output is never rewritten to appear canonical.
