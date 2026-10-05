"""Source-guided OCR presentation recovery; never solve or rewrite mathematics.

Offsets refer to raw selected model text. Candidate selection is bounded and
independent of model/runtime clients. Rejected candidates remain diagnostic.
"""
from __future__ import annotations

import re

from .vision_output import unwrap_math_output

NUMERIC = r'(?<![A-Za-z\d])(?:[-−]?\d+(?:\.\d+)?)'
LETTERS = r'[^\W\d_]+'
ENVIRONMENT = r'\\(?:begin|end)\{(?:aligned|align\*?|gathered|gather\*?|matrix|pmatrix|bmatrix|cases|array)\}(?:\{[lcr| ]+\})?'
FUNCTIONS = {'sin', 'cos', 'tan', 'log', 'ln', 'lim', 'exp'}


def lexical_text(text):
    return re.sub(r'\\[A-Za-z]+', '', re.sub(ENVIRONMENT, '', text))


def source_tokens(text):
    identifiers = set(re.findall(LETTERS, lexical_text(text))) | (set(re.findall(r'\\([A-Za-z]+)', text)) & FUNCTIONS)
    return identifiers, re.findall(NUMERIC, text.replace('−', '-'))


def detokenize(text, source):
    """Recover only complete source tokens, never globally remove whitespace."""
    identifiers, numbers = source_tokens(source)
    steps = []
    for token in sorted(identifiers | set(numbers), key=lambda t: (-len(t), t)):
        if len(token) < 2:
            continue
        # A number cannot be recovered from a prefix of a larger spaced number.
        tail = r'(?![\w.]|[ \t]+\d|[ \t]*\.[ \t]*\d)' if token in numbers else r'(?![\w]|[ \t]+[A-Za-z](?:[ \t]|$))'
        pattern = r'(?<![\w.\\])' + r'[ \t]*'.join(re.escape(c) for c in token) + tail
        def replace(match):
            raw = match.group()
            if raw != token and re.search(r'[ \t]', raw):
                steps.append({'type': 'source_token', 'source': raw, 'replacement': token})
            return token
        text = re.sub(pattern, replace, text)
    before = text
    # Syntax-only spacing outside text arguments. Ordinary text spacing and
    # operators inside source-supported \text are content, not math syntax.
    def syntax_spacing(value):
        value = re.sub(r'(\\[A-Za-z]+)[ \t]+(?=\{)', r'\1', value)
        value = re.sub(r'\{[ \t]+', '{', value)
        value = re.sub(r'[ \t]+\}', '}', value)
        value = re.sub(r'[ \t]*([=+^_])[ \t]*', r'\1', value)
        return re.sub(r'\}[ \t]+(?=\{)', '}', value)
    pieces, cursor = [], 0
    for match in re.finditer(r'\\text[ \t]*\{([^{}]*)\}', text):
        pieces.extend([syntax_spacing(text[cursor:match.start()]), r'\text{'+match[1].strip()+'}'])
        cursor = match.end()
    pieces.append(syntax_spacing(text[cursor:]))
    text = ''.join(pieces)
    if before != text:
        steps.append({'type': 'latex_syntax_whitespace'})
    return text.strip(), steps


def extraction_spans(raw, source):
    """Line candidates plus explicit equation continuations; no prose peeling.

Repeated source equation labels delimit repeated blocks even on one line.
A continuation must begin with an operator or continue unclosed braces, and
must have no unsupported letters. Full environments are considered intact.
"""
    spans = []
    cursor = 0
    identifiers, _ = source_tokens(source)
    roots = [m.group(1) for m in re.finditer(r'\b([A-Za-z]+)\s*=', source)]
    root_patterns = [r'(?<![\w\\])' + r'[ \t]*'.join(map(re.escape, root)) + r'[ \t]*=' for root in roots]
    for line in raw.splitlines(keepends=True):
        start, end = cursor + len(line)-len(line.lstrip()), cursor + len(line.rstrip())
        cursor += len(line)
        value = raw[start:end]
        if not value or value.startswith('```'):
            continue
        starts = sorted(set(m.start() for pattern in root_patterns for m in re.finditer(pattern, value)))
        # Do not extract an equation from an explanatory prefix. Only split
        # repeated labels when the first starts at the line's beginning.
        cuts = starts if starts and starts[0] == 0 else [0]
        for index, cut in enumerate(cuts):
            finish = cuts[index+1] if index+1 < len(cuts) else len(value)
            candidate = value[cut:finish].rstrip()
            if re.search(r'[=+^_−×÷]|\\(?:frac|sqrt|text|begin)\b', candidate):
                spans.append({'start': start+cut, 'end': start+cut+len(candidate), 'raw_candidate': candidate})
    # Add only source-compatible adjacent operator continuations, not unrelated
    # expressions or answer-like text. Keep component candidates for diagnosis.
    joined = []
    for i, span in enumerate(spans):
        end, combined = span['end'], span['raw_candidate']
        for following in spans[i+1:]:
            if raw[end:following['start']].strip():
                break
            value, _ = detokenize(following['raw_candidate'], source)
            unknown = set(re.findall(LETTERS, lexical_text(value))) - identifiers - FUNCTIONS
            continuation = value.startswith(('=', '+', '-', r'\end{')) or combined.count('{') > combined.count('}')
            if unknown or not continuation:
                break
            end = following['end']
            combined = raw[span['start']:end]
            joined.append({'start': span['start'], 'end': end, 'raw_candidate': combined})
    if r'\begin{' in raw and r'\end{' in raw:
        joined.append({'start': 0, 'end': len(raw), 'raw_candidate': raw})
    if not spans:
        return [{'start': 0, 'end': len(raw), 'raw_candidate': raw}]
    # A source-unsupported text command can delimit a noisy OCR suffix, but
    # source-supported mathematical \text remains part of the formula. Keep
    # the full attempt and its exact offsets as well as the bounded prefix.
    prefixes = []
    for span in spans:
        for match in re.finditer(r'\\text[ \t]*\{([^{}]*)\}', span['raw_candidate']):
            payload, _ = detokenize(match[1], source)
            if set(re.findall(LETTERS, payload)) - identifiers:
                prefix = span['raw_candidate'][:match.start()].rstrip()
                if prefix and syntax_valid(prefix) and re.search(r'[=]|\\(?:frac|sqrt)\b', prefix):
                    prefixes.append({'start': span['start'], 'end': span['start']+len(prefix), 'raw_candidate': prefix})
                break
    return (spans + joined + prefixes)[:64]


def syntax_valid(text):
    depth = 0
    for match in re.finditer(r'(?<!\\)[{}]', text):
        depth += 1 if match.group() == '{' else -1
        if depth < 0:
            return False
    if depth or text.rstrip().endswith(('=', '+', '-', r'\frac', r'\sqrt')):
        return False
    # Common structural commands must have all required nonempty arguments.
    for match in re.finditer(r'\\(frac|dfrac|tfrac|sqrt|text|dot)\b', text):
        cursor = match.end()
        if match.group(1) == 'sqrt' and text[cursor:cursor+1] == '[':
            closing = text.find(']', cursor)
            if closing < 0:
                return False
            cursor = closing+1
        for _ in range(2 if match.group(1) in ('frac', 'dfrac', 'tfrac') else 1):
            if text[cursor:cursor+1] != '{':
                return False
            level, opening = 1, cursor
            cursor += 1
            while cursor < len(text) and level:
                if text[cursor] == '{' and text[cursor-1] != '\\':
                    level += 1
                elif text[cursor] == '}' and text[cursor-1] != '\\':
                    level -= 1
                cursor += 1
            if level or not text[opening+1:cursor-1].strip():
                return False
    return True


def evaluate(text, source):
    identifiers, source_numbers = source_tokens(source)
    observed = set(re.findall(LETTERS, lexical_text(text))) | (set(re.findall(r'\\([A-Za-z]+)', text)) & FUNCTIONS)
    numbers = re.findall(NUMERIC, text.replace('−', '-'))
    unsupported = sorted(observed - identifiers)
    missing = sorted(identifiers - observed)
    unsupported_numbers = sorted(set(numbers) - set(source_numbers))
    remaining = iter(numbers)
    numeric_match = all(any(token == value for token in remaining) for value in source_numbers)
    reasons = []
    if unsupported:
        reasons.append('math_identifier_invalid')
    if missing:
        reasons.append('math_identifier_missing')
    if not numeric_match or unsupported_numbers:
        reasons.append('math_ocr_numeric_mismatch')
    if re.search(r'(?<![\w.])\d[ \t]+\d|\d[ \t]+\.[ \t]*\d', text):
        reasons.append('math_detokenization_unresolved')
    if not syntax_valid(text):
        reasons.append('math_latex_syntax_invalid')
    if not text or len(text) > 12000 or not re.search(r'[=+^_−×÷]|\\[A-Za-z]+', text):
        reasons.append('math_formula_not_found')
    score = (10*len(observed & identifiers) + 5*sum(min(numbers.count(n), source_numbers.count(n)) for n in set(source_numbers))
             + 2*text.count('=') + 3*len(re.findall(r'\\(?:frac|sqrt)\b', text))
             - 30*len(unsupported) - 30*len(missing) - 30*len(unsupported_numbers) - 50*(not numeric_match)
             - 5*max(0, len(numbers)-len(source_numbers)) - len(text)/1000)
    return {'source_identifier_matches': sorted(observed & identifiers), 'source_numeric_matches': [n for n in numbers if n in source_numbers],
            'unsupported_identifiers': unsupported, 'missing_identifiers': missing, 'unsupported_numbers': unsupported_numbers,
            'numeric_sequence_preserved': numeric_match, 'score': round(score, 3),
            'accepted': not reasons, 'rejection_reason': reasons[0] if reasons else None,
            'validation_reasons': reasons, 'numeric_review_required': source_numbers != numbers}


def select_candidate(raw, source):
    """Keep all attempts, select deterministically among validated candidates."""
    candidates, seen = [], {}
    extraction_text, base_offset = raw, 0
    outer_steps = []
    if raw.strip().startswith('```') or (raw.strip().startswith(('$$', r'\[', r'\(')) and '\n' in raw):
        try:
            extraction_text = unwrap_math_output(raw)
            base_offset = raw.find(extraction_text)
            outer_steps = [{'type': 'outer_wrapper_removed'}]
        except ValueError as exc:
            return {'candidate_count': 1, 'duplicate_count': 0, 'selected_candidate_index': 0,
                'selected_candidate': '', 'normalized_ocr_text': '', 'normalization_steps': [],
                'candidate_scores': [{'index': 0, 'start': 0, 'end': len(raw), 'raw_candidate': raw,
                    'normalized_candidate': '', 'normalization_steps': [], 'accepted': False,
                    'score': -1000, 'rejection_reason': str(exc)}],
                'rejection_reason': str(exc), 'numeric_review_required': False, 'validation_accepted': False}
    for index, span in enumerate(extraction_spans(extraction_text, source)):
        span = {**span, 'start': span['start']+base_offset, 'end': span['end']+base_offset}
        candidate = {'index': index, **span}
        try:
            unwrapped = unwrap_math_output(span['raw_candidate'])
            normalized, steps = detokenize(unwrapped, source)
            steps = outer_steps + steps
            if unwrapped != span['raw_candidate']:
                steps.insert(0, {'type': 'outer_wrapper_removed'})
            candidate.update(normalized_candidate=normalized, normalization_steps=steps, **evaluate(normalized, source))
        except ValueError as exc:
            candidate.update(normalized_candidate='', normalization_steps=[], accepted=False,
                             rejection_reason=str(exc), score=-1000)
        key = candidate['normalized_candidate']
        if key and key in seen:
            candidate['duplicate_of'] = seen[key]
        elif key:
            seen[key] = index
        candidates.append(candidate)
    unique = [c for c in candidates if 'duplicate_of' not in c]
    accepted = [c for c in unique if c['accepted']]
    selected = max(accepted or unique, key=lambda c: (c['score'], -c['index']))
    return {'candidate_count': len(candidates), 'duplicate_count': sum('duplicate_of' in c for c in candidates),
            'selected_candidate_index': selected['index'], 'selected_candidate': selected['normalized_candidate'],
            'normalized_ocr_text': selected['normalized_candidate'], 'normalization_steps': selected['normalization_steps'],
            'candidate_scores': candidates, 'rejection_reason': selected['rejection_reason'],
            'numeric_review_required': selected.get('numeric_review_required', False),
            'validation_accepted': selected['accepted']}
