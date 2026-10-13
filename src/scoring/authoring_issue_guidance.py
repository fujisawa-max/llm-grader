"""Teacher-facing explanations for existing authoring blockers; no decisions."""


def issue_guidance(snapshot, issue, total):
    key, code = issue.get('question_key'), issue.get('code')
    node = next((n for n in snapshot['nodes'] if n['stable_key'] == key), {})
    criteria = snapshot['rubrics'].get(key, [])
    labels = {'question': '本文を修正', 'answer': '模範解答を確認',
              'rubric': '採点基準を修正', 'source': '出典を確認', 'metadata': '合計点を修正'}
    result = {**issue, 'action_label': labels.get(issue['section'], '内容を確認'),
              'expected_state': '該当する編集欄で内容を確認・修正し、保存してください。'}
    if str(code).startswith('grading_'):
        result.update({k: issue[k] for k in ('action_label', 'expected_state') if k in issue})
        if issue.get('criterion_id'):
            criterion = next((c for c in criteria if c.get('id') == issue['criterion_id']), {})
            result['current_state'] = f"配点: {criterion.get('points', '未設定')}点 / 得点段階: {len(criterion.get('levels') or [])}件"
    elif code == 'question_source_warning':
        result.update(action_label='出典確認へ',
                      current_state=f"確認事項 {issue.get('source_review_index', '')}: {issue.get('source_review_label', '自動解析の確認事項')} / 未確認",
                      expected_state=(issue.get('source_review_explanation', '')+' ' if issue.get('source_review_explanation') else '')+'元PDFと該当項目を照合し、正しければ確認状態を「確認済み」にしてください。内容が違う場合は修正して「対応済み」にしてください。')
    elif code in {'question_formula_review', 'question_figure_review'}:
        result.update(action_label='出典確認へ', current_state='数式の確認が未完了' if code == 'question_formula_review' else '図の確認結果が未選択',
                      expected_state='元PDFと読み取り内容を照合し、正しければ「問題文を確認」を押してください。' if code == 'question_formula_review' else '元PDFの図を確認し、図の確認結果を選択してください。')
    elif issue.get('correction_type') == 'text_source_review':
        result.update(action_label='本文と出典を確認', current_state='編集本文と出典付き本文に差異があります。',
                      expected_state='元PDFと編集本文を照合し、数式や出典付き読み取り項目の対応を修正して保存してください。警告の確認だけでは本文の差異は解消されません。')
    elif code == 'rubric_points':
        points = node.get('score_points')
        result.update(current_state=f"設問の配点: {points if points is not None else '未設定'}点 / 採点基準の合計: {sum(c['points'] for c in criteria)}点",
                      expected_state=f'採点基準の合計を{points}点にしてください。' if points is not None else '先に設問の配点を設定してください。')
    elif code == 'rubric_review':
        pending = next((c for c in criteria if c.get('id') == issue.get('criterion_id')), {})
        states = []
        if pending.get('grouping_confirmed') is False:
            states.append('統合内容が未確認')
        if pending.get('points_conflict') and not pending.get('points_confirmed'):
            states.append('配点が未確認')
        result.update(current_state=' / '.join(states), expected_state='対象基準の本文を確認し、「この採点基準を確認」を押してください。配点が未確認の場合は点数を入力してください。')
    elif code == 'question_score':
        result.update(action_label='配点を修正', current_state=f"設問の配点: {node.get('score_points') if node.get('score_points') is not None else '未設定'}",
                      expected_state='設問設定で正しい配点を入力してください。')
    elif code == 'answer_missing':
        result.update(current_state='模範解答本文・確認済みの図が未登録', expected_state='模範解答本文を入力するか、正答となる図を確認して使用してください。')
    elif code == 'answer_classification':
        result.update(current_state='候補の分類が未確認', expected_state='候補の扱い・対応する設問・解答の種類を修正するか、「候補の分類を確認」で分類を確認してください。分類に関する変更は教師の確認として記録されます。')
    elif code in {'answer_unassigned', 'rubric_unassigned', 'rubric_recovery'}:
        exclude = '無視' if code == 'rubric_recovery' else '不要として除外'
        result.update(current_state='候補の対応先が未設定', expected_state=f'この候補を対応する設問へ割り当てるか、内容を確認して「{exclude}」を選んでください。')
    elif code == 'test_total':
        result.update(current_state=f"テストの合計点: {snapshot['metadata']['total_points']}点 / 採点対象の配点合計: {total}点",
                      expected_state='設問の配点とテストの合計点を確認して一致させてください。')
    elif code == 'formal_review_stale':
        result.update(current_state='下書きの作成後に正式内容が変更されています。',
                      expected_state='変更された正式内容と元PDF・本文・図の対応を確認し、「保存済みレビューを取り込む」で出典付きレビューを更新してください。')
    elif issue['section'] == 'source' or issue.get('field') == 'source':
        result.update(current_state='元資料との対応が未確認または無効', expected_state='使用しているPDFと本文・図の対応箇所を確認してください。必要なら資料を明示的に再解析してください。')
    return result
