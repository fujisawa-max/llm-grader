"""Stable correction targets for existing Question source-review requirements."""

WARNING_LABELS = {
    'ambiguous_score': '配点の読み取り',
    'score_scope_ambiguous': '配点の対応範囲',
    'formula_unresolved': '数式の読み取り',
    'native_formula_requires_teacher_edit': '数式の教師入力',
    'figure_unresolved': '図の読み取り',
    'reasoning_output_requires_review': '画像解析の読み取り',
    'native_vision_disagreement': 'PDFと画像解析の読み取り結果',
    'ambiguous_parent_assignment': '親設問の対応',
    'duplicate_question_label': '設問番号',
    'ambiguous_geometric_order': '設問の並び順',
    'unresolved_vector_evidence': 'ベクトル図の読み取り',
    'inline_subquestion_label': '本文内の小問名と分割範囲',
    'unassigned_content': '設問へ対応付けできなかった読み取り部分',
    'unassigned_score_expression': '対応先が不明な配点の記載',
    'direct_score_with_children': '大問と小問の配点方法',
    'each_child_without_clear_children': '配点を適用する小問範囲',
    'no_question_candidates': '問題の読み取り結果',
}


def question_source_target(question, *, kind, warning=None, region_id=None, materials=()):
    document = question['document']
    bindings = [m['id'] for m in materials if m.get('role') == 'question_sheet'
                and m.get('sha256') == document.get('source_pdf_sha256')]
    material_id = document.get('material_id') or (bindings[0] if len(bindings) == 1 else None)
    result = {'domain': 'question', 'correction_type': kind,
              'source_material_id': material_id,
              'source_review_id': document.get('id'),
              'source_sha256': document.get('source_pdf_sha256')}
    if warning:
        index = next((i for i, item in enumerate(document.get('warnings', []))
                      if item['id'] == warning['id']), 0) + 1
        result.update(source_review_index=index, warning_id=warning['id'], warning_code=warning['code'],
                      source_item_id=warning.get('source_id'),
                      source_scope=warning.get('scope'),
                      source_review_label=WARNING_LABELS.get(warning['code'].split(':')[0], '自動解析の確認事項'))
        region_id = next((r['region_id'] for r in document.get('regions', [])
                          if r['region_id'] == warning.get('source_id')), region_id)
    if region_id:
        result['region_id'] = region_id
    return result


def warning_question_key(nodes, warning, question):
    """Match the same exact source owner used by the editor, never label prefixes."""
    region = next((r for r in question['document'].get('regions', [])
                   if r['region_id'] == warning.get('source_id')), {})
    owner = warning.get('owner') or region.get('assigned_question_key') or warning.get('source_id')
    included = [n for n in nodes if n.get('included', True)]
    exact = next((n for n in included if n['stable_key'] == owner), None)
    if exact:
        return exact['stable_key']
    matches = [n for n in included if n.get('source_draft_stable_key') == owner]
    return matches[0]['stable_key'] if len(matches) == 1 else None
