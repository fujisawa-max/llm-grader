"""Deterministic, non-authoritative views of stored vision responses.

No mathematical rewriting, JSON repair, model calls or executable text.
normalized_sha256 hashes the complete view excluding that hash field itself.
"""
import json
import re
from typing import Protocol

from .pdf_native import canonical_hash

KEYS = ("visible_text", "labels", "visual_elements", "spatial_relations")
ANSWERING = re.compile(
    r"答えは|解答は|解くと|解は|求めると|the answer is|solving gives|therefore|"
    r"(?:このグラフは|関数式は|これは)\s*(?:y\s*=|sin|cos)", re.I)


class VisionOutputParser(Protocol):
    name: str
    version: str

    def extract(self, text: str) -> dict: ...


def response_text(raw):
    """Prefer nonblank final content; reasoning is an explicit fallback only."""
    if isinstance(raw, str):
        return raw, "raw_text", []
    choices = raw.get("choices", []) if isinstance(raw, dict) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message", {})
    message = message if isinstance(message, dict) else {}
    flags = ["vision_output_truncated"] if choice.get("finish_reason") == "length" else []
    for field in ("content", "final", "answer", "reasoning_content", "reasoning"):
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            if field.startswith("reasoning"):
                flags.append("reasoning_output_requires_review")
            return value, f"choices[0].message.{field}", flags
    return "", "none", flags


def formula_line(text):
    """Conservative lexical filter, not a formula recognizer."""
    if not text.strip() or re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
        return False
    value = re.sub(r"\\(?:begin|end)\{[A-Za-z*]+\}", "", text)
    value = re.sub(r"\\[A-Za-z]+", "", value)
    value = re.sub(r"\b(?:sin|cos|tan|log|ln|lim|exp)\b", "", value)
    return not re.search(r"[A-Za-z]{2,}", value)


class UniMuMerOutputParser:
    name = "unimumer-output-parser"
    version = "unimumer-output-parser-v1"

    def extract(self, text):
        warnings, fragments = [], []
        # Fence delimiters are wrappers only. Retain exact source character
        # offsets; do not collapse digit/token spacing or reorder formulas.
        cursor = 0
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            start = cursor + len(line) - len(line.lstrip())
            if stripped.startswith("```"):
                pass
            elif formula_line(stripped):
                fragments.append({"text": stripped, "start": start, "end": start+len(stripped)})
            elif stripped:
                warnings.append("non_formula_text_excluded")
            cursor += len(line)
        if ANSWERING.search(text):
            fragments = []
            warnings.append("model_answering_detected")
        unique, seen = [], set()
        multiline_latex = "\\begin{" in text or "\\end{" in text
        for fragment in fragments:
            if multiline_latex or fragment["text"] not in seen:
                unique.append(fragment["text"])
                seen.add(fragment["text"])
        duplicate = len(unique) != len(fragments)
        if duplicate:
            warnings.append("exact_duplicate_removed")
        normalized = "\n".join(unique)
        if text.strip() and not normalized:
            warnings.append("formula_candidate_unresolved")
        return {"output": {"recognized_expression": normalized},
                "transcription_raw_candidate": "\n".join(f["text"] for f in fragments),
                "transcription_normalized": normalized, "duplicate_removed": duplicate,
                "source_fragments": fragments, "structured": False,
                "parse_status": "parsed" if normalized else "unresolved",
                "parser_warnings": sorted(set(warnings))}


def json_objects(text):
    """Decode whole objects, skipping their interiors. Never repair JSON."""
    decoder = json.JSONDecoder()
    objects, cursor = [], 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(text[start:])
            end = start + length
            objects.append((value, start, end))
            cursor = end
        except ValueError:
            cursor = start + 1
    return objects


def evidence_object(value):
    required = ("visible_text", "visual_elements", "spatial_relations")
    return (isinstance(value, dict) and all(k in value for k in required)
            and all(isinstance(value[k], list) and all(isinstance(x, str) for x in value[k])
                    for k in KEYS if k in value))


class RicohVisionOutputParser:
    name = "ricoh-output-parser"
    version = "ricoh-output-parser-v1"

    def extract(self, text):
        warnings, candidates, sources = [], [], []
        answering = bool(ANSWERING.search(text))
        for value, start, end in json_objects(text):
            if not evidence_object(value):
                continue
            # A schema echoed inside reasoning is not an observation. Empty
            # standalone/fenced JSON is valid, empty JSON amidst prose is not.
            outside = text[:start] + text[end:]
            wrapper_only = not re.sub(r"```(?:json)?", "", outside).strip()
            if not any(value.get(k) for k in KEYS) and not wrapper_only:
                warnings.append("json_template_ignored")
                continue
            if not any(value == v for v, _, _ in candidates):
                candidates.append((value, start, end))
        if len(candidates) == 1 and not answering:
            value, start, end = candidates[0]
            return {"output": {k: value[k] for k in KEYS if k in value},
                    "structured": True, "parse_status": "structured",
                    "source_fragments": [{"start": start, "end": end, "kind": "json_object"}],
                    "parser_warnings": warnings, "unstructured_observation": text}
        if len(candidates) > 1:
            warnings.append("ambiguous_json_candidates")
        if answering:
            warnings.append("model_answering_detected")
        # Only explicit machine-readable label lists are recoverable from
        # prose. Do not promote narrative guesses about curves/relations.
        recovered = {}
        if not answering and len(candidates) <= 1:
            for match in re.finditer(r"\b(visible_text|labels)\s*(?:は|=|:)\s*(?=\[)", text):
                try:
                    values, length = json.JSONDecoder().raw_decode(text[match.end():])
                    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                        continue
                    key = match[1]
                    target = recovered.setdefault(key, [])
                    for value in values:
                        if value not in target:
                            target.append(value)
                    sources.append({"field": key, "start": match.end(), "end": match.end()+length})
                except ValueError:
                    pass
        warnings.append("vision_output_parse_failed")
        if recovered:
            warnings.append("partial_structured_extraction")
        return {"output": {"unparsed_text": text, **recovered}, "structured": False,
                "unstructured_observation": text,
                "parse_status": "partial" if recovered else "unstructured",
                "source_fragments": sources, "parser_warnings": sorted(set(warnings))}


PARSERS = {"math_ocr": UniMuMerOutputParser(), "ocr": RicohVisionOutputParser()}


def parse_output(raw, role, native, *, source_raw_sha256=None, region_id=None, inherited_flags=()):
    parser = PARSERS[role]
    text, field, flags = response_text(raw)
    result = parser.extract(text)
    if not text.strip():
        flags.append("vision_output_empty")
    if role == "math_ocr":
        # Preserve H.2-C's conservative whitespace-only comparison.
        if "".join(result["transcription_normalized"].split()) != "".join("".join(native).split()):
            flags.append("native_vision_disagreement")
    if "model_answering_detected" in result["parser_warnings"]:
        flags.append("possible_answer_inference")
    flags = sorted(set(flags + result["parser_warnings"] + list(inherited_flags)))
    value = {"schema_version": "question-region-vision-evidence.v1", **result,
             "parser_name": parser.name, "parser_version": parser.version,
             "source_raw_sha256": source_raw_sha256 or canonical_hash(raw),
             "raw_hash_basis": "artifact_bytes" if source_raw_sha256 else "canonical_json",
             "model_role": role, "region_id": region_id, "source_field": field,
             "native_fragments": native, "authoritative": False,
             "review_required": bool(flags), "review_flags": flags,
             "parser_warnings": sorted(set(flags)),
             "hash_convention": "canonical-json-excluding-normalized_sha256"}
    value["normalized_sha256"] = canonical_hash(value)
    return value


def unwrap_math_output(text):
    """Remove complete outer presentation wrappers without changing math."""
    value = text.strip()
    for _ in range(4):
        previous = value
        fence = re.fullmatch(r'```(?:latex|tex)?\s*\n?([\s\S]*?)\n?```', value, re.I)
        if fence:
            value = fence.group(1).strip()
        else:
            for left, right in [('$$', '$$'), ('$', '$'), (r'\(', r'\)'), (r'\[', r'\]')]:
                if value.startswith(left) and value.endswith(right) and len(value) >= len(left)+len(right):
                    value = value[len(left):-len(right)].strip()
                    break
        if previous == value:
            break
    if '$' in value or '```' in value or any(marker in value for marker in (r'\[', r'\]', r'\(', r'\)')):
        raise ValueError('math_wrapper_invalid')
    return value
