import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import select, func
from scoring.api import create_app
from scoring.db import create_session_factory, init_database
from scoring.db.models import QuestionImportExtraction, QuestionImportDraft, QuestionImportDraftNode, TestQuestion as QuestionModel
from scoring.domain import DomainService
from scoring.pdf_native import PyMuPdfNativeExtractor, canonical_hash, sha256_file
from scoring.question_structure import QuestionStructureParser
from scoring.coordinate import PageCoordinateSpace, expand_bbox, page_pixel_size, pdf_bbox_to_pixel
from tests.test_pdf_native import _endpoint, _Request
from tests import test_pdf_native


def text(eid, value, x=50, y=100, math=False, size=12):
    return {"element_id": eid, "type": "text", "native_text": value, "normalized_text": value,
            "bbox": [x, y, x+max(10, len(value)*6), y+size], "reading_order": int(eid[1:]),
            "native": {"font": "CambriaMath" if math else "Japanese", "font_size": size},
            "quality_signals": {"math_like_candidate": math}, "review_flags": []}


def document(elements, pages=None):
    return {"schema_version": "question-document-ir.v1", "source": {}, "parser": {},
            "pages": pages or [{"page_index": 0, "width": 600, "height": 800, "elements": elements, "vector_summary": {"count": 0}}]}


class StructureTests(unittest.TestCase):
    def build(self, elements):
        return QuestionStructureParser().build(document(elements))[1]

    def test_geometric_order_preserves_native_and_determinism(self):
        ir = document([text('e0','x=1',y=160,math=True), text('e1','Header',y=30), text('e2','問題1 body',y=100)])
        before = deepcopy(ir)
        a, draft = QuestionStructureParser().build(ir)
        b, again = QuestionStructureParser().build(ir)
        self.assertEqual(ir, before)
        self.assertEqual(a['lines'][0]['native_orders'], [1])
        self.assertEqual(canonical_hash(a), canonical_hash(b))
        self.assertEqual(canonical_hash(draft), canonical_hash(again))
        self.assertEqual(draft['formula_regions'][0]['assigned_question_key'], 'q1')

    def test_each_child_hierarchy_total_and_provenance(self):
        values = ['問題１ body（各20点）','（１） first','（２） second','問題２ body（30点）',
                  '問題３ body（各10点）','（１） a','（２） b','（３） c']
        d = self.build([text(f'e{i}', v, y=100+60*i) for i,v in enumerate(values)])
        self.assertEqual(len(d['nodes']), 8)
        self.assertEqual(d['total_points_candidate'], 100)
        self.assertEqual([n['score']['effective_points_candidate'] for n in d['nodes'] if n['leaf_candidate']], [20,20,30,10,10,10])
        self.assertEqual(d['nodes'][1]['parent_key'], 'q1')
        self.assertEqual(d['nodes'][1]['source_regions'][0]['source_element_ids'], ['e1'])

    def test_no_score_is_unset(self):
        d = self.build([text('e0','問題1 body')])
        self.assertIsNone(d['total_points_candidate'])
        self.assertEqual(d['nodes'][0]['score']['semantics'], 'unset')

    def test_each_child_without_children_is_ambiguous(self):
        d = self.build([text('e0','問題1 body（各20点）')])
        self.assertEqual(d['nodes'][0]['score']['semantics'], 'ambiguous')
        self.assertIsNone(d['total_points_candidate'])

    def test_inline_labels_do_not_create_children(self):
        d = self.build([text('e0','問題1 次の（1）式を、（2）式へ（各20点）')])
        self.assertEqual(len(d['nodes']), 1)
        self.assertIn('inline_subquestion_label', d['review_flags'])
        self.assertIsNone(d['total_points_candidate'])

    def test_direct_parent_does_not_distribute_score(self):
        d = self.build([text('e0','問題1 body（30点）'),text('e1','(1) a',y=150),text('e2','(2) b',y=200)])
        self.assertIn('direct_score_with_children',d['review_flags'])
        self.assertIsNone(d['total_points_candidate'])

    def test_formula_fragments_and_ordinary_prose(self):
        d = self.build([text('e0','問題1 body（30点）'),text('e1','x',y=140,math=True),
                        text('e2','3',x=62,y=136,math=True,size=8),text('e3','= -8',x=70,y=140,math=True)])
        self.assertEqual(len(d['formula_regions']),1)
        self.assertEqual(len(d['formula_regions'][0]['text_fragments']),3)
        self.assertNotIn('latex',d['formula_regions'][0])
        self.assertEqual(d['nodes'][0]['score']['points'],30)

    def test_figure_components_and_vector_only(self):
        image = {"element_id":"im1", "type":"image", "bbox":[50,200,350,350],"sha256":"hash","artifact_ref":"images/a.png"}
        tiny = {**image,"element_id":"im2","bbox":[60,220,70,230]}
        ir = document([text('e0','問題1 body'),image,tiny])
        ir['pages'][0]['vector_summary']['count'] = 24
        _,d = QuestionStructureParser().build(ir)
        self.assertEqual(len(d['figure_regions']),1)
        self.assertEqual(d['figure_regions'][0]['assigned_question_key'],'q1')
        ir['pages'][0]['elements'] = [text('e0','問題1 body')]
        _,d = QuestionStructureParser().build(ir)
        self.assertEqual(d['figure_regions'],[])
        self.assertIn('unresolved_vector_evidence',d['review_flags'])

    def test_multipage_continuation_and_footer(self):
        pages = [document([text('e0','問題1 body')])['pages'][0],
                 {**document([text('e1','continued',y=100),text('e2','footer',y=780)])['pages'][0], 'page_index':1}]
        _,d = QuestionStructureParser().build(document([],pages))
        self.assertEqual(len(d['nodes']),1)
        self.assertIn('continued',d['nodes'][0]['body_text'])
        self.assertNotIn('footer',d['nodes'][0]['body_text'])
        self.assertEqual(d['nodes'][0]['source_regions'][-1]['page_index'],1)

    def test_duplicate_and_conflicting_scores_require_review(self):
        d = self.build([text('e0','問題1 a (20点) (30点)'),text('e1','問題1 b',y=200)])
        self.assertIn('duplicate_question_label',d['review_flags'])
        self.assertEqual(d['nodes'][0]['score']['semantics'],'ambiguous')
        self.assertEqual(len({n['stable_key'] for n in d['nodes']}),2)


class DraftApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine,self.sf = create_session_factory(f"sqlite:///{self.root / 'db'}")
        init_database(self.engine)
        with self.sf() as s:
            service = DomainService(s)
            u=service.user(display_name='Draft test')
            c=service.course(u.id,name='Draft test')
            o=service.offering(c.id,academic_year=2026,term='fall')
            t=service.test(o.id,name='Draft test',total_points=100)
            s.commit()
            self.tid=t.id
        self.app=create_app(self.sf,question_import_root=self.root/'artifacts')
        source=test_pdf_native.PdfNativeTests().make_pdf(self.root)
        with self.sf() as s:
            self.extraction=asyncio.run(_endpoint(self.app,'/api/v1/tests/{test_id}/question-materials')(self.tid,_Request(source.read_bytes()),s))
        self.post=_endpoint(self.app,'/api/v1/question-imports/{extraction_id}/draft')

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_generate_idempotency_get_and_no_question_mutation(self):
        with self.sf() as s:
            a=self.post(self.extraction['id'],s)
            b=self.post(self.extraction['id'],s)
            self.assertEqual(a['id'],b['id'])
            self.assertEqual(a['state'],'completed')
            self.assertEqual(s.scalar(select(func.count()).select_from(QuestionModel)),0)
            self.assertEqual(s.scalar(select(func.count()).select_from(QuestionImportDraft)),1)
            for path,identifier in [('/api/v1/question-imports/{extraction_id}/draft',self.extraction['id']),('/api/v1/question-import-drafts/{draft_id}',a['id'])]:
                value=_endpoint(self.app,path)(identifier,s)
                self.assertEqual(value['id'],a['id'])
                self.assertNotIn(str(self.root),json.dumps(value,default=str))
            self.assertEqual(s.scalar(select(func.count()).select_from(QuestionImportDraftNode)),len(a['nodes']))

    def test_unfinished_and_missing(self):
        with self.sf() as s:
            with self.assertRaises(HTTPException) as caught:
                self.post('missing',s)
            self.assertEqual(caught.exception.status_code,404)
            s.get(QuestionImportExtraction,self.extraction['id']).state='extracting'
            s.commit()
            with self.assertRaises(HTTPException) as caught:
                self.post(self.extraction['id'],s)
            self.assertEqual(caught.exception.status_code,409)

    def test_source_hash_mismatch_and_symlink_escape(self):
        path=self.root/'artifacts'/self.extraction['id']/'native'/'document-ir.json'
        path.write_text('{}')
        with self.sf() as s:
            with self.assertRaises(HTTPException) as caught:
                self.post(self.extraction['id'],s)
            self.assertEqual(caught.exception.status_code,409)
            self.assertEqual(s.scalar(select(func.count()).select_from(QuestionImportDraft)),0)
        path.unlink()
        path.symlink_to(self.root/'db')
        with self.sf() as s:
            with self.assertRaises(HTTPException):
                self.post(self.extraction['id'],s)


class RealStructureTests(unittest.TestCase):
    def test_three_native_pdfs(self):
        sources=[Path('testData/SampleQ')/f'sampleQ{i}.pdf' for i in (1,2,3)]
        if not all(p.exists() for p in sources):
            self.skipTest('local real PDF fixtures unavailable')
        with tempfile.TemporaryDirectory() as folder:
            for i,p in enumerate(sources,1):
                self.assertEqual(p.read_bytes()[:5],b'%PDF-')
                ir=PyMuPdfNativeExtractor().extract(p,source_sha256=sha256_file(p),material_id=f'real-{i}',output_dir=Path(folder)/str(i)).as_dict()
                original=canonical_hash(ir)
                layout,d=QuestionStructureParser().build(ir)
                self.assertEqual(canonical_hash(ir),original)
                self.assertEqual(sum(n['depth']==0 for n in d['nodes']),3)
                self.assertEqual(d['total_points_candidate'],None if i==2 else 100)
                if i==1:
                    self.assertEqual([n['score']['effective_points_candidate'] for n in d['nodes'] if n['leaf_candidate']],[20,20,30,10,10,10])
                    self.assertEqual(d['formula_regions'],[])
                    self.assertEqual(d['figure_regions'],[])
                if i==2:
                    self.assertTrue(all(n['score']['semantics']=='unset' for n in d['nodes']))
                    self.assertIn('inline_subquestion_label',d['review_flags'])
                    self.assertGreaterEqual(len(d['formula_regions']),3)
                    self.assertNotEqual(layout['lines'][0]['native_orders'][0],0)
                if i==3:
                    self.assertEqual([n['score']['points'] for n in d['nodes']],[30,30,40])
                    self.assertEqual(len(d['figure_regions']),1)
                    self.assertEqual(d['figure_regions'][0]['assigned_question_key'],'q3')
                    self.assertAlmostEqual(d['figure_regions'][0]['bbox'][0],56.4,delta=1)


class AdditionalSafetyTests(unittest.TestCase):
    def build(self, elements):
        return QuestionStructureParser().build(document(elements))[1]

    def test_ordered_content_anchors_text_formula_score(self):
        values = [text('e0', '問題1 Text A（30点）'),
                  text('e1', 'x', x=110, y=100, math=True),
                  text('e2', 'Text B', x=160, y=100)]
        ir = document(values)
        ir['pages'][0]['elements'][1]['bbox'] = [110, 100, 120, 112]
        ir['pages'][0]['elements'][2]['bbox'] = [160, 100, 196, 112]
        _, draft = QuestionStructureParser().build(ir)
        content = draft['nodes'][0]['ordered_content']
        self.assertEqual([item['type'] for item in content], ['text', 'formula_region', 'text', 'score_expression'])
        self.assertEqual(content[1]['region_id'], 'formula-0001')
        self.assertEqual(content[1]['source_element_ids'], ['e1'])
        self.assertEqual(content[0]['order'], 0)
        self.assertEqual([item['order'] for item in content], list(range(len(content))))

    def test_ordered_content_is_deterministic_and_multipage(self):
        pages = [document([text('e0', '問題1 Text', y=100)])['pages'][0],
                 {**document([text('e1', 'x', y=100, math=True), text('e2', 'continued', x=100, y=120)])['pages'][0],
                  'page_index': 1}]
        _, first = QuestionStructureParser().build(document([], pages))
        _, second = QuestionStructureParser().build(document([], pages))
        self.assertEqual(canonical_hash(first), canonical_hash(second))
        self.assertEqual([i['page_index'] for i in first['nodes'][0]['ordered_content']], [0, 1, 1])

    def test_coordinate_rotation_crop_offset_margin_and_clipping(self):
        page = PageCoordinateSpace((10, 20, 310, 420), (20, 40, 300, 400), 0)
        self.assertEqual(page_pixel_size(page), (280, 360))
        self.assertEqual(pdf_bbox_to_pixel([20, 40, 30, 50], page).as_dict()['bbox'], [0, 0, 10, 10])
        self.assertEqual(expand_bbox([20, 40, 30, 50], 5, bounds=page.cropbox), [20, 40, 35, 55])
        for rotation, expected, size in (
                (90, [350, 0, 360, 10], (360, 280)),
                (180, [270, 350, 280, 360], (280, 360)),
                (270, [0, 270, 10, 280], (360, 280))):
            rotated = PageCoordinateSpace(page.mediabox, page.cropbox, rotation)
            self.assertEqual(page_pixel_size(rotated), size)
            self.assertEqual(pdf_bbox_to_pixel([20, 40, 30, 50], rotated).as_dict()['bbox'], expected)
        clipped = pdf_bbox_to_pixel([0, 0, 25, 45], page, margin=10)
        self.assertEqual(clipped.as_dict()['bbox'], [0, 0, 15, 15])
        self.assertTrue(clipped.clipped)

    def test_routing_evidence_does_not_assert_formula_semantics(self):
        values = [text('e0', '問題1 body'), text('e1', 'x', x=100, y=130, math=True),
                  text('e2', '3', x=112, y=126, math=True, size=8)]
        _, draft = QuestionStructureParser().build(document(values))
        evidence = draft['formula_regions'][0]['routing_evidence']
        self.assertEqual(evidence['semantic_assertion'], 'none')
        self.assertIn(evidence['strength'], {'strong', 'supporting', 'weak'})
        self.assertIn('source_span_count', evidence)

    def test_explicit_child_score_blocks_each_child_distribution(self):
        d=self.build([text('e0','問題1 a (各20点)'),text('e1','(1) b (10点)',y=160),text('e2','(2) c',y=220)])
        self.assertEqual(d['nodes'][0]['score']['semantics'],'ambiguous')
        self.assertIsNone(d['nodes'][2]['score']['effective_points_candidate'])
        self.assertIsNone(d['total_points_candidate'])

    def test_inline_reference_is_not_a_major_question(self):
        d=self.build([text('e0','問題1 body'),text('e1','問題1について説明する',y=150)])
        self.assertEqual(len(d['nodes']),1)

    def test_unassigned_formula_before_question_is_reviewed(self):
        d=self.build([text('e0','x=1',y=60,math=True),text('e1','問題1 body',y=120)])
        self.assertIsNone(d['formula_regions'][0]['assigned_question_key'])
        self.assertIn('unassigned_formula_region',d['review_flags'])

    def test_config_change_changes_config_hash(self):
        self.assertNotEqual(QuestionStructureParser().config_hash,QuestionStructureParser({'formula_gap':20}).config_hash)

    def test_draft_failure_has_no_partial_nodes(self):
        from unittest.mock import patch
        from scoring.question_drafts import QuestionDraftService, DraftError
        case=DraftApiTests()
        case.setUp()
        try:
            with case.sf() as s:
                with patch.object(QuestionStructureParser,'build',side_effect=ValueError('private /opt/path')):
                    with self.assertRaises(DraftError):
                        QuestionDraftService(s,case.root/'artifacts').generate(case.extraction['id'])
                self.assertEqual(s.scalar(select(func.count()).select_from(QuestionImportDraftNode)),0)
                record=s.scalar(select(QuestionImportDraft))
                self.assertEqual(record.state,'failed')
                self.assertNotIn('/opt',record.error_message)
        finally:
            case.tearDown()


class DraftMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_upgrade_preserves_existing_test_tables(self):
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import create_engine, inspect
        with tempfile.TemporaryDirectory() as folder:
            config=Config('alembic.ini')
            url=f'sqlite:///{folder}/migration.db'
            config.set_main_option('sqlalchemy.url',url)
            command.upgrade(config,'head')
            command.downgrade(config,'0005_question_import_extraction')
            engine=create_engine(url)
            self.assertIn('test_questions',inspect(engine).get_table_names())
            self.assertNotIn('question_import_drafts',inspect(engine).get_table_names())
            engine.dispose()
            command.upgrade(config,'head')
            engine=create_engine(url)
            self.assertIn('question_import_draft_nodes',inspect(engine).get_table_names())
            self.assertEqual(len(inspect(engine).get_unique_constraints('question_import_drafts')),1)
            engine.dispose()


class ContextScoreTests(unittest.TestCase):
    def test_unassigned_score_is_evidence_not_an_invented_question(self):
        _,d=QuestionStructureParser().build(document([text('e0','表紙 (100点)',y=30),text('e1','問題1 body',y=100)]))
        self.assertEqual(len(d['nodes']),1)
        self.assertEqual(len(d['unassigned_score_expressions']),1)
        self.assertIn('unassigned_score_expression',d['review_flags'])
        self.assertIsNone(d['total_points_candidate'])
