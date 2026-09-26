"""Scoped, resumable batch orchestration. No grading entry point."""
import json
from pathlib import Path

from sqlalchemy import select

from . import student_visual
from .answer_anchors import question_anchors
from .db import models as m
from .grading_mapping import GradingInputAssembler
from .page_extraction import PageExtractionArtifactStore
from .pdf_native import canonical_hash, sha256_file
from .region_ownership import classify_regions, _overlap
from .student_answer import SelectedImageStudentAnswerReconstruction
from .student_identity import StudentIdentityService


VERSION = 'ricoh-anchored-v4'


def selected_reconstructions(session, sid, qid):
    return list(session.scalars(select(m.StudentAnswerReconstruction).join(
        m.StudentAnswerExtractionResult,
        m.StudentAnswerReconstruction.extraction_result_id == m.StudentAnswerExtractionResult.id
    ).join(m.StudentAnswerExtractionRun,
           m.StudentAnswerExtractionResult.run_id == m.StudentAnswerExtractionRun.id).where(
        m.StudentAnswerReconstruction.submission_id == sid,
        m.StudentAnswerReconstruction.question_id == qid,
        m.StudentAnswerExtractionRun.selected.is_(True))))


def annotate_answers(questions, anchors):
    by_ref = {a['question_ref']: a for a in anchors}
    # Ricoh sometimes associates a handwriting box with the neighbouring
    # printed label.  Reconcile that label using the authoritative geometry;
    # this is deliberately page-relative, never sample-coordinate based.
    def geometry_ref(region):
        bbox = region.get('bbox')
        candidates = []
        for anchor in anchors:
            s = anchor['search_bbox']
            if bbox and _overlap(bbox, s) > 0.5 and bbox[1] >= s[1] - 1e-6 and bbox[3] <= s[3] + 1e-6:
                candidates.append(anchor['question_ref'])
        return candidates[0] if len(candidates) == 1 else None
    result = []
    for item in questions:
        raw = []
        for region in item['answer_regions']:
            r = dict(region, question_ref=item['question_ref'])
            reassigned = geometry_ref(r)
            if reassigned and reassigned != item['question_ref']:
                r['question_ref'] = reassigned
                r['ownership_reason'] = 'question_ref_reconciled_from_authoritative_geometry'
            raw.append(r)
        ref = raw[0]['question_ref'] if raw else item['question_ref']
        a = by_ref[ref]
        regions = []
        for one in raw:
            owner_anchor = by_ref[one['question_ref']]
            regions.extend(classify_regions(
                [one], {}, native_regions={owner_anchor['question_ref']: owner_anchor['bbox']},
                answer_search_regions={owner_anchor['question_ref']: owner_anchor['search_bbox']}))
        seen = {}
        for r in regions:
            key = canonical_hash({k:r[k] for k in ('bbox','type','text')})
            if key in seen:
                seen[key]['duplicate_count'] += 1
                continue
            r['duplicate_count'] = 1
            # Only the target question's native printed blocks can make a
            # region MIXED.  Parent/adjacent question boxes often span the
            # same page band and would otherwise create false negatives.
            # A handwriting bbox can touch the baseline of a printed label.
            # Treat only substantial printed-area occupancy as MIXED; a small
            # edge intersection remains auditable but is not enough to discard
            # the answer region from the authoritative search band.
            overlaps = any(_overlap(r['bbox'], b) > 0.25 for b in a.get('printed_bboxes', []))
            if overlaps:
                r.update(ownership='MIXED', review_required=True,
                         ownership_reason='overlaps_native_printed_region')
            if r['type'] == 'visual':
                # A canvas location is not proof that a student drew on it.
                r.update(ownership='UNKNOWN', review_required=True,
                         ownership_reason='student_drawing_requires_source_review')
            if r['type'] != 'visual' and any(_overlap(r['bbox'], b)>0 for b in a['canvas_bboxes']):
                r.update(ownership='UNKNOWN', review_required=True,
                         ownership_reason='transcription_overlaps_drawing_canvas')
            seen[key] = r
        result.extend(seen.values())
    return result


class BatchAnswerProcessor:
    def __init__(self, session, stages, root, question_root, capability):
        self.s, self.stages = session, stages
        self.root, self.question_root = Path(root).resolve(), Path(question_root).resolve()
        self.capability = capability
        self.store = PageExtractionArtifactStore(self.root/'student-answer')

    def page(self, sub, source):
        sha = sha256_file(source)
        identity_service = StudentIdentityService(self.s, root=self.root)
        if identity_service.load(sub.id) is None and hasattr(self.stages, "ricoh_identity"):
            _, identity = self.stages.ricoh_identity(source)
            uncertainties = identity.get("uncertainties") or []
            confidence = 0.95 if not uncertainties else 0.5
            identity_service.extract(
                sub.id,
                student_number=identity.get("student_number", ""),
                student_name=identity.get("student_name", ""),
                confidence=confidence,
                review_required=bool(uncertainties),
                raw_text=identity.get("raw_text", ""),
                evidence=identity.get("source_bbox"),
                raw={"warnings": ["identity_uncertain"] if uncertainties else []},
            )
        anchors = question_anchors(self.s, sub.test_id, self.question_root)
        version = VERSION + '-' + canonical_hash(anchors)[:16]
        existing = self.store.load(sub.id, sha, version)
        if existing:
            return existing
        raw, value = self.stages.ricoh_page_answers(source, anchors)
        regions = annotate_answers(value['questions'], anchors)
        # Visual-primary questions must not depend on Ricoh returning text.
        # When the authoritative Question layout exposes a figure canvas and
        # the page pass omitted a visual region, retain a canvas-scoped visual
        # evidence region for review/asset registration.  This is derived only
        # from Question geometry; it never turns OCR prose into a drawing.
        by_ref = {a['question_ref']: a for a in anchors}
        existing_refs = {r['question_ref'] for r in regions if r.get('type') == 'visual'}
        for ref, anchor in by_ref.items():
            if not anchor.get('canvas_bboxes') or ref in existing_refs:
                continue
            regions.append({
                'question_ref': ref, 'type': 'visual', 'bbox': anchor['canvas_bboxes'][0],
                'text': '', 'coordinate_space': 'normalized',
                'ownership': 'UNKNOWN', 'review_required': True,
                'ownership_reason': 'question_visual_canvas_fallback_without_ocr_text',
                'geometry_source': anchor.get('geometry_source'),
                'source_coordinate_space': 'normalized',
            })
        artifact = self.store.save(sub.id, sha, regions, response_sha=canonical_hash(raw),
            model_version=self.stages.config['models']['ocr']['model_id'],
            prompt_version=VERSION, version=version)
        folder = self.store._path(sub.id, sha, version).parent
        evidence = folder / (version + '-evidence.json')
        if not evidence.exists():
            evidence.write_text(json.dumps({'raw':raw,'normalized':value,'anchors':anchors},ensure_ascii=False))
            evidence.chmod(0o600)
        return artifact

    def process(self, sid, qid):
        sub = self.s.get(m.StudentSubmission, sid)
        q = self.s.get(m.TestQuestion, qid)
        if not sub or not q or q.test_id != sub.test_id or not q.is_gradable:
            raise ValueError('QUESTION_MAPPING_NOT_FOUND')
        if selected_reconstructions(self.s, sid, qid):
            return {'submission':sid,'question_id':qid,'final':'SKIPPED_SELECTED'}
        source = Path(self.s.get(m.TestMaterial, sub.material_id).storage_ref).resolve()
        before = sha256_file(source)
        artifact = self.page(sub, source)
        regions = [r for r in artifact['regions'] if r['question_ref'] == qid]
        row = {'submission':sid,'question_id':qid,'extraction':'COMPLETE',
               'page_artifact_id':artifact['artifact_id'],'uni':0,'visual_assets':[],
               'reconstruction':'NOT_RUN','preview':'NOT_RUN','final':'BLOCKED'}
        visual = [r for r in regions if r['type']=='visual']
        ordinary = [r for r in regions if r['type']!='visual']
        requires_text = bool(ordinary)
        for region in visual:
            asset = student_visual.StudentVisualAssetService(self.s,self.root).register(
                sid,qid,region['bbox'],source_sha=before,verified=False,
                provenance={'page_artifact_id':artifact['artifact_id'],
                            'requires_reconstruction':requires_text,'ownership':region['ownership']})
            row['visual_assets'].append(asset)
        unsafe = [r for r in ordinary if r['ownership'] in {'MIXED','UNKNOWN'}]
        accepted = [r for r in ordinary if r['ownership']=='STUDENT_HANDWRITING']
        if unsafe:
            row['final']='REVIEW_REQUIRED'
            row['blockers']=['REGION_OWNERSHIP_REVIEW_REQUIRED']
        elif accepted:
            norm={'coordinate_space':'normalized','text_blocks':[], 'formula_regions':[],
                  'visual_regions':[], 'reading_order':[], 'warnings':[]}
            for i,r in enumerate(accepted):
                if r['type']=='formula':
                    norm['formula_regions'].append({'region_id':f'formula_{i}', 'question_id':qid,
                        'page_id':f'submission-source-{before[:16]}','bbox':r['bbox'],
                        'coordinate_space':'normalized','transcription':r['text']})
                else:
                    norm['text_blocks'].append({'text':r['text'],'bbox':r['bbox']})
            def uni(crop, region):
                row['uni'] += 1
                return self.stages.unimumer(crop,region)
            def reconstruct(payload):
                self.stages.image_resolver = lambda p: [(p['source_answer']['pages'][0]['page_id'],source)]
                return self.stages.ornith_reconstruction(payload)
            run,out=SelectedImageStudentAnswerReconstruction(self.s,artifact_root=self.root,
                question_root=self.question_root).run(sid,qid,
                ricoh=lambda image,question: ({'page_artifact_id':artifact['artifact_id']},norm),
                unimumer=uni,ornith_reconstruction=reconstruct,
                config={'pipeline':VERSION,'question_id':qid,'protect_selected':True})
            row.update(reconstruction=out['status'],run_id=run.id,answer=out['answer_text'])
            if out['status']=='REVIEW_REQUIRED':
                row['final']='REVIEW_REQUIRED'
        try:
            p=GradingInputAssembler(self.s,sub.test_id,root=self.question_root,
                allowed_roots=[self.root],answer_root=self.root,
                reference_root=self.root/'h3c1-model-answer',visual_capability=self.capability
            ).execution_preview(sid,qid)
            row['preview']=p['execution_state']
            row['bundle_sha256']=(p.get('bundle') or {}).get('bundle_sha256')
            row['preview_blockers']=p.get('blockers',[])
            if p['execution_state']=='READY':
                row['final']='READY_FOR_GRADING'
            elif visual:
                row['final']='REVIEW_REQUIRED'
        except ValueError as exc:
            row['preview']='BLOCKED'
            row['preview_blockers']=[str(exc)]
        if not regions:
            row['blockers']=['NO_ANSWER_DETECTED']
        if sha256_file(source)!=before:
            raise ValueError('SOURCE_IMAGE_MUTATED')
        return row
