"""Geometry fixtures use synthetic native spans; never access application data."""
from types import SimpleNamespace
import unittest

from scoring.model_answer_geometry import build_geometry_entries, map_segments, native_segments
from scoring.model_answer_classification import build_classification, ClassificationOutputError


def question(key, parent=None, gradable=True, content=None):
    return SimpleNamespace(id=key, parent_id=parent, display_label=key.split('.')[-1],
                           question_number=key.removeprefix('q'), stable_question_key=key,
                           is_gradable=gradable, question_text=None, content=content, sort_order=1)


def document(pages):
    return {'source': {'sha256': 'fixture-sha', 'material_id': 'fixture-material'},
            'pages': [{'page_index': i, 'width': 600, 'height': 800,
                       'elements': [{'element_id': f'p{i}-e{n}', 'type': 'text', 'native_text': text,
                                     'bbox': [x, y, x + 120, y + 12], 'reading_order': n,
                                     'native': {'block_index': n, 'line_index': 0}}
                                    for n, (text, x, y) in enumerate(lines)]}
                      for i, lines in enumerate(pages)]}


class GeometryTests(unittest.TestCase):
    def test_each_question_region_no_last_question_collapse(self):
        qs = [question(f'q{i}') for i in range(1, 4)]
        problem = document([[('Question 1', 30, 100), ('Question 2', 30, 400), ('Question 3', 30, 700)]])
        answers = document([[('Answer A', 30, 180), ('Answer B', 30, 470), ('Answer C', 30, 740)]])
        segments, _ = map_segments(answers, qs, question_ir=problem)
        self.assertEqual([s['geometry']['question_id'] for s in segments], ['q1', 'q2', 'q3'])
        entries, _ = build_geometry_entries(answers, qs, question_ir=problem)
        self.assertEqual([e['answer_text'] for e in entries], ['Answer A', 'Answer B', 'Answer C'])
        self.assertEqual(native_segments(answers)[0]['id'], native_segments(answers)[0]['id'])
        self.assertEqual(entries[0]['source']['segments'][0]['original_text'], 'Answer A')

    def test_sibling_boundary_and_last_sibling(self):
        ir = document([[('Question 1', 30, 100), ('last one', 30, 350),
                        ('Question 2', 30, 400), ('last two', 30, 780)]])
        segments, _ = map_segments(ir, [question('q1'), question('q2')])
        self.assertEqual([s['geometry']['question_id'] for s in segments], ['q1', 'q1', 'q2', 'q2'])

    def test_child_and_parent_only_not_other_root(self):
        ir = document([[('Question 1', 30, 100), ('shared explanation', 30, 140),
                        ('(1) First', 30, 200), ('first answer', 30, 220),
                        ('(2) Second', 30, 300), ('second answer', 30, 330), ('Question 2', 30, 500)]])
        segments, _ = map_segments(ir, [question('q1', gradable=False), question('q1.1', 'q1'),
                                       question('q1.2', 'q1'), question('q2')])
        self.assertEqual(segments[1]['geometry']['assignment_status'], 'parent_only')
        self.assertEqual(segments[3]['geometry']['question_id'], 'q1.1')
        self.assertEqual(segments[5]['geometry']['question_id'], 'q1.2')

    def test_column_mapping_and_ambiguous_duplicate_anchors(self):
        ir = document([[('Question 1', 30, 100), ('Question 2', 330, 100),
                        ('left answer', 30, 180), ('right answer', 330, 180)]])
        segments, _ = map_segments(ir, [question('q1'), question('q2')])
        self.assertEqual([s['geometry']['question_id'] for s in segments[2:]], ['q1', 'q2'])
        duplicate = document([[('Question 1', 30, 100), ('Question 1', 30, 100), ('ambiguous', 30, 180)]])
        segments, _ = map_segments(duplicate, [question('q1')])
        self.assertEqual(segments[-1]['geometry']['assignment_status'], 'ambiguous')

    def test_cross_page_requires_continuation_evidence(self):
        ir = document([[('Question 1', 30, 700)], [('unknown continuation', 30, 30),
                                                ('Question 1', 30, 100), ('explicit continuation', 30, 180)]])
        segments, _ = map_segments(ir, [question('q1')])
        self.assertIsNone(segments[1]['geometry']['question_id'])
        self.assertEqual(segments[-1]['geometry']['question_id'], 'q1')

    def test_unknown_heading_and_text_above_first_heading_not_last_fallback(self):
        ir = document([[('preface', 30, 20), ('Question 1', 30, 100), ('answer', 30, 150),
                        ('Question 99', 30, 250), ('unmatched answer', 30, 300)]])
        segments, _ = map_segments(ir, [question('q1')])
        self.assertIsNone(segments[0]['geometry']['question_id'])
        self.assertIsNone(segments[-1]['geometry']['question_id'])

    def test_incompatible_geometry_does_not_use_problem_anchors(self):
        answer = document([[('no heading', 30, 180)]])
        problem = document([[('Question 1', 30, 100)]])
        problem['pages'][0]['width'] = 900
        segments, _ = map_segments(answer, [question('q1')], question_ir=problem)
        self.assertIsNone(segments[0]['geometry']['question_id'])

    def test_classifier_uses_native_ids_only_and_keeps_categories_separate(self):
        source = 'Prompt\nAnswer\nAlternate\n5 points\nNote\nMaybe'
        categories = ['question', 'model_answer', 'alternative_answer', 'rubric', 'note', 'uncertain']
        spans, assignments, offset = [], [], 0
        for i, (text, category) in enumerate(zip(source.splitlines(keepends=True), categories)):
            spans.append({'id': f'pdf-{i}', 'text': text, 'start': offset, 'end': offset + len(text)})
            assignments.append({'id': f'pdf-{i}', 'category': category, 'confidence': .99})
            offset += len(text)
        result = build_classification(source, {'overall_confidence': .99, 'segments': assignments}, source_segments=spans)
        self.assertEqual(result['primary_answer_text'], 'Answer\n')
        self.assertEqual(result['status'], 'needs_teacher_review')
        self.assertEqual(result['alternative_answers'][0]['text'], 'Alternate\n')
        for bad in ([*assignments, assignments[0]], [{**assignments[0], 'id': 'fake'}, *assignments[1:]]):
            with self.assertRaises(ClassificationOutputError):
                build_classification(source, {'overall_confidence': .99, 'segments': bad}, source_segments=spans)
        with self.assertRaises(ClassificationOutputError):
            build_classification(source, {'overall_confidence': .99, 'segments': assignments},
                                 source_segments=[{**spans[0], 'text': 'invented'}, *spans[1:]])


def test_unicode_and_whitespace_are_preserved_in_native_segments():
    ir = document([[('  原文😀 $x_1$  ', 30, 100)]])
    segment = native_segments(ir)[0]
    assert segment['original_text'] == '  原文😀 $x_1$  '
    assert segment['text_end'] - segment['text_start'] == len(segment['original_text'])
    assert segment['source_spans'][0]['text'] == segment['original_text']


def test_anchored_source_element_survives_changed_question_label():
    problem = document([[('Original heading without numbering', 30, 100)]])
    q = question('q1', content={'items': [{'source_element_ids': ['p0-e0']}]})
    answer = document([[('Answer near original heading', 30, 180)]])
    segments, _ = map_segments(answer, [q], question_ir=problem)
    assert segments[0]['geometry']['question_id'] == 'q1'
    assert segments[0]['geometry']['region']['origin'] == 'question_source_element'


def test_native_reading_order_with_all_headings_first_does_not_collapse_to_q3():
    # PDF insertion order can list every heading before the later-added answer blocks.
    # Stateful label parsers attach all three additions to their last Q3 match.
    ir = document([[('Question 1', 30, 100), ('Question 2', 30, 400), ('Question 3', 30, 700),
                    ('Answer one', 30, 180), ('Answer two', 30, 470), ('Answer three', 30, 740)]])
    entries, _ = build_geometry_entries(ir, [question(f'q{i}') for i in range(1, 4)])
    assert [(entry['question_id'], entry['answer_text']) for entry in entries] == [
        ('q1', 'Answer one'), ('q2', 'Answer two'), ('q3', 'Answer three'),
    ]
