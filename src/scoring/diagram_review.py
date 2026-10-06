"""Validated diagram review records; discovery is distinct from explicit Save."""
from copy import deepcopy
import json
import re

from .pdf_native import canonical_hash, sha256_file
from .diagram_regions import write_diagram_json

FIELDS = ('id', 'domain', 'target_key', 'material_id', 'source_sha256', 'source_ir_sha256',
    'page_index', 'automatic_bbox', 'final_bbox', 'crop_bbox', 'source_element_ids',
    'grouping_method', 'confidence', 'ricoh_used', 'teacher_adjusted', 'crop_width',
    'crop_height', 'crop_sha256', 'artifact_ref', 'context_sha256', 'legacy_region_id',
    'revision', 'state', 'status', 'reason_code', 'ricoh_finish_reason', 'ricoh_response_field',
    'page_width', 'page_height', 'page_rotation', 'legacy_region_ids',
    'scope', 'source_question_id', 'source_question_path', 'assigned_question_id')


class DiagramReview:
    def __init__(self, engine, candidates):
        self.engine = engine
        self.context = canonical_hash({'source': engine.ir['source']['sha256'],
            'ownership': getattr(engine, 'ownership_key', {}),
            'candidates': [{k: c[k] for k in ('id', 'source_element_ids', 'bbox')} for c in candidates]})
        self.ref = f'diagrams/reviews/{self.context}.json'
        self.candidates = candidates
        path = engine.store.path(self.ref)
        if path.exists():
            value = json.loads(path.read_text())
            if value.get('context_sha256') != self.context:
                raise ValueError('diagram_cache_invalid')
            cached = value.get('candidates', [])
            from .diagram_regions import union
            for c in cached:
                page = next((p for p in engine.ir['pages'] if p['page_index'] == c.get('page_index')), None)
                if page is None:
                    raise ValueError('diagram_cache_invalid')
                known = {e['element_id']: e for e in page.get('elements', []) + page.get('vector_elements', [])}
                ids = c.get('source_element_ids', [])
                allowed = set(engine.discovery_args['ownership'].get(c['page_index'], []))
                if (not ids or len(set(ids)) != len(ids) or not set(ids) <= allowed or not set(ids) <= set(known)
                        or c.get('domain') != engine.discovery_args['domain']
                        or c.get('target_key') != engine.discovery_args['target_key']
                        or c.get('source_sha256') != engine.ir['source']['sha256']):
                    raise ValueError('diagram_cache_invalid')
                identity = {k: c[k] for k in ('domain', 'target_key', 'source_sha256', 'page_index', 'source_element_ids', 'bbox')}
                if (c['bbox'] != union([known[i] for i in ids])
                        or c['automatic_bbox'] != c['bbox']
                        or c['id'] != 'diagram-' + canonical_hash(identity)[:24]):
                    raise ValueError('diagram_cache_invalid')
            self.candidates = cached
        else:
            self._cache()

    def _cache(self):
        write_diagram_json(self.engine.store, self.ref, {'context_sha256': self.context, 'candidates': self.candidates})

    def discover(self, manager):
        from .diagram_vision import RicohDiagramGrouping
        if any(c.get('status') == 'unresolved' for c in self.candidates):
            grouping = RicohDiagramGrouping(self.engine, manager)
            self.candidates = self.engine.candidates(**self.engine.discovery_args,
                grouping=grouping)
            for c in self.candidates:
                for observation in grouping.observations:
                    if set(c['source_element_ids']) & set(observation['source_element_ids']):
                        c.update({k: observation[k] for k in ('ricoh_finish_reason', 'ricoh_response_field')})
            self._cache()

    def candidate(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'diagram-[0-9a-f]{24}', identifier):
            raise ValueError('diagram_candidate_not_found')
        c = next((c for c in self.candidates if c['id'] == identifier), None)
        if c is None:
            raise ValueError('diagram_candidate_not_found')
        return c

    def record(self, identifier, *, state='candidate', final_bbox=None, revision=1):
        c = self.candidate(identifier)
        if not isinstance(state, str) or state not in {'candidate', 'accepted', 'excluded'}:
            raise ValueError('diagram_invalid_decision')
        if c.get('status') == 'unresolved' and state == 'accepted':
            raise ValueError(c.get('reason_code', 'diagram_geometry_ambiguous'))
        value = self.engine.crop(c, final_bbox=final_bbox)
        value.update(state=state, context_sha256=self.context, revision=revision)
        from .vision_policy import page_space
        page = next(p for p in self.engine.ir['pages'] if p['page_index'] == c['page_index'])
        bounds = page_space(page).cropbox
        value.update(page_width=bounds[2], page_height=bounds[3], page_rotation=page['rotation'])
        legacy = [r['region_id'] for r in getattr(self.engine, 'legacy_figures', [])
            if r['page_index'] == c['page_index'] and set(r['source_element_ids']) <= set(c['source_element_ids'])]
        if legacy:
            value.update(legacy_region_id=legacy[0], legacy_region_ids=legacy)
        return {k: deepcopy(value[k]) for k in FIELDS if k in value}

    def records(self, saved=(), *, revision=1):
        by_id = {r['id']: r for r in saved}
        result = []
        for c in self.candidates:
            old = by_id.get(c['id'], {})
            stale = bool(old and (old.get('context_sha256') != self.context or any(
                key in old and old[key] != c[key] for key in (
                    'source_sha256', 'material_id', 'domain', 'target_key', 'page_index',
                    'automatic_bbox', 'source_element_ids'))))
            try:
                r = self.record(c['id'], state=old.get('state', 'candidate') if not stale else 'candidate',
                    final_bbox=old.get('final_bbox') if not stale else None, revision=revision)
            except ValueError as exc:
                r = {k: deepcopy(c[k]) for k in FIELDS if k in c}
                r.update(state='candidate', status='unresolved', reason_code=str(exc), context_sha256=self.context)
            if stale:
                r.update(state='candidate', status='unresolved', reason_code='diagram_source_stale')
            result.append(r)
        for identifier, old in by_id.items():
            if not any(r['id'] == identifier for r in result):
                stale = {k: v for k, v in old.items() if k not in {'crop_sha256', 'artifact_ref'}}
                result.append({**stale, 'state': 'candidate', 'status': 'unresolved', 'reason_code': 'diagram_source_stale'})
        return result

    def validate(self, records, revision):
        if not isinstance(records, list) or len(records) > 16 or len(json.dumps(records)) > 100000:
            raise ValueError('diagram_invalid_decision')
        result, seen = [], set()
        for r in records:
            if (not isinstance(r, dict) or not isinstance(r.get('id'), str) or set(r)-set(FIELDS) or r.get('id') in seen
                    or r.get('context_sha256') != self.context):
                raise ValueError('diagram_source_stale')
            candidate = self.candidate(r['id'])
            # A canonical context alone must not legitimize stale source identity
            # carried by a saved decision. Paths/crop bytes are still re-derived.
            for key in ('source_sha256', 'material_id', 'domain', 'target_key', 'page_index',
                        'automatic_bbox', 'source_element_ids'):
                if key in r and r[key] != candidate[key]:
                    raise ValueError('diagram_source_stale')
            seen.add(r['id'])
            result.append(self.record(r['id'], state=r.get('state', 'candidate'),
                                      final_bbox=r.get('final_bbox'), revision=revision))
        return result

    def path(self, record):
        # Never use a caller-supplied path; derive it again from verified geometry.
        value = self.record(record['id'], final_bbox=record.get('final_bbox'))
        path = self.engine.store.path(value['artifact_ref'])
        if sha256_file(path) != value['crop_sha256']:
            raise ValueError('diagram_artifact_integrity_error')
        return path

    def preview(self, record):
        write_diagram_json(self.engine.store, f'diagrams/previews/{self.context}/{record["id"]}/{record["crop_sha256"]}.json', record)
        return record

    def preview_path(self, identifier, crop_sha=None):
        if crop_sha is None:
            return self.path(self.record(identifier))
        if not re.fullmatch(r'[0-9a-f]{64}', crop_sha):
            raise ValueError('diagram_candidate_not_found')
        path = self.engine.store.path(f'diagrams/previews/{self.context}/{identifier}/{crop_sha}.json')
        if not path.exists():
            raise ValueError('diagram_candidate_not_found')
        record = json.loads(path.read_text())
        if record['id'] != identifier or record['context_sha256'] != self.context:
            raise ValueError('diagram_source_stale')
        return self.path(record)


def question_diagram_review(service, review_id, node_key, revision, *, snapshot_override=None):
    from .diagram_sources import question_diagram_candidates
    engine, candidates = question_diagram_candidates(service, review_id, node_key, revision,
                                                     snapshot_override=snapshot_override)
    return DiagramReview(engine, candidates)
