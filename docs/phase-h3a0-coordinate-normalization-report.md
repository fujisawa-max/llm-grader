# Phase H.3-A.0 Coordinate Normalization Contract Migration Report

## 1. Previous coordinate contract

The student-answer Ricoh adapter and `regions.crop_image` interpreted answer
image boxes as integer xyxy values in a 0–1000 normalized space. The H.2-C
`locate` response schema and `prompts/locate.md` used the same legacy model
contract. Native question IR and review geometry were already PDF-point based;
their contract was not changed.

## 2. Inventory

* **Actual legacy normalized_1000:** the H.2-C locate response/checkpoint and
  old answer-layout checkpoints. Nine checked-in run layouts have no field in
  the layout JSON, but their immutable run manifests contain the old locate
  prompt explicitly describing `[0,0]`–`[1000,1000]`; the compatibility reader
  uses that provenance, never the values, to identify them.
* **Pixel:** answer crop rectangles and review preview `pixel_bbox` values.
* **PDF:** Document IR, question structure, native review regions, and the
  existing PDF renderer use PDF-point coordinates with the existing origin,
  CropBox/MediaBox, and rotation rules.
* **Unrelated literals:** maximum text/node limits and HTTP error truncation
  values containing `1000` are not coordinate conversions.
* **Historical H.3-A raw/normalized artifacts:** retained unchanged as
  historical evidence; they predate this contract and are not rewritten.

## 3. New canonical contract

New normalized bboxes are `coordinate_space: "normalized"`, xyxy, top-left
origin, x-right/y-down, and every value is in the inclusive range 0.0–1.0.

## 4. Coordinate spaces

`pdf_point`, `pixel`, `normalized`, and legacy `normalized_1000` are represented
by `CoordinateSpace` in `src/scoring/coordinate.py`. Values never select their
own space.

## 5. Origin / bbox convention

PDF point geometry remains unrotated native page geometry. Image geometry is
top-left, x-right/y-down. Bboxes remain xyxy; no xywh migration was made.

## 6. Files changed

The central utility is `src/scoring/coordinate.py`. H.2-C layout validation and
crop handling are in `src/scoring/regions.py`, CLI/schema/prompt boundaries in
`src/scoring/cli.py`, `src/scoring/schemas.py`, and `prompts/locate.md`, and
H.3-A Ricoh/crop metadata in `src/scoring/student_answer_runtime.py` and
`src/scoring/student_answer.py`. Review pixel metadata and the frontend type
contract were extended additively.

## 7. Central coordinate utilities

`pixel_to_normalized`, `normalized_to_pixel`,
`legacy_1000_to_normalized`, `normalized_to_legacy_1000`, `pdf_to_pixel`,
`pixel_to_pdf`, `clip_bbox`, and `validate_bbox` now provide the conversion and
validation boundary. Pixel rounding occurs only when producing a crop.

## 8. Legacy compatibility

Legacy conversion is exactly `/ 1000.0` and only accepts an explicit
`normalized_1000` declaration. Old raw artifacts are not rewritten. The CLI
uses the immutable pre-v2 run manifest prompt to identify the old checkpoint
contract; an unknown artifact is rejected.

## 9. Ambiguous legacy handling

`canonicalize_layout` and `validate_layout` raise
`AMBIGUOUS_COORDINATE_SPACE` when neither the layout nor a trusted provenance
boundary declares its space. No value-range heuristic remains.

## 10. Schema/version changes

New derived layout and answer artifacts carry
`coordinate_version: "coordinate-contract.v2"`. H.2-C new responses require
`coordinate_space: "normalized"` and numeric bbox limits 0–1. Historical raw
schemas are not rewritten.

## 11. Migration decision

No database migration was added. Coordinate bboxes are artifact/API metadata,
and the existing database stores source/context/hash references rather than
these image bbox arrays.

## 12. H.2-B changes

None to native PDF IR geometry. PDF point, page origin, rotation, and
CropBox/MediaBox behavior remain unchanged.

## 13. H.2-C changes

Locate prompts/schema now emit canonical normalized coordinates. Legacy
checkpoints are converted in memory at the explicit reader boundary, and
formula crop metadata records source and pixel coordinate spaces.

## 14. H.2-D changes

Review preview highlights continue to use pixel bboxes; responses now label
`pixel_coordinate_space: "pixel"` and `source_coordinate_space: "pdf_point"`.

## 15. H.2-E compatibility

No confirmation, correction, TestQuestion content, or historical hash was
changed.

## 16. H.3-A changes

Ricoh reconstruction output requires canonical normalized coordinates. Formula
crop requests pass the region's declared space to the central crop utility;
missing metadata is rejected rather than guessed.

## 17. Ricoh raw vs normalized coordinate handling

The model response/raw envelope remains retained as returned. The normalized
view validates each bbox as canonical normalized and adds explicit contract
metadata. A legacy model response is not silently divided in the H.3-A
adapter; it must be handled by a declared legacy adapter boundary.

## 18. API changes

Review preview metadata labels pixel and source spaces. The H.2-C response
schema and H.3-A normalized artifacts include coordinate metadata; no endpoint
returns a new 0–1000 normalized contract.

## 19. Frontend changes

Review metadata types now carry coordinate-space labels, and
`frontend/lib/coordinates.ts` provides explicit normalized/pixel conversion.
Existing PDF preview continues consuming its explicitly named pixel bbox.

## 20. Hash / artifact compatibility

New canonical serialization may produce a new derived hash. Historical raw,
review, confirmation, correction, and reconstruction hashes are not recomputed.

## 21. Existing artifact immutability

No existing artifact, sample question, source image/PDF, or persistent row was
rewritten. Model/runtime calls were not made.

## 22. Conversion examples

`[500,250,1500,750]` pixels on a 2000×1000 image becomes
`[0.25,0.25,0.75,0.75]`. Explicit legacy
`[250,250,750,750]` in `normalized_1000` becomes the same canonical bbox.

## 23. Round-trip result

Golden, non-square, edge, clipping, and PDF rotation round-trip tests pass.

## 24. Legacy crop equivalence

The explicit legacy crop path divides by 1000 and uses the same floor/ceil and
padding behavior as the canonical path; the crop regression tests pass.

## 25–27. sampleQ1/Q2/Q3 regression

No sample data was mutated. Question-side native/PDF geometry tests pass, and
the existing authoritative content and asset hashes remain untouched.

## 28. H.3-A synthetic regression

The answer crop tests cover 100×200, 200×400, and 150×300 pages, canonical
normalized coordinates, explicit legacy coordinates, edge clipping, and missing
coordinate metadata rejection. Ricoh normalized-view tests verify the metadata.

## 29. Database validation

No migration was needed. A read-only Alembic check was attempted against the
configured PostgreSQL endpoint, but the persistent container was unavailable
(`psycopg OperationalError: connection is bad`); no reset or write was made.

## 30. Backend tests

31 targeted tests covering coordinate, H.2-C crop/layout, H.3-A runtime
contract, schema, and pipeline behavior pass. Ruff is clean. The full
`unittest`/`pytest` runs still stop in the pre-existing Python 3.14 Starlette
`TestClient` portal hang before completion; this is outside the coordinate
implementation and remains a validation blocker.

## 31. Frontend validation

Using Node v22.14.0, typecheck, lint, and production build pass. Lint retains
one pre-existing React hook warning in `app/tests/[testId]/page.tsx`.

## 32. Playwright

Not run; no browser behavior was changed beyond additive metadata types.

## 33. Model execution audit

Ricoh, Uni-MuMER, and Ornith calls were all 0 for H.3-A.0.

## 34. Problems / limitations

The old H.3-A artifacts remain old-schema historical records by design. A
future runtime smoke must use the new Ricoh prompt/schema and visually verify
the resulting source crop.

## 35. Remaining legacy usage

Legacy 0–1000 remains only in raw/historical artifacts, explicit compatibility
conversion, and tests. No new internal canonical normalized output uses it.

## 36. Final status

**H.3-A.0: NOT COMPLETE in this environment** because the required full test
completion and persistent PostgreSQL validation are blocked by external
environment issues. The coordinate migration implementation and targeted
regressions are complete.

## 37. H.3-A.1 readiness

The code is ready for a new no-model review of H.3-A.1 runtime smoke after the
TestClient/PG environment blockers are resolved. H.3-A.1 must still revalidate
actual model grounding; this phase did not run models.
