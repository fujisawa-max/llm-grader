import { useMemo, type ReactNode } from "react";
import type { AutomaticNode, Region, ReviewNode } from "@/types/reviews";
import { questionTypeLabel, reviewDecisionLabel, scoreSemanticsLabel } from "@/lib/reviewLabels";
import { MarkdownMathText, MarkdownMathPreview, markdownMathHelp } from "@/components/MarkdownMathText";
import { formulaIsConfirmed, setFormulaConfirmation } from "@/lib/formulaConfirmation";
import { reviewFieldId } from "@/lib/reviewValidation";
import { effectiveQuestionScore } from "@/lib/questionScores";
import { LatexNormalizationControl } from "@/components/LatexNormalizationControl";
import { questionMathSource, questionMathReference } from "@/lib/questionMathSource";
import type { LatexProposal } from "@/lib/api/textTools";

export function NodeEditor({ node, nodes, automatic, regions, readonly, onChange, onParent, onMove, onRegion, activeRegionId, renderEvidence, issues = {}, mathContext, content, contentChanged, onContentChange, onConfirmContent, onCaret }: {
  content: string; contentChanged: boolean;
  onCaret?: (offset:number)=>void;
  onContentChange: (text: string, proposal?: LatexProposal) => void;
  onConfirmContent: (confirm: (node: ReviewNode) => ReviewNode) => void;
  mathContext?: {reviewId: string; revision: number; savedNode?: ReviewNode; authoringTestId?: string};
  node: ReviewNode; nodes: ReviewNode[]; automatic?: AutomaticNode; regions: Region[]; readonly: boolean;
  onChange: (node: ReviewNode) => void; onParent: (key: string | null) => void;
  onMove: (direction: number) => void; onRegion: (region: string) => void;
  activeRegionId?: string; renderEvidence?: (regionId: string) => ReactNode; issues?: Record<string, string[]>;
}) {
  const descendants = new Set([node.stable_key]);
  for (let i = 0; i < nodes.length; i++) for (const n of nodes) if (n.parent_key && descendants.has(n.parent_key)) descendants.add(n.stable_key);
  const modified = useMemo(() => automatic && (JSON.stringify(automatic.ordered_content) !== JSON.stringify(node.ordered_content) ||
    automatic.label.raw !== node.label.raw || automatic.score.points !== node.score_points || automatic.score.semantics !== node.score_semantics), [automatic, node]);
  const childQuestions = nodes.filter(entry => entry.included && entry.parent_key === node.stable_key)
    .sort((left, right) => left.sort_order - right.sort_order);
  const hasChildren = childQuestions.length > 0;
  const derivedScore = useMemo(() => effectiveQuestionScore(node.stable_key, nodes), [node.stable_key, nodes]);
  const contentDiagnostics = useMemo(() => JSON.stringify(node.ordered_content, null, 2), [node.ordered_content]);
  const reviewId = mathContext?.reviewId, revision = mathContext?.revision, savedNode = mathContext?.savedNode;
  const authoringTestId = mathContext?.authoringTestId;
  const source = useMemo(() => {
    const value = reviewId && revision !== undefined ? questionMathSource(reviewId, revision, node, savedNode) : undefined;
    return value && authoringTestId ? {...value, authoringTestId} : value;
  }, [reviewId, revision, savedNode, node, authoringTestId]);
  const confirmContent = () => onConfirmContent(current => {
    const decisions = {...current.formula_decisions};
    for (const region of regions.filter(r => r.region_type === "formula")) {
      const old = decisions[region.region_id] || {decision: "unreviewed"};
      decisions[region.region_id] = setFormulaConfirmation({...old,
        decision: old.decision === "unreviewed" ? "teacher_edit" : old.decision,
        teacher_transcription: old.teacher_transcription ?? region.text_fragments?.map(f => f.native_text).join("\n") ?? "",
      }, "confirmed", "bulk");
    }
    return {...current, formula_decisions: decisions};
  });
  const fieldIssues = (key: string) => issues[key] || [];
  const errors = (key: string) => fieldIssues(key).map((issue, index) => <small key={index} className="review-field-error" role="alert">{issue}</small>);
  const needsCheck = (key: string) => fieldIssues(key).length ? <span className="review-required">要確認</span> : null;
  return <article className="panel review-field-target" id={reviewFieldId(node.stable_key, "node")} aria-label="選択問題エディタ">
    <h3>{node.label.raw || "名称未設定の設問"} {(modified || contentChanged) && <span className="badge badge-rubric_review">自動解析から変更あり</span>}</h3>
    {errors("node")}
    <fieldset disabled={readonly} className="review-fields"><legend>設問の編集</legend>
      <label id={reviewFieldId(node.stable_key, "label")} className={fieldIssues("label").length ? "review-field-target has-error" : "review-field-target"}>設問番号・見出し <span className="review-required" aria-label="必須">*</span>{needsCheck("label")}<input maxLength={200} value={node.label.raw} aria-invalid={!!fieldIssues("label").length} onChange={e => onChange({ ...node, label: { raw: e.target.value, normalized: e.target.value } })} />{errors("label")}</label>
      <label><input type="checkbox" checked={node.included} onChange={e => onChange({ ...node, included: e.target.checked })} /> この設問を含める（チェックを外すと除外）</label>
      <label id={reviewFieldId(node.stable_key, "parent")} className={fieldIssues("parent").length ? "review-field-target has-error" : "review-field-target"}>設問の階層{needsCheck("parent")}<select aria-label="設問の階層" aria-invalid={!!fieldIssues("parent").length} value={node.parent_key || ""} onChange={e => onParent(e.target.value || null)}>
        <option value="">大問（最上位）</option>{nodes.filter(n => !descendants.has(n.stable_key)).map(n => <option key={n.stable_key} value={n.stable_key}>{n.label.raw || "名称未設定の設問"}の小問</option>)}
      </select>{errors("parent")}</label><p>種別: {questionTypeLabel(node.node_type)}（親設問に連動）</p>
      <div className="review-toolbar"><button type="button" onClick={() => onMove(-1)}>上へ移動</button><button type="button" onClick={() => onMove(1)}>下へ移動</button></div>
      <label id={reviewFieldId(node.stable_key, "score_method")}>配点の扱い<select value={node.score_semantics} onChange={e => {
        const semantics = e.target.value as ReviewNode["score_semantics"];
        onChange({ ...node, score_semantics: semantics, score_points: semantics === "direct" ? node.score_points : null });
      }}>
        {node.score_semantics === "each_child" && <option value="each_child" disabled>旧設定（同じ配点を各小問に適用）</option>}
        {node.score_semantics === "ambiguous" && <option value="ambiguous" disabled>要確認（自動解析）</option>}
        {node.score_semantics === "direct" && hasChildren
          ? <option value="direct" disabled>この問題に直接配点（小問があるため利用不可）</option>
          : !hasChildren && <option value="direct">この問題に直接配点</option>}
        {(hasChildren || node.score_semantics === "sum_children") && <option value="sum_children" disabled={!hasChildren}>小問の個別配点の合計</option>}
        <option value="unset">未設定</option>
      </select></label>
      {node.score_semantics === "sum_children" ? <div id={reviewFieldId(node.stable_key, "score")} className={fieldIssues("score").length ? "review-field-target derived-score has-error" : "review-field-target derived-score"} aria-invalid={!!fieldIssues("score").length}>
        <strong>配点: {derivedScore.complete ? `${derivedScore.points}点` : "未確定"}</strong>
        <p className="muted">小問の個別配点から自動計算されます。</p>
        {!derivedScore.complete && <p>{derivedScore.knownCount > 0 ? `小問合計（設定済み分）: ${derivedScore.knownPoints}点。` : "小問の配点がまだ設定されていません。"}{derivedScore.missingLabels.length > 0 && ` 未設定または要確認: ${derivedScore.missingLabels.join("、")}`}</p>}
        {errors("score")}
      </div> : node.score_semantics === "unset" ? <div id={reviewFieldId(node.stable_key, "score")} className="review-field-target"><strong>配点: 未設定</strong>{hasChildren && <p className="muted">小問に任せる設定ではありません。配点方法を選んでください。</p>}{errors("score")}</div>
        : node.score_semantics === "each_child" ? <div id={reviewFieldId(node.stable_key, "score")} className="review-field-target legacy-score"><strong>旧設定の配点: {node.score_points ?? "未設定"}点ずつ</strong><p className="muted">この修正版では、設定済み点数を各小問へ同じ点数として適用します。新しい方式へ変更する場合は上の選択欄から選んでください。</p>{errors("score")}</div>
          : <label id={reviewFieldId(node.stable_key, "score")} className={fieldIssues("score").length ? "review-field-target has-error" : "review-field-target"}>配点{node.score_semantics === "direct" ? <span className="review-required" aria-label="必須">*</span> : null}{needsCheck("score")}<input type="number" min="0" max="1000000000" step="any" disabled={node.score_semantics === "ambiguous" || hasChildren} value={node.score_points ?? ""} aria-invalid={!!fieldIssues("score").length}
            onChange={e => onChange({ ...node, score_points: e.target.value === "" ? null : Number(e.target.value) })} />{hasChildren && <p className="muted">小問がある設問は、この画面では直接配点できません。小問の個別配点を合計する方式を選んでください。</p>}{errors("score")}</label>}
      {automatic && <p className="muted">自動解析による配点: {scoreSemanticsLabel(automatic.score.semantics)} {automatic.score.points ?? "—"}</p>}
      <section id={reviewFieldId(node.stable_key, "content")} className={fieldIssues("content").length ? "review-content-item has-error" : "review-content-item"} data-content-type="question-content" aria-label="問題文の編集">
        {Object.keys(issues).filter(key => key.startsWith("text:") || key.startsWith("formula:")).map(key =>
          <span key={key} id={reviewFieldId(node.stable_key, key)} />)}
        <label>問題文<textarea aria-label="問題文" maxLength={20000} rows={14} value={content} aria-invalid={!!fieldIssues("content").length}
          onSelect={event=>onCaret?.(event.currentTarget.selectionStart)} onChange={event => onContentChange(event.target.value)} /></label>
        {errors("content")}
        <small className="math-help">{markdownMathHelp}</small><MarkdownMathPreview source={content} />
        {mathContext && <><LatexNormalizationControl key={`${node.stable_key}:${mathContext.revision}`} text={content}
          contextType="question" contextLabel={node.label.raw} source={source} disabled={readonly || !source}
          onApply={onContentChange} />
          {!source && <p className="muted" role="status">{!mathContext.savedNode || JSON.stringify(node.ordered_content.map(questionMathReference)) !== JSON.stringify(mathContext.savedNode.ordered_content.map(questionMathReference))
            ? "構成の変更を保存すると、元PDFとの対応を確認して数式OCRを利用できます。"
            : "この設問には利用できる元PDFの対応情報がありません。"}</p>}</>}
        {regions.some(r => r.region_type === "formula") && <div className="review-toolbar">
          <button type="button" data-review-confirm-content onClick={confirmContent}>問題文を確認</button>
          <span className="muted">{!contentChanged && regions.filter(r => r.region_type === "formula").every(r => formulaIsConfirmed(node.formula_decisions[r.region_id]))
            ? "元資料との照合済み" : "元資料と問題文を照合してください。編集後は再確認が必要です。"}</span>
        </div>}
        {Object.entries(issues).filter(([key]) => key.startsWith("text:") || key.startsWith("formula:")).flatMap(([key, messages]) =>
          messages.map((message, index) => <p role="alert" key={`${key}:${index}`}>{message}</p>))}
      </section>
      {node.ordered_content.filter(item => item.type === "figure_region").map(item => {
        const id = String("region_id" in item ? item.region_id : ""), decision = node.figure_decisions[id];
        return <section id={reviewFieldId(node.stable_key, `figure:${id}`)} key={id} className="review-content-item" data-content-type="figure" data-region-id={id}>
          <h4>図</h4><p className="muted">原問題用紙の図を確認し、確認結果を選択してください。</p>
          <button type="button" onClick={() => onRegion(id)}>図の原文と確認方法を表示</button>
          <p>{decision?.decision ? reviewDecisionLabel(decision.decision) : "要確認"}</p>
          {errors(`figure:${id}`)}{activeRegionId === id && renderEvidence?.(id)}
        </section>;
      })}
      <details><summary>出典・読み取り構造の診断</summary>
        <pre>{contentDiagnostics}</pre>
        {regions.filter(r => r.region_type === "formula").map(r => <section key={r.region_id}>
          <button type="button" onClick={() => onRegion(r.region_id)}>元資料を確認</button>
          {activeRegionId === r.region_id && renderEvidence?.(r.region_id)}
        </section>)}
      </details>
    </fieldset>
    <details><summary>保存済みの問題文を表示</summary><MarkdownMathText source={node.body_text} /></details>
    {automatic && <details><summary>自動解析された問題文を表示</summary><MarkdownMathText source={automatic.body_text} /></details>}
    <details><summary>技術情報</summary><code>{node.stable_key}</code></details>
  </article>;
}
