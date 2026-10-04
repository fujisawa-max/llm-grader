"""Bounded source-PDF formula transcription; proposals never mutate drafts."""
from __future__ import annotations

import base64
import logging
from hashlib import sha256
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz

from .adapters.question_vision import PROMPTS
from .core import LocalClient, generation_payload, image_content
from .vision_output import response_text

logger = logging.getLogger(__name__)


class MathOCRError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def math_like(text):
    return bool(re.search(r'[=+^_]|\\(?:frac|sqrt)|\b(?:TP|FP|TN|FN)\b', text)) or bool(re.fullmatch(r'\s*[\d.]+\s*', text))


def source_regions(segments, text):
    """Only uniquely aligned immutable source lines; never infer replacement prose."""
    selected = []
    cursor = 0
    for segment in sorted(segments, key=lambda s: s.get('reading_order', 0)):
        original = segment.get('original_text', segment.get('text', ''))
        box = segment.get('bbox')
        if not original.strip() or not math_like(original) or not box:
            continue
        matches = list(re.finditer(r'(?m)^' + re.escape(original) + r'$', text))
        if len(matches) != 1 or matches[0].start() < cursor:
            continue
        start, end = matches[0].span()
        item = {'page_index': segment['page_index'], 'bbox': list(box), 'start': start, 'end': end,
                'segment_ids': [segment['id']]}
        if selected:
            previous = selected[-1]
            a, b = previous['bbox'], box
            if (previous['page_index'] == item['page_index'] and not text[previous['end']:start].strip()
                    and -4 <= b[1] - a[3] <= 24 and b[0] < a[2] + 24 and b[2] > a[0] - 24):
                previous.update(end=end, bbox=[min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])])
                previous['segment_ids'].append(segment['id'])
                cursor = end
                continue
        selected.append(item)
        cursor = end
    return selected


class SourceMathOCR:
    def __init__(self, manager, profile_id='math_ocr'):
        self.manager, self.profile_id = manager, profile_id

    def propose(self, path: Path, segments, text):
        regions = source_regions(segments, text)
        result = {'original_text': text, 'normalized_text': text, 'reconstructed_text': text, 'status': 'no_change', 'confidence': None,
                  'warnings': [], 'changes': [], 'profile': self.profile_id, 'model': '', 'math_regions': []}
        if not regions:
            return result
        if len(regions) > 8:
            raise ValueError('math_region_limit')
        # Validate and render before starting the model. Never accept page-sized crops.
        crops = []
        with fitz.open(path) as document:
            for region in regions:
                page_index = region['page_index']
                box = region['bbox']
                if (type(page_index) is not int or not 0 <= page_index < len(document)
                        or len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)):
                    raise ValueError('math_source_invalid')
                page = document[page_index]
                rect = fitz.Rect(box)
                if rect.is_empty or not page.rect.contains(rect):
                    raise ValueError('math_source_invalid')
                clip = (rect + (-6, -6, 6, 6)) & page.rect
                if clip.get_area() > page.rect.get_area() * .35 or clip.get_area() * 4 > 4_000_000:
                    raise ValueError('math_crop_too_large')
                image = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip).tobytes('png')
                region['crop_bbox'] = list(clip)
                region['crop_sha256'] = sha256(image).hexdigest()
                crops.append(image)
        logger.info('math OCR runtime ensure start profile=%s regions=%s', self.profile_id, len(regions))
        try:
            ready = self.manager.ensure_running(self.profile_id)
        except Exception as exc:
            code = 'math_runtime_start_timeout' if 'timeout' in str(exc).lower() else 'math_runtime_start_failed'
            raise MathOCRError(code) from exc
        if ready.get('ok') is False or ready.get('state') != 'ready':
            raise MathOCRError('math_runtime_unavailable')
        logger.info('math OCR runtime ready profile=%s', self.profile_id)
        profile = ready['profile']
        result['model'] = profile['model_id']
        result['runtime_type'] = profile['runtime_type']
        result['backend'] = ready.get('hardware', {}).get('backend')
        result['created_at'] = datetime.now(timezone.utc).isoformat()
        settings = {'models': {'math_ocr': {'base_url': profile['endpoint'], 'model_id': profile['model_id'],
                    'request_timeout_seconds': profile.get('request_timeout_seconds', 300),
                    'generation': profile.get('generation', {'max_output_tokens': 1024})}}}
        client = LocalClient(settings, 'math_ocr')
        with tempfile.TemporaryDirectory(prefix='math-ocr-') as temporary:
            for index, (region, image) in enumerate(zip(regions, crops)):
                crop = Path(temporary) / f'{index}.png'
                crop.write_bytes(image)
                logger.info('math OCR inference start profile=%s region=%s', self.profile_id, index)
                payload = {
                    'model': profile['model_id'], 'stream': False,
                    'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': PROMPTS['math_ocr']['text']}, image_content(crop)]}],
                    **generation_payload(client.generation)}
                try:
                    raw = client.request(client.base + '/chat/completions', payload)
                except TimeoutError as exc:
                    raise MathOCRError('math_inference_timeout') from exc
                except Exception as exc:
                    raise MathOCRError('math_inference_failed') from exc
                raw_text, source_field, warnings = response_text(raw)
                latex = re.sub(r'^```(?:latex|tex)?\s*|\s*```$', '', raw_text.strip())
                # The question parser excludes multi-letter variables (TP, Precision).
                # Here permit only identifiers already visible in the source region.
                lexical = re.sub(r'\\[A-Za-z]+', '', latex)
                native = text[region['start']:region['end']]
                identifiers = set(re.findall(r'[A-Za-z]+', native)) | {'sin', 'cos', 'tan', 'log', 'ln', 'lim', 'exp'}
                if set(re.findall(r'[A-Za-z]+', lexical)) - identifiers:
                    raise ValueError('math_ocr_invalid_response')
                # Native digits may omit a visible numerator; never silently change
                # any digits that native extraction did retain.
                numeric = r'(?<![A-Za-z\d])(?:[-−]?\d+(?:\.\d+)?)'
                source_numbers = re.findall(numeric, native.replace('−', '-'))
                recognized_numbers = re.findall(numeric, latex.replace('−', '-'))
                remaining = iter(recognized_numbers)
                if any(not any(token == value for token in remaining) for value in source_numbers):
                    raise ValueError('math_ocr_numeric_mismatch')
                if source_numbers != recognized_numbers:
                    warnings.append('原文抽出と数値の数が異なります。PDF画像と照合してください。')
                if not latex or len(latex) > 12000 or '$' in latex:
                    raise ValueError('math_ocr_invalid_response')
                region.update(raw_latex=raw_text, raw_response=raw, source_field=source_field, latex=latex, original_text=text[region['start']:region['end']],
                              crop_image='data:image/png;base64,' + base64.b64encode(image).decode(),
                              warnings=warnings)
        rebuilt = text
        for region in reversed(regions):
            rebuilt = rebuilt[:region['start']] + '$$\n' + region['latex'] + '\n$$' + rebuilt[region['end']:]
        result.update(normalized_text=rebuilt, reconstructed_text=rebuilt, status='ambiguous', math_regions=regions,
                      warnings=['数式OCR結果を元PDFと照合してください。'] + list(dict.fromkeys(w for r in regions for w in r['warnings'])),
                      changes=[{'type': 'source_math_ocr', 'source': r['original_text']} for r in regions])
        logger.info('math OCR proposal built profile=%s regions=%s', self.profile_id, len(regions))
        return result
