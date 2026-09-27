import type { ReviewWarning, WarningResolution } from "@/types/reviews";
import { reviewIssueLabel, reviewStateLabel } from "@/lib/reviewLabels";

export function WarningPanel({ warnings, states, readonly, onChange }: {
  warnings: ReviewWarning[]; states: Record<string, WarningResolution>; readonly: boolean;
  onChange: (id: string, resolution: WarningResolution) => void;
}) {
  return <section className="panel"><h3>確認事項</h3>
    {!warnings.length && <p>確認が必要な項目はありません。</p>}
    {warnings.map((w, index) => <fieldset key={w.id} disabled={readonly} className="review-warning">
      <legend>確認事項 {index + 1}: {reviewIssueLabel(w.code)}{w.blocking ? "（対応が必要）" : ""}</legend>
      <label>確認状態<select aria-label={`確認事項 ${index + 1}の状態`} value={states[w.id]?.state || "unreviewed"}
        onChange={e => onChange(w.id, { ...states[w.id], state: e.target.value as WarningResolution["state"] })}>
        {(["unreviewed", "acknowledged", "resolved"] as const).map(state => <option key={state} value={state}>{reviewStateLabel(state)}</option>)}
      </select></label>
      <label>教師メモ<input maxLength={2000} value={states[w.id]?.note || ""} onChange={e => onChange(w.id, { state: states[w.id]?.state || "unreviewed", note: e.target.value })} /></label>
      <details><summary>技術情報</summary><code>{w.source_id} · {w.code}</code></details>
    </fieldset>)}
    <p className="muted">確認状態を保存しても、元の警告は残ります。</p>
  </section>;
}
