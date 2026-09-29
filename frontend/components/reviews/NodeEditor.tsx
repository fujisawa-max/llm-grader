import { useRef, useState, type ReactNode } from "react";
import type { AutomaticNode, ContentItem, Region, ReviewNode } from "@/types/reviews";
import { questionTypeLabel, reviewContentLabel, reviewDecisionLabel, scoreSemanticsLabel } from "@/lib/reviewLabels";
import { MathPreview } from "@/components/MathText";
import { MarkdownMathText, MarkdownMathPreview, markdownMathHelp } from "@/components/MarkdownMathText";
import { inlineFormulaSource } from "@/lib/formulaMerge";
import { mergeContiguousText } from "@/lib/reviewTextMerge";
import { reviewFieldId } from "@/lib/reviewValidation";

export function NodeEditor({ node, nodes, automatic, regions, readonly, onChange, onParent, onMove, onRegion, activeRegionId, renderEvidence, issues = {} }: {
  node: ReviewNode; nodes: ReviewNode[]; automatic?: AutomaticNode; regions: Region[]; readonly: boolean;
  onChange: (node: ReviewNode) => void; onParent: (key: string | null) => void;
  onMove: (direction: number) => void; onRegion: (region: string) => void;
  activeRegionId?: string; renderEvidence?: (regionId: string) => ReactNode; issues?: Record<string, string[]>;
}) {
  const descendants = new Set([node.stable_key]);
  for (let i = 0; i < nodes.length; i++) for (const n of nodes) if (n.parent_key && descendants.has(n.parent_key)) descendants.add(n.stable_key);
  const modified = automatic && (JSON.stringify(automatic.ordered_content) !== JSON.stringify(node.ordered_content) ||
    automatic.label.raw !== node.label.raw || automatic.score.points !== node.score_points || automatic.score.semantics !== node.score_semantics);
  const regionById = new Map(regions.map(region => [region.region_id, region]));
  const mergeFocusIndex = useRef<number | null>(null);
  const [mergeSelectionState, setMergeSelectionState] = useState<{
    nodeKey: string; active: boolean; indices: number[];
  }>({ nodeKey: node.stable_key, active: false, indices: [] });
  const mergeMode = mergeSelectionState.nodeKey === node.stable_key && mergeSelectionState.active;
  const selectedMergeIndices = mergeSelectionState.nodeKey === node.stable_key ? mergeSelectionState.indices : [];
  const clearMergeSelection = () => setMergeSelectionState(state => state.nodeKey === node.stable_key
    ? { ...state, indices: [] } : state);
  const updateItems = (items: ContentItem[]) => onChange({ ...node, ordered_content: items.map((item, order) => ({ ...item, order })) });
  const addText = () => { clearMergeSelection(); updateItems([...node.ordered_content, { type: "text", order: node.ordered_content.length, text: "" }]); };
  const removeText = (index: number, value: string) => {
    if (value.trim() && !window.confirm("この問題文を削除しますか？")) return;
    clearMergeSelection();
    updateItems(node.ordered_content.filter((_, at) => at !== index));
  };
  const moveItem = (index: number, delta: number) => {
    const next = index + delta;
    if (next < 0 || next >= node.ordered_content.length) return;
    clearMergeSelection();
    const copy = [...node.ordered_content]; [copy[index], copy[next]] = [copy[next], copy[index]];
    updateItems(copy);
  };
  const mergeTextItems = (indices: number[]) => {
    const firstIndex = [...new Set(indices)].sort((a, b) => a - b)[0];
    const mergedItems = mergeContiguousText(node.ordered_content, indices);
    if (!mergedItems) return;
    mergeFocusIndex.current = firstIndex;
    updateItems(mergedItems);
    setMergeSelectionState({ nodeKey: node.stable_key, active: false, indices: [] });
  };
  const mergeText = (index: number) => mergeTextItems([index - 1, index]);
  const selectedMergeContiguous = selectedMergeIndices.length >= 2 && selectedMergeIndices.every((index, at) =>
    at === 0 || index === selectedMergeIndices[at - 1] + 1);
  const selectedMergeLength = selectedMergeIndices.reduce((total, index) => {
    const item = node.ordered_content[index];
    return total + (item?.type === "text" && typeof item.text === "string" ? item.text.length : 0);
  }, 0);
  const canMergeSelection = selectedMergeContiguous && selectedMergeLength <= 20000 &&
    selectedMergeIndices.every(index => node.ordered_content[index]?.type === "text");
  const removeFormula = (index: number, regionId: string) => {
    if (!window.confirm("この数式を問題内容から削除しますか？ 元の問題用紙は残ります。")) return;
    clearMergeSelection();
    onChange({ ...node,
      ordered_content: node.ordered_content.filter((_, at) => at !== index).map((item, order) => ({ ...item, order })),
      formula_decisions: { ...node.formula_decisions,
        [regionId]: { ...node.formula_decisions[regionId], decision: "excluded" } },
    });
  };
  const mergeFormula = (index: number, regionId: string, source: string) => {
    const previous = node.ordered_content[index - 1];
    const formula = node.ordered_content[index];
    const latex = inlineFormulaSource(source);
    if (previous?.type !== "text" || typeof previous.text !== "string" ||
        formula?.type !== "formula_region" || !latex || previous.text.length + latex.length + 2 > 20000) return;
    clearMergeSelection();
    const anchor = Object.fromEntries(Object.entries(formula).filter(([key]) => key !== "order"));
    const segments = [
      ...(Array.isArray(previous.merged_source_segments) ? previous.merged_source_segments : []),
      anchor,
    ];
    const merged = { ...previous, text: `${previous.text}$${latex}$`, merged_source_segments: segments };
    mergeFocusIndex.current = index - 1;
    onChange({ ...node,
      ordered_content: node.ordered_content.flatMap((item, at) => at === index - 1 ? [merged] : at === index ? [] : [item])
        .map((item, order) => ({ ...item, order })),
      formula_decisions: { ...node.formula_decisions,
        [regionId]: { ...node.formula_decisions[regionId], decision: "merged_into_text", teacher_transcription: latex } },
    });
  };
  const fieldIssues = (key: string) => issues[key] || [];
  const errors = (key: string) => fieldIssues(key).map((issue, index) => <small key={index} className="review-field-error" role="alert">{issue}</small>);
  const needsCheck = (key: string) => fieldIssues(key).length ? <span className="review-required">要確認</span> : null;
  let textNumber = 0, formulaNumber = 0, figureNumber = 0;
  return <article className="panel review-field-target" id={reviewFieldId(node.stable_key, "node")} aria-label="選択問題エディタ">
    <h3>{node.label.raw || "名称未設定の設問"} {modified && <span className="badge badge-rubric_review">自動解析から変更あり</span>}</h3>
    {errors("node")}
    <fieldset disabled={readonly} className="review-fields"><legend>設問の編集</legend>
      <label id={reviewFieldId(node.stable_key, "label")} className={fieldIssues("label").length ? "review-field-target has-error" : "review-field-target"}>設問番号・見出し <span className="review-required" aria-label="必須">*</span>{needsCheck("label")}<input maxLength={200} value={node.label.raw} aria-invalid={!!fieldIssues("label").length} onChange={e => onChange({ ...node, label: { raw: e.target.value, normalized: e.target.value } })} />{errors("label")}</label>
      <label><input type="checkbox" checked={node.included} onChange={e => onChange({ ...node, included: e.target.checked })} /> この設問を含める（チェックを外すと除外）</label>
      <label id={reviewFieldId(node.stable_key, "parent")} className={fieldIssues("parent").length ? "review-field-target has-error" : "review-field-target"}>設問の階層{needsCheck("parent")}<select aria-label="設問の階層" aria-invalid={!!fieldIssues("parent").length} value={node.parent_key || ""} onChange={e => onParent(e.target.value || null)}>
        <option value="">大問（最上位）</option>{nodes.filter(n => !descendants.has(n.stable_key)).map(n => <option key={n.stable_key} value={n.stable_key}>{n.label.raw || "名称未設定の設問"}の小問</option>)}
      </select>{errors("parent")}</label><p>種別: {questionTypeLabel(node.node_type)}（親設問に連動）</p>
      <div className="review-toolbar"><button type="button" onClick={() => onMove(-1)}>上へ移動</button><button type="button" onClick={() => onMove(1)}>下へ移動</button></div>
      <label>配点の扱い<select value={node.score_semantics} onChange={e => {
        const semantics = e.target.value as ReviewNode["score_semantics"];
        onChange({ ...node, score_semantics: semantics, score_points: semantics === "unset" ? null : node.score_points });
      }}>{(["direct", "each_child", "unset", "ambiguous"] as const).map(s => <option key={s} value={s}>{scoreSemanticsLabel(s)}</option>)}</select></label>
      <label id={reviewFieldId(node.stable_key, "score")} className={fieldIssues("score").length ? "review-field-target has-error" : "review-field-target"}>配点{node.score_semantics === "direct" || node.score_semantics === "each_child" ? <span className="review-required" aria-label="必須">*</span> : null}{needsCheck("score")}<input type="number" min="0" max="1000000000" step="any" disabled={node.score_semantics === "unset"} value={node.score_points ?? ""} aria-invalid={!!fieldIssues("score").length}
        onChange={e => onChange({ ...node, score_points: e.target.value === "" ? null : Number(e.target.value) })} />{errors("score")}</label>
      {automatic && <p className="muted">自動解析による配点: {scoreSemanticsLabel(automatic.score.semantics)} {automatic.score.points ?? "—"}</p>}
      <h4>問題文・数式・図（原文の読み順）</h4>
      <div className="review-toolbar">
        <button type="button" onClick={() => setMergeSelectionState({
          nodeKey: node.stable_key, active: !mergeMode, indices: [],
        })}>{mergeMode ? "一括結合をキャンセル" : "問題文をまとめて結合"}</button>
        {mergeMode && <>
          <span className="muted">連続する問題文を2件以上選択してください。数式・図をまたぐ結合はできません。</span>
          <button type="button" disabled={!canMergeSelection} onClick={() => mergeTextItems(selectedMergeIndices)}>
            選択した{selectedMergeIndices.length}件を結合
          </button>
        </>}
      </div>
      {mergeMode && selectedMergeIndices.length > 0 && !canMergeSelection && <p className="warn" role="status">
        {selectedMergeIndices.length < 2 ? "問題文を2件以上選択してください。"
          : !selectedMergeContiguous ? "連続する問題文だけを結合できます。数式や図をまたぐ選択を外してください。"
            : "結合後の問題文が文字数上限を超えます。選択数を減らしてください。"}
      </p>}
      {node.ordered_content.map((item, index) => {
        if (item.type === "text" && typeof item.text === "string") {
          const number = ++textNumber, key = `text:${index}`;
          const preceding = node.ordered_content[index - 1];
          const precedingText = preceding?.type === "text" && typeof preceding.text === "string" ? preceding.text : null;
          const canMerge = precedingText !== null;
          const mergeTooLong = precedingText !== null && precedingText.length + item.text.length > 20000;
          return <section className={fieldIssues(key).length ? "review-content-item has-error" : "review-content-item"} id={reviewFieldId(node.stable_key, key)} key={`text-${index}`} data-content-type="text">
            {mergeMode && <label className="review-merge-select"><input type="checkbox" aria-label={`まとめて結合する 問題文 ${number}`}
              checked={selectedMergeIndices.includes(index)} onChange={event => setMergeSelectionState({
                nodeKey: node.stable_key, active: true,
                indices: event.target.checked
                  ? [...new Set([...selectedMergeIndices, index])].sort((a, b) => a - b)
                  : selectedMergeIndices.filter(selectedIndex => selectedIndex !== index),
              })} />この問題文を一括結合に含める</label>}
            <label>問題文 {number} <span className="review-required" aria-label="必須">*</span>{needsCheck(key)}<textarea ref={element => { if (element && mergeFocusIndex.current === index) { element.focus(); mergeFocusIndex.current = null; } }} aria-label={`問題文 ${number}`} maxLength={20000} value={item.text} aria-invalid={!!fieldIssues(key).length}
              onChange={e => updateItems(node.ordered_content.map((value, at) => at === index ? { ...value, text: e.target.value } : value))} /></label>
            {errors(key)}<small className="math-help">{markdownMathHelp}</small><MarkdownMathPreview source={item.text} />
            <div className="review-content-actions"><button type="button" onClick={() => moveItem(index, -1)} disabled={index === 0}>上へ</button><button type="button" onClick={() => moveItem(index, 1)} disabled={index === node.ordered_content.length - 1}>下へ</button>{canMerge && <button type="button" onClick={() => mergeText(index)} disabled={mergeTooLong} title={mergeTooLong ? "結合後の問題文が文字数上限を超えます" : undefined}>上の問題文とマージ</button>}<button type="button" onClick={() => removeText(index, String(item.text))}>問題文 {number}を削除</button></div>
          </section>;
        }
        if ((item.type === "formula_region" || item.type === "figure_region") && typeof item.region_id === "string") {
          const regionId = item.region_id, formula = item.type === "formula_region";
          const number = formula ? ++formulaNumber : ++figureNumber;
          const region = regionById.get(regionId);
          const decision = formula ? node.formula_decisions[regionId] : node.figure_decisions[regionId];
          const source = decision?.teacher_transcription ?? region?.text_fragments?.map(fragment => fragment.native_text).join("\n") ?? "";
          const preceding = node.ordered_content[index - 1];
          const precedingText = preceding?.type === "text" && typeof preceding.text === "string" ? preceding.text : null;
          const latex = inlineFormulaSource(String(source));
          const mergeDisabled = !latex || (decision?.decision === "use_vision" && !decision.teacher_transcription) ||
            (precedingText !== null && precedingText.length + latex.length + 2 > 20000);
          const key = `${formula ? "formula" : "figure"}:${regionId}`;
          return <section className={fieldIssues(key).length ? "review-content-item has-error" : "review-content-item"} id={reviewFieldId(node.stable_key, key)} key={regionId} data-content-type={formula ? "formula" : "figure"} data-region-id={regionId}>
            <div className="review-content-heading"><h5>{reviewContentLabel(item.type)} {number}</h5><span className={decision?.decision && decision.decision !== "unreviewed" ? "review-confirmed" : "review-needs-check"}>{decision?.decision && decision.decision !== "unreviewed" ? reviewDecisionLabel(decision.decision) : "要確認"}</span>{needsCheck(key)}</div>
            {formula ? <><label>数式 {number}のLaTeX<textarea aria-label={`数式 ${number}のLaTeX`} maxLength={20000} value={String(source)} aria-invalid={!!fieldIssues(key).length} onFocus={() => onRegion(regionId)} onChange={e => onChange({ ...node, formula_decisions: { ...node.formula_decisions, [regionId]: { ...decision, decision: "teacher_edit", teacher_transcription: e.target.value } } })} /></label>{errors(key)}<MathPreview source={String(source)} mathOnly /></> : <p className="muted">原問題用紙の図を確認し、確認結果を選択してください。</p>}
            <button type="button" onClick={() => onRegion(regionId)}>{formula ? "読み取り候補と確認方法を表示" : "図の原文と確認方法を表示"}</button>
            <div className="review-content-actions"><button type="button" onClick={() => moveItem(index, -1)} disabled={index === 0}>上へ</button><button type="button" onClick={() => moveItem(index, 1)} disabled={index === node.ordered_content.length - 1}>下へ</button></div>
            {formula && <div className="review-content-actions">
              {precedingText !== null && <button type="button" onClick={() => mergeFormula(index, regionId, String(source))} disabled={mergeDisabled}
                title={mergeDisabled ? "数式の内容を確認・修正してから結合してください" : "数式を直前の問題文にインライン数式として結合します"}>上の問題文とマージ</button>}
              <button type="button" onClick={() => removeFormula(index, regionId)}>数式 {number}を削除</button>
            </div>}
            {activeRegionId === regionId && renderEvidence?.(regionId)}
          </section>;
        }
        if (item.type === "score_expression") return <div className="review-content-item" key={`score-${index}`}>配点の記載: {typeof item.text === "string" ? item.text : "原文を確認してください"}</div>;
        return <div className="notice" key={`other-${index}`}>表示できない内容があります。<details><summary>技術情報</summary><code>{item.type}</code></details></div>;
      })}
      <button type="button" className="button secondary" onClick={addText}>＋ 問題文を追加</button>
    </fieldset>
    <details><summary>保存済みの問題文を表示</summary><MarkdownMathText source={node.body_text} /></details>
    {automatic && <details><summary>自動解析された問題文を表示</summary><MarkdownMathText source={automatic.body_text} /></details>}
    <details><summary>技術情報</summary><code>{node.stable_key}</code></details>
  </article>;
}
