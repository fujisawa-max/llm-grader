"""Detection uncertainty is confirmable; source-integrity failures never are.

Call only after canonical candidate membership and crop safety validation.
Unknown failures deliberately remain hard-invalid.
"""
TEACHER_CONFIRMABLE_REASONS = frozenset({
    'diagram_geometry_ambiguous', 'diagram_grouping_ambiguous',
    'diagram_ricoh_output_truncated', 'diagram_ricoh_unavailable',
    'diagram_ricoh_timeout', 'diagram_ricoh_invalid_json',
    'diagram_ricoh_low_confidence',
})


def diagram_trust(candidate):
    reason = candidate.get('reason_code')
    if reason in TEACHER_CONFIRMABLE_REASONS:
        return 'teacher_confirmable'
    if reason or candidate.get('status') == 'unresolved':
        return 'hard_invalid'
    return 'trusted'
