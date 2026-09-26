"""Ricoh-guided crops and resumable, region-level formula recognition."""

import math
from copy import deepcopy
from pathlib import Path

from .core import digest, effective_generation, identifier, read_json, write_json
from .coordinate import (CoordinateSpace, COORDINATE_CONTRACT_VERSION,
                          legacy_1000_to_normalized, normalized_to_pixel,
                          validate_bbox)
from .math_ocr import parse_math_response


def canonicalize_layout(value, *, source_coordinate_space: str | None = None):
    """Convert an explicitly typed layout to the v2 normalized representation.

    Raw model/checkpoint JSON is never modified by this helper.  Callers that
    read an old checkpoint must pass its known legacy contract explicitly;
    values are never classified by their magnitude.
    """
    space = value.get("coordinate_space") or source_coordinate_space
    if space is None:
        raise ValueError("AMBIGUOUS_COORDINATE_SPACE")
    if space not in {CoordinateSpace.NORMALIZED.value, CoordinateSpace.NORMALIZED_1000.value}:
        raise ValueError("layout coordinate_space must be normalized or normalized_1000")
    result = deepcopy(value)
    result["regions"] = []
    for original in value.get("regions", []):
        region = dict(original)
        box = region.get("bbox")
        if space == CoordinateSpace.NORMALIZED_1000.value:
            box = legacy_1000_to_normalized(box)
        else:
            box = validate_bbox(box, CoordinateSpace.NORMALIZED)
        region["bbox"] = box
        region["coordinate_space"] = CoordinateSpace.NORMALIZED.value
        region["coordinate_version"] = COORDINATE_CONTRACT_VERSION
        result["regions"].append(region)
    result["coordinate_space"] = CoordinateSpace.NORMALIZED.value
    result["coordinate_version"] = COORDINATE_CONTRACT_VERSION
    if space == CoordinateSpace.NORMALIZED_1000.value:
        result["source_coordinate_space"] = CoordinateSpace.NORMALIZED_1000.value
    return result


def validate_layout(value, page_id, question_ids, *, source_coordinate_space=None):
    value = canonicalize_layout(value, source_coordinate_space=source_coordinate_space)
    if value.get("page_id") != page_id or type(value.get("needs_review")) is not bool:
        raise ValueError("領域結果のページID・needs_reviewが不正")
    coverage = value.get("questions")
    regions = value.get("regions")
    if not isinstance(coverage, list) or not isinstance(regions, list) or len(regions) > 32:
        raise ValueError("領域または設問対応が不正")
    ids = [q.get("question_id") for q in coverage]
    if len(ids) != len(set(ids)) or set(ids) != set(question_ids):
        raise ValueError("領域結果の設問対応に欠落・重複・不明IDがあります")
    seen = set()
    for region in regions:
        rid = identifier(region.get("region_id"))
        if rid in seen or region.get("question_id") not in question_ids:
            raise ValueError("領域IDが重複または設問IDが不明")
        seen.add(rid)
        if region.get("kind") not in {"math", "graph", "text"}:
            raise ValueError("領域の種類が不正")
        box = region.get("bbox")
        try:
            validate_bbox(box, CoordinateSpace.NORMALIZED)
        except ValueError as exc:
            raise ValueError("領域座標はnormalized 0.0〜1.0の[x0,y0,x1,y1]で正の幅と高さが必要") from exc
        if region["kind"] == "math" and (box[2]-box[0])*(box[3]-box[1]) > 0.5:
            raise ValueError("数式領域がページの半分を超えています。計算のまとまりごとに分割が必要")
        if not isinstance(region.get("description"), str) or not region["description"].strip():
            raise ValueError("領域の説明がありません")
    for question in coverage:
        status = question.get("status")
        if status not in {"located", "blank", "no_math", "unreadable"}:
            raise ValueError("設問の領域検出状態が不正")
        if not isinstance(question.get("reason"), str) or not question["reason"].strip():
            raise ValueError("設問の領域判定理由がありません")
        math_regions = [r for r in regions if r["question_id"] == question["question_id"]
                        and r["kind"] == "math"]
        # A graph/text region is a valid located answer for a no_math question;
        # only formula coverage must agree with the status.
        answer_regions = [r for r in regions if r["question_id"] == question["question_id"]]
        if status == "located" and not answer_regions:
            raise ValueError("数式領域と設問の検出状態が矛盾しています")
        if status == "blank" and math_regions:
            # Preserve the region evidence, but never treat contradictory
            # "blank" metadata as an empty answer.
            question["status"] = "unreadable"
            question["reason"] += " 数式領域が検出されたため未記入判定を要確認に変更。"
            value["needs_review"] = True
    return value


def crop_image(source, bbox, destination, padding=12, *, coordinate_space=None):
    """Copy native pixels; never resize the page or alter the original."""
    import pymupdf

    if coordinate_space is None:
        raise ValueError("coordinate_space is required; do not infer bbox units from values")
    space = CoordinateSpace(coordinate_space)
    if space is CoordinateSpace.PDF_POINT:
        raise ValueError("pdf_point bbox requires the PDF page transform before image crop")
    pix = pymupdf.Pixmap(str(source))
    width, height = pix.width, pix.height
    if space is CoordinateSpace.NORMALIZED:
        pixels = normalized_to_pixel(bbox, width, height)
    elif space is CoordinateSpace.NORMALIZED_1000:
        pixels = normalized_to_pixel(legacy_1000_to_normalized(bbox), width, height)
    elif space is CoordinateSpace.PIXEL:
        pixels = validate_bbox(bbox, CoordinateSpace.PIXEL, bounds=[0, 0, width, height])
    else:  # pragma: no cover - CoordinateSpace is exhaustive
        raise ValueError("unsupported crop coordinate space")
    x0 = max(0, math.floor(pixels[0]) - padding)
    y0 = max(0, math.floor(pixels[1]) - padding)
    x1 = min(width, math.ceil(pixels[2]) + padding)
    y1 = min(height, math.ceil(pixels[3]) + padding)
    if x1-x0 < 4 or y1-y0 < 4:
        raise ValueError("切り出した画像が小さすぎます")
    rectangle = pymupdf.IRect(x0, y0, x1, y1)
    crop = pymupdf.Pixmap(pix.colorspace, rectangle, pix.alpha)
    crop.copy(pix, rectangle)
    crop.set_origin(0, 0)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != crop.tobytes("png"):
            raise ValueError("保存済み切り出し画像が入力・領域指定と一致しません")
    else:
        destination.write_bytes(crop.tobytes("png"))
    return {"bbox_pixels": [x0, y0, x1, y1], "coordinate_space": CoordinateSpace.PIXEL.value,
            "source_bbox": list(bbox), "source_coordinate_space": space.value,
            "coordinate_version": COORDINATE_CONTRACT_VERSION,
            "page_size": [width, height],
            "crop_size": [x1-x0, y1-y0], "padding_pixels": padding,
            "image_sha256": digest(destination), "renderer": f"PyMuPDF {pymupdf.VersionBind}"}


def process_regions(page, ricoh, layout, folder, config, prompt, checkpoint, client=None):
    """Run crops, or validate stored crop checkpoints when client is absent."""
    pid = page["page_id"]
    settings = config["models"]["math_ocr"]
    parser_hash = digest(Path(__file__).with_name("math_ocr.py"))
    region_results = []
    for region in layout["regions"]:
        if region["kind"] != "math":
            continue
        rid = region["region_id"]
        image_path = folder / "regions" / pid / f"{rid}.png"
        if client is None and not image_path.exists():
            raise ValueError(f"成功済みの切り出し画像が必要: {pid}/{rid}")
        metadata = crop_image(page["path"], region["bbox"], image_path,
                              coordinate_space=region.get("coordinate_space", layout.get("coordinate_space")))
        materials = {"page_id": pid, "region": region, "crop": metadata,
                     "source_sha256": digest(page["path"]), "ricoh": ricoh,
                     "layout": layout}
        result_folder = folder / "regions" / pid / rid
        if client is not None:
            print(f"{pid}/{rid} ({region['question_id']}): unimumer OCR", flush=True)
            value = checkpoint(client, result_folder, "transcription", prompt, materials,
                               [(rid, image_path)], lambda v: v,
                               parser=lambda raw: parse_math_response(raw, pid),
                               parser_signature=parser_hash)
        else:
            status = read_json(result_folder / "transcription.status.json")
            result_path = result_folder / "transcription.json"
            expected = {"model": settings,
                        "generation": effective_generation(config, "math_ocr"),
                        "prompt": prompt, "materials": materials,
                        "images": [[rid, metadata["image_sha256"]]], "parser_sha256": parser_hash}
            if (status.get("state") != "success" or status.get("signature") != expected
                    or status.get("result_sha256") != digest(result_path)):
                raise ValueError(f"領域OCRが失敗・変更済み: {pid}/{rid}")
            value = read_json(result_path)
        region_results.append({**region, **metadata, "image": str(image_path.relative_to(folder)),
                               "ocr": value})
    aggregate = {"page_id": pid, "coordinate_space": CoordinateSpace.NORMALIZED.value,
                 "coordinate_version": COORDINATE_CONTRACT_VERSION,
                 "regions": region_results, "coverage": layout["questions"],
                 "layout_needs_review": layout["needs_review"],
                 "source_sha256": digest(page["path"]),
                 "text": "\n".join(r["ocr"]["text"] for r in region_results),
                 "latex": [formula for r in region_results for formula in r["ocr"]["latex"]],
                 "uncertainties": [{"location": "regions", "candidates": [],
                                    "reason": "領域の位置と数式の対応を元画像で確認すること"}]}
    if client is not None:
        write_json(folder / f"{pid}.json", aggregate)
    elif read_json(folder / f"{pid}.json") != aggregate:
        raise ValueError("領域OCRの集約結果が変更されています")
    return aggregate


def for_question(aggregate, question_id):
    regions = [r for r in aggregate["regions"] if r["question_id"] == question_id]
    return {**aggregate, "regions": regions,
            "coverage": [q for q in aggregate["coverage"] if q["question_id"] == question_id],
            "text": "\n".join(r["ocr"]["text"] for r in regions),
            "latex": [f for r in regions for f in r["ocr"]["latex"]]}
