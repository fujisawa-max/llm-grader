"""Bounded presentation recovery for explicitly known LaTeX control words."""
import re

HSPACE = r'(?:[^\S\r\n]|\u200b|\ufeff)'
WSPACE = r'(?:\s|\u200b|\ufeff)'
CONTROL_WORDS = ('frac', 'dfrac', 'tfrac', 'sqrt', 'text', 'mathrm', 'operatorname', 'dot', 'ddot', 'vec', 'hat', 'bar')


def recover_controls(text, *, multiline=False):
    space = WSPACE if multiline else HSPACE
    steps = []
    for word in sorted(CONTROL_WORDS, key=lambda w: (-len(w), w)):
        pattern = r'\\' + space+'*' + (space+'*').join(word) + r'(?![A-Za-z])(?='+space+r'*[\{\[])'
        def replace(match):
            value = '\\'+word
            if match.group() != value:
                steps.append({'type': 'latex_control_spacing', 'source': match.group(), 'replacement': value})
            return value
        text = re.sub(pattern, replace, text)
    return text, steps


def control_continuation(before, following):
    """Only a known control word interrupted by a physical line boundary."""
    _, steps = recover_controls(before+'\n'+following, multiline=True)
    return any('\n' in step['source'] for step in steps)
