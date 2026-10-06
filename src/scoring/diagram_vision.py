"""Optional RuntimeManager-managed Ricoh WHERE grouping, never transcription."""
import json
import logging

from .core import LocalClient, generation_payload, image_content
from .diagram_regions import union, validate_grouping
from .pdf_native import canonical_hash
from .vision_output import response_text

logger = logging.getLogger(__name__)


class RicohDiagramGrouping:
    def __init__(self, engine, manager, profile_id='ocr'):
        self.engine, self.manager, self.profile_id = engine, manager, profile_id
        self.observations = []

    def __call__(self, elements):
        ids = sorted(e['element_id'] for e in elements)
        observation = {'source_element_ids': ids, 'ricoh_finish_reason': None, 'ricoh_response_field': None}
        self.observations.append(observation)
        try:
            if self.manager is None:
                raise RuntimeError('diagram_ricoh_unavailable')
            page = next(p for p in self.engine.ir['pages'] if any(
                e['element_id'] in ids for e in p.get('vector_elements', []) + p['elements']))
            crop = self.engine.crop({'id': 'diagram-'+canonical_hash(ids)[:24],
                'page_index': page['page_index'], 'automatic_bbox': union(elements),
                'source_sha256': self.engine.ir['source']['sha256']})
            ready = self.manager.ensure_running(self.profile_id)
            if ready.get('state') != 'ready' or ready.get('ok') is False:
                raise RuntimeError('diagram_ricoh_unavailable')
            profile = ready['profile']
            client = LocalClient({'models': {'ocr': {'base_url': profile['endpoint'],
                'model_id': profile['model_id'], 'generation': profile.get('generation', {}),
                'request_timeout_seconds': profile.get('request_timeout_seconds', 180)}}}, 'ocr')
            schema = {'type': 'object', 'additionalProperties': False, 'required': ['groups'],
                'properties': {'groups': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                    'items': {'type': 'object', 'additionalProperties': False,
                        'required': ['element_ids', 'confidence'], 'properties': {
                            'element_ids': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                                'items': {'type': 'string', 'enum': ids}},
                            'confidence': {'type': 'number', 'minimum': .9, 'maximum': 1}}}}}}
            prompt = ('Group supplied source element IDs that visually belong to one diagram. '
                'Only WHERE grouping: do not describe, interpret, solve, transcribe, generate '
                'coordinates, graph semantics, math answers or corrections. Use known IDs only. '
                'Return only the complete JSON object with groups containing element_ids and confidence. '
                'Do not explain or reason.\n' + json.dumps(elements, ensure_ascii=False))
            raw = client.request(client.base+'/chat/completions', {'model': profile['model_id'],
                'stream': False, **generation_payload(client.generation), 'max_tokens': 2048, 'temperature': 0,
                'chat_template_kwargs': {'enable_thinking': False}, 'messages': [{'role': 'user',
                    'content': [{'type': 'text', 'text': prompt}, image_content(self.engine.store.path(crop['artifact_ref']))]}],
                'response_format': {'type': 'json_schema', 'json_schema': {'name': 'diagram_grouping',
                    'strict': True, 'schema': schema}}})
            text, field, flags = response_text(raw)
            observation['ricoh_response_field'] = field
            choice = raw.get('choices', [{}])[0] if isinstance(raw, dict) and raw.get('choices') else {}
            observation['ricoh_finish_reason'] = choice.get('finish_reason')
            if 'vision_output_truncated' in flags or choice.get('finish_reason') == 'length':
                raise ValueError('diagram_ricoh_output_truncated')
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise ValueError('diagram_ricoh_invalid_json') from exc
            validate_grouping(value, set(ids))
            logger.info('diagram grouping profile=%s elements=%s field=%s length=%s',
                self.profile_id, len(ids), field, len(text))
            return value
        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            code = 'diagram_ricoh_timeout' if 'timeout' in str(exc).lower() else 'diagram_ricoh_unavailable'
            raise RuntimeError(code) from exc
