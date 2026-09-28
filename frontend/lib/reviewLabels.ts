import type { ReviewNode } from "@/types/reviews";

const questionTypes: Record<ReviewNode["node_type"], string> = {
  major_question: "大問",
  subquestion: "小問",
};
const scoreSemantics: Record<ReviewNode["score_semantics"], string> = {
  direct: "この設問に直接配点",
  each_child: "各小問に配点",
  unset: "未設定",
  ambiguous: "要確認",
};
const reviewStates: Record<string, string> = {
  editing: "編集中",
  reviewed: "確認済み",
  unreviewed: "未確認",
  acknowledged: "確認済み",
  resolved: "対応済み",
};
const decisions: Record<string, string> = {
  unreviewed: "未確認",
  use_native: "PDFから読み取った内容を採用",
  use_vision: "画像から読み取った候補を採用",
  teacher_edit: "教師が入力した内容を採用",
  excluded: "問題内容から除外",
  merged_into_text: "問題文に結合",
  accepted_as_evidence: "図の資料として採用",
  needs_correction: "修正が必要",
};

export const questionTypeLabel = (value: ReviewNode["node_type"]) => questionTypes[value];
export const scoreSemanticsLabel = (value: ReviewNode["score_semantics"]) => scoreSemantics[value];
export const reviewStateLabel = (value: string) => reviewStates[value] ?? "確認が必要";
export const reviewDecisionLabel = (value: string) => decisions[value] ?? "確認が必要";
export const reviewContentLabel = (value: string) => ({
  text: "問題文", formula_region: "数式", figure_region: "図", score_expression: "配点の記載",
})[value as "text" | "formula_region" | "figure_region" | "score_expression"] ?? "その他の内容";

const reviewIssues: Record<string, string> = {
  ambiguous_score: "配点の扱いを確認してください",
  score_conflict: "親設問と小問の配点が一致しません",
  score_unset: "配点を確認してください",
  parent_direct_score: "小問を持つ大問の配点方法を確認してください",
  each_child_structural_child: "小問ごとの配点と設問構成を確認してください",
  native_formula_requires_teacher_edit: "数式を原文と照合し、必要なら入力してください",
  formula_unresolved: "数式の読み取り内容を確認してください",
  figure_unresolved: "図の確認結果を選択してください",
  total_unresolved: "合計点を確認してください",
  hierarchy_cycle_or_orphan: "設問の親子関係を確認してください",
  question_number_collision: "設問番号が重複しています",
  stable_key_collision: "既存の設問と重複しています",
  reasoning_output_requires_review: "画像解析による読み取り内容を確認してください",
  native_vision_disagreement: "PDFと画像解析の読み取り結果が異なります",
  score_scope_ambiguous: "配点の対象となる設問を確認してください",
  ambiguous_parent_assignment: "親設問を確認してください",
  duplicate_question_label: "設問番号が重複しています",
  ambiguous_geometric_order: "設問の並び順を確認してください",
  each_child_without_clear_children: "小問の範囲を確認してください",
};

export const reviewIssueLabel = (code: string) => reviewIssues[code.split(":", 1)[0]] ?? "内容を確認してください";

const reviewSaveIssues: Record<string, string> = {
  label_required: "設問名を入力してください。",
  invalid_label: "設問名を確認してください。",
  invalid_text_length: "文字数または入力内容を確認してください。",
  invalid_score: "配点は0以上の数値で入力してください。",
  score_type_mismatch: "配点の扱いと配点を一致させてください。",
  invalid_score_semantics: "配点の扱いを確認してください。",
  invalid_parent: "親設問を確認してください。",
  orphan_node: "親設問が見つかりません。設問の階層を確認してください。",
  cycle: "設問の階層が循環しています。親設問を確認してください。",
  parent_type_mismatch: "設問の階層と種別を確認してください。",
  duplicate_order: "設問の並び順が重複しています。",
  invalid_ordered_content: "問題文・数式・図の内容と順序を確認してください。",
  teacher_transcription_required: "数式の内容を入力してください。",
  merged_formula_text_missing: "問題文に結合した数式を確認してください。",
  source_anchor_changed: "元資料との対応情報に不整合があります。入力欄を編集せず、最新の内容を再読み込みしてください。",
  invalid_source_slice: "元資料との対応情報に不整合があります。入力欄を編集せず、最新の内容を再読み込みしてください。",
  duplicate_region_decision: "数式または図の確認結果が重複しています。",
  formula_content_decision_mismatch: "数式の内容と確認結果を一致させてください。",
};
export const reviewSaveIssueLabel = (code: string) => reviewSaveIssues[code] ?? "保存内容を確認してください。";

const reviewIssueReasons: Record<string, string> = {
  ambiguous_score: "配点の読み取り方が一つに定まりません。原問題用紙と照合してください。",
  score_conflict: "親設問の配点と小問の合計が一致しません。配点欄を確認してください。",
  formula_unresolved: "数式の読み取り結果がまだ確定していません。原問題用紙と照合してください。",
  native_formula_requires_teacher_edit: "PDFから得た数式をそのまま確定できません。正しい式を入力してください。",
  figure_unresolved: "図の内容について確認結果が未選択です。原問題用紙を確認してください。",
  reasoning_output_requires_review: "画像解析の読み取り候補を教師が確認する必要があります。",
  native_vision_disagreement: "PDFと画像解析の候補が異なります。原問題用紙を基準に確認してください。",
  total_unresolved: "設問の配点から合計点を確定できません。各設問の配点を確認してください。",
};

export const reviewIssueReason = (code: string) => reviewIssueReasons[code.split(":", 1)[0]] ?? "自動解析で確認が必要と判定されました。原問題用紙と照合してください。";
