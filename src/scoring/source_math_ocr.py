"""Bounded source-PDF formula transcription; proposals never mutate drafts."""
from __future__ import annotations

import base64
import logging
import json
import os
from hashlib import sha256
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz

from .adapters.question_vision import PROMPTS
from .core import LocalClient, generation_payload, image_content
from .vision_output import response_text, unwrap_math_output
from .math_region_grouping import source_regions, validate_groups, region_from_atoms

logger = logging.getLogger(__name__)


class MathOCRError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)




class SourceMathOCR:
    def __init__(self, manager, profile_id='math_ocr'):
        self.manager, self.profile_id = manager, profile_id

    def runtime_client(self, role, profile_id):
        logger.info('math runtime ensure role=%s profile=%s', role, profile_id)
        try:
            ready = self.manager.ensure_running(profile_id)
        except Exception as exc:
            code = 'math_runtime_start_timeout' if 'timeout' in str(exc).lower() else 'math_runtime_unavailable'
            raise MathOCRError(code) from exc
        if ready.get('ok') is False or ready.get('state') != 'ready':
            raise MathOCRError('math_runtime_unavailable')
        profile = ready['profile']
        logger.info('math runtime ready role=%s profile=%s', role, profile_id)
        client = LocalClient({'models': {role: {
            'base_url': profile['endpoint'], 'model_id': profile['model_id'],
            'request_timeout_seconds': profile.get('request_timeout_seconds', 300),
            'generation': profile.get('generation', {'max_output_tokens': 2048})}}}, role)
        return client, ready

    @staticmethod
    def render(document, region):
        page_index, box = region['page_index'], region['bbox']
        if (type(page_index) is not int or not 0 <= page_index < len(document) or len(box) != 4
                or not all(type(v) in (int, float) and math.isfinite(v) for v in box)):
            raise ValueError('math_crop_invalid')
        page = document[page_index]
        rect = fitz.Rect(box)
        if rect.is_empty or not page.rect.contains(rect):
            raise ValueError('math_crop_invalid')
        clip = (rect + (-6, -6, 6, 6)) & page.rect
        if clip.get_area() > page.rect.get_area() * .35 or clip.get_area() * 4 > 4_000_000:
            raise ValueError('math_crop_too_large')
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip)
        image = pixmap.tobytes('png')
        region.update(crop_bbox=list(clip), crop_sha256=sha256(image).hexdigest(),
                      crop_width=pixmap.width, crop_height=pixmap.height,
                      crop_image='data:image/png;base64,' + base64.b64encode(image).decode())
        return image

    def repair_groups(self, document, regions):
        pending = [r for r in regions if r.get('grouping_ambiguous')]
        if not pending:
            return regions
        # Separate bounded neighborhoods/pages; never ask vision about a whole page.
        from .math_region_grouping import connected
        remaining, neighborhoods = pending[:], []
        while remaining:
            cluster = [remaining.pop(0)]
            while True:
                neighbor = next((r for r in remaining if any(connected(a, b, loose=True)
                    for member in cluster for a in member['source_spans'] for b in r['source_spans'])), None)
                if neighbor is None:
                    break
                cluster.append(neighbor)
                remaining.remove(neighbor)
            neighborhoods.append(cluster)
        output = [r for r in regions if r not in pending]
        for cluster in neighborhoods:
            atoms = [a for r in cluster for a in r['source_spans']]
            diagnostic = region_from_atoms(atoms, 'geometry_ambiguous')
            image = self.render(document, diagnostic)
            diagnostic.update(ricoh_used=True, validation='rejected', rejection_code='math_geometry_ambiguous')
            try:
                client, ready = self.runtime_client('ocr', os.getenv('LLM_GRADER_MATH_GROUPING_PROFILE', 'ocr'))
                diagnostic['ricoh_profile'] = ready['profile']['runtime_id'] if 'runtime_id' in ready['profile'] else 'ocr'
                prompt = ('Identify only which supplied source segment IDs visually belong to one mathematical expression. '
                          'Do not solve, correct, transcribe, output LaTeX or invent coordinates or content. '
                          'Return JSON only: {"groups":[{"segment_ids":["id"],"confidence":0.95}]}. '
                          'Each supplied ID must occur exactly once. Keep independent expressions separate.\n'
                          + json.dumps({'segments': atoms}, ensure_ascii=False))
                with tempfile.TemporaryDirectory(prefix='math-group-') as temporary:
                    crop = Path(temporary)/'group.png'
                    crop.write_bytes(image)
                    raw = client.request(client.base+'/chat/completions', {
                        'model': ready['profile']['model_id'], 'stream': False,
                        'chat_template_kwargs': {'enable_thinking': False},
                        'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, image_content(crop)]}],
                        **generation_payload(client.generation)})
                raw_text, field, _ = response_text(raw)
                diagnostic.update(ricoh_response_field=field, ricoh_raw_response=raw)
                value = json.loads(raw_text)
                diagnostic["ricoh_result"] = value
                repaired = validate_groups(value, atoms)
                same_membership = sorted(sorted(r['segment_ids']) for r in repaired) == sorted(sorted(r['segment_ids']) for r in cluster)
                for region in repaired:
                    region.update(ricoh_result=value, ricoh_response_field=field, ricoh_used=True,
                                  grouping_method="geometry_ricoh_validation" if same_membership else "ricoh_assisted_repair")
                output.extend(repaired)
            except MathOCRError:
                diagnostic['rejection_code'] = 'math_ricoh_unavailable'
                output.append(diagnostic)
            except Exception:
                diagnostic['rejection_code'] = 'math_ricoh_grouping_rejected'
                output.append(diagnostic)
        return sorted(output, key=lambda r: r['start'])

    def propose(self, path: Path, segments, text):
        regions = source_regions(segments, text)
        result = {'original_text': text, 'normalized_text': text, 'reconstructed_text': text,
                  'status': 'no_change', 'confidence': None, 'warnings': [], 'changes': [],
                  'profile': self.profile_id, 'model': '', 'math_regions': [], 'reason_code': 'math_no_region',
                  'grouping_summary': {'native_segment_count': len(segments),
                      'aligned_math_segment_count': sum(len(r['segment_ids']) for r in regions),
                      'geometry_region_count': len(regions), 'final_region_count': len(regions), 'ricoh_used': False}}
        if not regions:
            return result
        if len(regions) > 8:
            raise ValueError('math_region_limit')
        with fitz.open(path) as document:
            regions = self.repair_groups(document, regions)
            if len(regions) > 8:
                raise ValueError("math_region_limit")
            for region in regions:
                self.render(document, region)
        result['math_regions'] = regions
        result['grouping_summary'].update(final_region_count=len(regions), ricoh_used=any(r['ricoh_used'] for r in regions))
        if any(r.get('rejection_code') for r in regions):
            result.update(status='rejected', reason_code=next(r['rejection_code'] for r in regions if r.get('rejection_code')),
                          warnings=['数式領域の所属を確認できません。cropと位置情報を確認してください。'])
            return result
        logger.info('math OCR runtime ensure start profile=%s regions=%s', self.profile_id, len(regions))
        try:
            client, ready = self.runtime_client('math_ocr', self.profile_id)
        except MathOCRError as exc:
            for region in regions:
                region.update(validation='rejected', rejection_code=exc.code, inference_started=False, inference_completed=False)
            result.update(status='rejected', reason_code=exc.code, warnings=['数式OCRを起動できませんでした。元の本文は保持されています。'])
            return result
        profile = ready['profile']
        result.update(model=profile['model_id'], runtime_type=profile['runtime_type'],
                      backend=ready.get('hardware', {}).get('backend'), created_at=datetime.now(timezone.utc).isoformat())
        with tempfile.TemporaryDirectory(prefix='math-ocr-') as temporary:
            for index, region in enumerate(regions):
                crop = Path(temporary)/f'{index}.png'
                crop.write_bytes(base64.b64decode(region['crop_image'].split(',', 1)[1]))
                region.update(inference_started=True, inference_completed=False, validation='pending', warnings=[], normalized_candidate='')
                logger.info('math OCR inference start profile=%s region=%s segments=%s method=%s dimensions=%sx%s crop_sha=%s',
                            self.profile_id, index, len(region['segment_ids']), region['grouping_method'],
                            region['crop_width'], region['crop_height'], region['crop_sha256'])
                payload = {'model': profile['model_id'], 'stream': False,
                    'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': PROMPTS['math_ocr']['text']}, image_content(crop)]}],
                    **generation_payload(client.generation)}
                try:
                    try:
                        raw = client.request(client.base+'/chat/completions', payload)
                    except TimeoutError as exc:
                        raise MathOCRError('math_inference_timeout') from exc
                    except ValueError as exc:
                        raise MathOCRError('math_response_unsupported') from exc
                    except Exception as exc:
                        raise MathOCRError('math_inference_failed') from exc
                    region.update(inference_completed=True, raw_response=raw)
                    raw_text, field, warnings = response_text(raw)
                    region.update(raw_latex=raw_text, source_field=field, warnings=warnings, raw_text_sha256=sha256(raw_text.encode()).hexdigest())
                    if not raw_text.strip():
                        choices = raw.get('choices', []) if isinstance(raw, dict) else []
                        message = choices[0].get('message', {}) if choices and isinstance(choices[0], dict) else {}
                        has_message = isinstance(message, dict) and any(isinstance(message.get(k), str) for k in ('content', 'final', 'answer', 'reasoning_content', 'reasoning'))
                        raise ValueError('math_ocr_empty_response' if has_message else 'math_response_unsupported')
                    latex = unwrap_math_output(raw_text)
                    region['normalized_candidate'] = latex
                    native = region['original_text']
                    lexical = re.sub(r'\\(?:begin|end)\{(?:aligned|align\*?|gathered|gather\*?|matrix|pmatrix|bmatrix|cases|array)\}(?:\{[lcr| ]+\})?', '', latex)
                    lexical = re.sub(r'\\[A-Za-z]+', '', lexical)
                    identifiers = set(re.findall(r'[^\W\d_]+', native)) | {'sin', 'cos', 'tan', 'log', 'ln', 'lim', 'exp'}
                    if set(re.findall(r'[^\W\d_]+', lexical)) - identifiers:
                        raise ValueError('math_identifier_invalid')
                    numeric = r'(?<![A-Za-z\d])(?:[-−]?\d+(?:\.\d+)?)'
                    source_numbers = re.findall(numeric, native.replace('−', '-'))
                    recognized_numbers = re.findall(numeric, latex.replace('−', '-'))
                    remaining = iter(recognized_numbers)
                    if any(not any(token == value for token in remaining) for value in source_numbers):
                        raise ValueError('math_ocr_numeric_mismatch')
                    if source_numbers != recognized_numbers:
                        warnings.append('原文抽出と数値の数が異なります。PDF画像と照合してください。')
                    if not latex or len(latex) > 12000 or not re.search(r'[=+^_−×÷]|\\[A-Za-z]+', latex):
                        raise ValueError('math_formula_not_found')
                    region.update(latex=latex, validation='accepted')
                except (ValueError, MathOCRError) as exc:
                    region.update(validation='rejected', rejection_code=exc.code if isinstance(exc, MathOCRError) else str(exc))
                logger.info('math OCR result region=%s field=%s raw_length=%s candidate_length=%s validation=%s reason=%s',
                            index, region.get('source_field'), len(region.get('raw_latex', '')),
                            len(region.get('normalized_candidate', '')), region['validation'], region.get('rejection_code'))
        rejected = [r for r in regions if r['validation'] == 'rejected']
        if rejected:
            result.update(status='rejected', reason_code=rejected[0]['rejection_code'],
                          warnings=['有効な数式を取得できませんでした。cropとOCR診断を確認してください。元の本文は保持されています。'])
            return result
        # Each visual region has explicit source ranges; insert once, remove only
        # mapped fragments. Non-math prose/line breaks are never removed by bbox.
        replacements = []
        for region in regions:
            spans = sorted(region['source_spans'], key=lambda a: a['start'])
            for index, span in enumerate(spans):
                replacements.append((span['start'], span['end'], '$$\n'+region['latex']+'\n$$' if index == 0 else ''))
        rebuilt = text
        for start, end, value in sorted(replacements, reverse=True):
            rebuilt = rebuilt[:start]+value+rebuilt[end:]
        result.update(normalized_text=rebuilt, reconstructed_text=rebuilt, status='ambiguous', reason_code=None,
                      warnings=['数式OCR結果を元PDFと照合してください。'] + list(dict.fromkeys(w for r in regions for w in r['warnings'])),
                      changes=[{'type': 'source_math_ocr', 'source': r['original_text']} for r in regions])
        logger.info('math OCR proposal built profile=%s regions=%s', self.profile_id, len(regions))
        return result
