import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf

from scoring.regions import crop_image
from scoring.student_answer_runtime import RuntimeStudentAnswerStages, compact_reconstruction_input
from scoring.pdf_native import sha256_file


class BlockerTests(unittest.TestCase):
    def test_normalized_crop_scales_and_clips(self):
        with tempfile.TemporaryDirectory() as tmp:
            for width, height in [(100, 200), (200, 400), (150, 300)]:
                source = Path(tmp) / f'{width}.png'
                doc = pymupdf.open()
                doc.new_page(width=width, height=height).get_pixmap().save(source)
                doc.close()
                result = crop_image(source, [0.1, 0.2, 0.5, 0.6], Path(tmp)/f'{width}-crop.png', padding=0,
                                    coordinate_space="normalized")
                self.assertEqual(result['bbox_pixels'], [width//10, height//5, width//2, height*3//5])
                edge = crop_image(source, [0, 0, 1, 1], Path(tmp)/f'{width}-edge.png',
                                  coordinate_space="normalized")
                self.assertEqual(edge['bbox_pixels'], [0, 0, width, height])

    def payload(self, path):
        return {'question': {'question_id': 'q1', 'context': {'effective_text': 'parent + self'}},
                'source_answer': {'pages': [{'page_id': 'p1', 'sha256': sha256_file(path)}]},
                'ricoh_evidence': [{'page_id': 'p1', 'raw': 'RAW_SECRET', 'normalized': {'text_blocks': [{'text': '2+2=5'}]}}],
                'formula_evidence': []}

    def test_compact_removes_raw_and_transfers_only_owned_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'page.png'
            path.write_bytes(b'fixture')
            payload = self.payload(path)
            compact = compact_reconstruction_input(payload)
            self.assertNotIn('RAW_SECRET', str(compact))
            self.assertIn('2+2=5', str(compact))
            stages = RuntimeStudentAnswerStages(None, {}, image_resolver=lambda _: [('p1', path)])
            with patch.object(stages, '_structured_request', return_value={}) as request:
                stages.ornith_reconstruction(payload)
                self.assertEqual(request.call_args.args[-1], [('p1', path)])
            stages.image_resolver = lambda _: [('other-question-page', path)]
            with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                stages.ornith_reconstruction(payload)

    def test_image_missing_refused(self):
        stages = RuntimeStudentAnswerStages(None, {})
        with self.assertRaisesRegex(ValueError, 'RESOLVER_REQUIRED'):
            stages.ornith_reconstruction({})
