import type { AutomaticNode, Region, ReviewNode } from "@/types/reviews";
import { questionTypeLabel, reviewContentLabel, scoreSemanticsLabel } from "@/lib/reviewLabels";

export function NodeEditor({ node, nodes, automatic, regions, readonly, onChange, onParent, onMove, onRegion }: {
  node: ReviewNode; nodes: ReviewNode[]; automatic?: AutomaticNode; regions: Region[]; readonly: boolean;
  onChange: (node: ReviewNode) => void; onParent: (key: string | null) => void;
  onMove: (direction: number) => void; onRegion: (region: string) => void;
}) {
  const descendants = new Set([node.stable_key]);
  for (let i = 0; i < nodes.length; i++) for (const n of nodes) if (n.parent_key && descendants.has(n.parent_key)) descendants.add(n.stable_key);
  const modified = automatic && (JSON.stringify(automatic.ordered_content) !== JSON.stringify(node.ordered_content) ||
    automatic.label.raw !== node.label.raw || automatic.score.points !== node.score_points || automatic.score.semantics !== node.score_semantics);
  return <article className="panel" aria-label="選択問題エディタ">
    <h3>{node.label.raw || "名称未設定の設問"} {modified && <span className="badge badge-rubric_review">自動解析から変更あり</span>}</h3>
    <fieldset disabled={readonly} className="review-fields"><legend>設問の編集</legend>
      <label>設問番号・見出し<input maxLength={200} value={node.label.raw} onChange={e => onChange({ ...node, label: { raw: e.target.value, normalized: e.target.value } })} /></label>
      <label><input type="checkbox" checked={node.included} onChange={e => onChange({ ...node, included: e.target.checked })} /> この設問を含める（チェックを外すと除外）</label>
      <label>設問の階層<select aria-label="設問の階層" value={node.parent_key || ""} onChange={e => onParent(e.target.value || null)}>
        <option value="">大問（最上位）</option>{nodes.filter(n => !descendants.has(n.stable_key)).map(n => <option key={n.stable_key} value={n.stable_key}>{n.label.raw || "名称未設定の設問"}の小問</option>)}
      </select></label><p>種別: {questionTypeLabel(node.node_type)}（親設問に連動）</p>
      <div className="review-toolbar"><button onClick={() => onMove(-1)}>上へ移動</button><button onClick={() => onMove(1)}>下へ移動</button></div>
      <label>配点の扱い<select value={node.score_semantics} onChange={e => {
        const semantics = e.target.value as ReviewNode["score_semantics"];
        onChange({ ...node, score_semantics: semantics, score_points: semantics === "unset" ? null : node.score_points });
      }}>{(["direct", "each_child", "unset", "ambiguous"] as const).map(s => <option key={s} value={s}>{scoreSemanticsLabel(s)}</option>)}</select></label>
      <label>配点<input type="number" min="0" max="1000000000" step="any" disabled={node.score_semantics === "unset"} value={node.score_points ?? ""}
        onChange={e => onChange({ ...node, score_points: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      {automatic && <p className="muted">自動解析による配点: {scoreSemanticsLabel(automatic.score.semantics)} {automatic.score.points ?? "—"}</p>}
      <h4>問題文と資料</h4>
      {node.ordered_content.map((item, index) => {
        if (item.type === "text" && typeof item.text === "string") return <label key={index}>問題文 {index + 1}<textarea maxLength={20000} value={item.text}
          onChange={e => onChange({ ...node, ordered_content: node.ordered_content.map((i, at) => at === index ? { ...i, text: e.target.value } : i) })} /></label>;
        if ((item.type === "formula_region" || item.type === "figure_region") && typeof item.region_id === "string") {
          const regionId = item.region_id;
          return <button type="button" className="review-anchor" data-region-id={regionId} key={index} onClick={() => onRegion(regionId)}>{reviewContentLabel(item.type)} {index + 1} · 読み取り結果を比較</button>;
        }
        if (item.type === "score_expression") return <div className="review-anchor" key={index}>配点の記載: {typeof item.text === "string" ? item.text : "原文を確認してください"}</div>;
        return <div className="notice" key={index}>表示できない内容があります。<details><summary>技術情報</summary><code>{item.type}</code></details></div>;
      })}
    </fieldset>
    {/* Evidence navigation stays available while reading historical revisions. */}
    <div className="review-toolbar">{regions.map((r, index) => <button key={r.region_id} data-region-id={r.region_id} onClick={() => onRegion(r.region_id)}>{r.region_type === "formula" ? "数式" : "図"} {index + 1}を確認</button>)}</div>
    <details><summary>保存済みの問題文を表示</summary><pre>{node.body_text}</pre></details>
    {automatic && <details><summary>自動解析された問題文を表示</summary><pre>{automatic.body_text}</pre></details>}
    <details><summary>技術情報</summary><code>{node.stable_key}</code></details>
  </article>;
}
