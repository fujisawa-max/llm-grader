"""Scoped teacher text corrections, derived on successful draft Save only.

These receipts never approve formula/figure decisions, parser warnings,
classification, criterion grouping, points or executable scoring policy.
"""
from copy import deepcopy

from .pdf_native import canonical_hash


def meaningful_text(value):
    return ''.join(value.split())


def _receipt(container, old_container, before, after, revision):
    # This field is server-derived; a round trip cannot manufacture approval.
    if not isinstance(container, dict) or (old_container is not None and not isinstance(old_container, dict)):
        from .test_authoring import AuthoringError
        raise AuthoringError('AUTHORING_INVALID_TEXT', '本文の確認情報を確認してください。')
    previous = deepcopy((old_container or {}).get('text_review'))
    container.pop('text_review', None)
    if previous is not None:
        container['text_review'] = previous
    if meaningful_text(before) == meaningful_text(after):
        return
    container['text_review'] = {
        'teacher_confirmed': True, 'confirmation_origin': 'manual_edit',
        'previous_text_sha256': canonical_hash(before),
        'reviewed_text_sha256': canonical_hash(after), 'revision': revision,
        **({'previous_review': previous} if previous is not None else {}),
    }


def restore_question_corrections(snapshot, previous):
    """Question source validation receives only previously persisted receipts."""
    old = {node['stable_key']: node for node in previous['nodes']}
    for node in snapshot['nodes']:
        node.pop('teacher_correction', None)
        correction = old.get(node['stable_key'], {}).get('teacher_correction')
        if correction is not None:
            node['teacher_correction'] = deepcopy(correction)


def confirm_manual_text_edits(snapshot, previous, revision):
    from .test_authoring import source_text
    from .authoring_sources import rubric_snapshot_projection

    old_nodes = {node['stable_key']: node for node in previous['nodes']}
    for node in snapshot['nodes']:
        prior = old_nodes.get(node['stable_key'])
        if prior is None:
            continue
        key = node['stable_key']
        previous_buffer = previous.get('question_text_buffers', {}).get(key)
        current_buffer = snapshot.get('question_text_buffers', {}).get(key)
        before = previous_buffer if isinstance(previous_buffer, str) else source_text(prior, previous)
        after = current_buffer if isinstance(current_buffer, str) else source_text(node, snapshot)
        # A saved teacher buffer is authoritative editable text even when it
        # cannot be reconciled into the PDF-anchored ordered content. Require
        # the buffer and body to agree before recording the scoped text receipt;
        # source_warnings still reports the separate source-mapping problem.
        if current_buffer is not None and (not isinstance(current_buffer, str) or node.get('body_text') != current_buffer):
            continue
        correction = deepcopy(node.get('teacher_correction') or {})
        _receipt(correction, prior.get('teacher_correction'), before, after, revision)
        if correction:
            node['teacher_correction'] = correction

    old_answer = {entry['id']: entry for entry in previous.get('domains', {}).get('answer', {}).get('entries', [])}
    for entry in snapshot.get('domains', {}).get('answer', {}).get('entries', []):
        prior = old_answer.get(entry['id'])
        correction = deepcopy(entry.get('teacher_correction') or {})
        _receipt(correction, (prior or {}).get('teacher_correction'),
                 prior['answer_text'] if prior else entry['answer_text'], entry['answer_text'], revision)
        if correction:
            entry['teacher_correction'] = correction
        else:
            entry.pop('teacher_correction', None)

    old_rubric = {entry['id']: entry for entry in previous.get('domains', {}).get('rubric', {}).get('entries', [])}
    rubric = snapshot.get('domains', {}).get('rubric')
    for entry in (rubric or {}).get('entries', []):
        criteria = {item['id']: item for item in old_rubric.get(entry['id'], {}).get('criteria', [])}
        for item in entry['criteria']:
            prior = criteria.get(item['id'])
            provenance = deepcopy(item.get('provenance') or {})
            _receipt(provenance, (prior or {}).get('provenance'),
                     prior['description'] if prior else item['description'], item['description'], revision)
            if provenance:
                item['provenance'] = provenance
            else:
                item.pop('provenance', None)
    if rubric is not None:
        snapshot['rubrics'] = rubric_snapshot_projection(rubric, set(old_nodes) | {node['stable_key'] for node in snapshot['nodes']})
