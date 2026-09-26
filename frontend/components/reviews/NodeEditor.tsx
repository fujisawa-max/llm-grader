import type { AutomaticNode, Region, ReviewNode } from "@/types/reviews";

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
    <h3>{node.stable_key} {modified && <span className="badge badge-rubric_review">Modified</span>}</h3>
    <fieldset disabled={readonly} className="review-fields"><legend>Question editor</legend>
      <label>Label<input maxLength={200} value={node.label.raw} onChange={e => onChange({ ...node, label: { raw: e.target.value, normalized: e.target.value } })} /></label>
      <label><input type="checkbox" checked={node.included} onChange={e => onChange({ ...node, included: e.target.checked })} /> 含める（外すと除外扱い）</label>
      <label>Parent / hierarchy<select aria-label="Parent" value={node.parent_key || ""} onChange={e => onParent(e.target.value || null)}>
        <option value="">Top level — major question</option>{nodes.filter(n => !descendants.has(n.stable_key)).map(n => <option key={n.stable_key} value={n.stable_key}>{n.stable_key} {n.label.raw}</option>)}
      </select></label><p>Type: {node.node_type}（parentに連動）</p>
      <div className="review-toolbar"><button onClick={() => onMove(-1)}>Move up</button><button onClick={() => onMove(1)}>Move down</button></div>
      <label>Score semantics<select value={node.score_semantics} onChange={e => {
        const semantics = e.target.value as ReviewNode["score_semantics"];
        onChange({ ...node, score_semantics: semantics, score_points: semantics === "unset" ? null : node.score_points });
      }}>{["direct", "each_child", "unset", "ambiguous"].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Score points<input type="number" min="0" max="1000000000" step="any" disabled={node.score_semantics === "unset"} value={node.score_points ?? ""}
        onChange={e => onChange({ ...node, score_points: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      {automatic && <p className="muted">Automatic: {automatic.score.semantics} {automatic.score.points ?? "—"}</p>}
      <h4>Ordered content</h4>
      {node.ordered_content.map((item, index) => {
        if (item.type === "text" && typeof item.text === "string") return <label key={index}>Text {index + 1}<textarea maxLength={20000} value={item.text}
          onChange={e => onChange({ ...node, ordered_content: node.ordered_content.map((i, at) => at === index ? { ...i, text: e.target.value } : i) })} /></label>;
        if ((item.type === "formula_region" || item.type === "figure_region") && typeof item.region_id === "string") {
          const regionId = item.region_id;
          return <button type="button" className="review-anchor" key={index} onClick={() => onRegion(regionId)}>{item.type === "formula_region" ? "[Formula]" : "[Figure]"} {regionId} · evidenceを比較</button>;
        }
        if (item.type === "score_expression") return <div className="review-anchor" key={index}>[Score anchor] {typeof item.text === "string" ? item.text : "配点の原文"}</div>;
        return <div className="notice" key={index}>Unsupported content item: {item.type}</div>;
      })}
    </fieldset>
    {/* Evidence navigation stays available while reading historical revisions. */}
    <div className="review-toolbar">{regions.map(r => <button key={r.region_id} onClick={() => onRegion(r.region_id)}>{r.region_id}</button>)}</div>
    <details><summary>保存済みReview body text</summary><pre>{node.body_text}</pre></details>
    {automatic && <details><summary>Automatic Draft（読み取り専用）</summary><pre>{automatic.body_text}</pre></details>}
  </article>;
}
