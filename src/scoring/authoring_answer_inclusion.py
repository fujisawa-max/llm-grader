"""Teacher diagram acceptance supersedes automatic non-answer classification."""


def accept_answer_diagram(entry, previous_records, *, target_valid):
    """Promote only a newly accepted diagram on a mapped, auto-excluded entry.

    Keep the classifier evidence. Existing teacher disposition decisions are
    authoritative, and merely saving an already accepted diagram is not a new
    teacher acceptance action.
    """
    if (not target_valid or entry.get('disposition') != 'excluded'
            or entry.get('mapping_state') != 'automatic'
            or entry.get('ignore_reason') != 'classified_as_non_answer'
            or (entry.get('semantic_classification') or {}).get('status') != 'classified'
            or (entry.get('teacher_correction') or {}).get('disposition') in
            {'ignored', 'excluded', 'unassigned'}):
        return False
    already_accepted = {record.get('id') for record in previous_records
                        if record.get('state') == 'accepted'}
    if not any(record.get('state') == 'accepted' and record.get('id') not in already_accepted
               and record.get('trust_state') != 'hard_invalid'
               for record in entry.get('diagram_records', [])):
        return False
    entry['disposition'] = 'include'
    entry['teacher_correction'] = {**(entry.get('teacher_correction') or {}),
        'disposition': 'include', 'teacher_confirmed': True}
    return True
