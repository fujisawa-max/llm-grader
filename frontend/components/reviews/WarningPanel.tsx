import type { ReviewWarning, WarningResolution } from "@/types/reviews";

export function WarningPanel({ warnings, states, readonly, onChange }: {
  warnings: ReviewWarning[]; states: Record<string, WarningResolution>; readonly: boolean;
  onChange: (id: string, resolution: WarningResolution) => void;
}) {
  return <section className="panel"><h3>Warnings / 教師確認</h3>
    {!warnings.length && <p>警告なし</p>}
    {warnings.map(w => <fieldset key={w.id} disabled={readonly} className="review-warning">
      <legend>{w.source_id} · {w.code}</legend>
      <label>確認状態<select aria-label={`${w.id} state`} value={states[w.id]?.state || "unreviewed"}
        onChange={e => onChange(w.id, { ...states[w.id], state: e.target.value as WarningResolution["state"] })}>
        <option value="unreviewed">unreviewed — 未確認</option><option value="acknowledged">acknowledged — 確認済み</option><option value="resolved">resolved — 対応済み</option>
      </select></label>
      <label>Note<input maxLength={2000} value={states[w.id]?.note || ""} onChange={e => onChange(w.id, { state: states[w.id]?.state || "unreviewed", note: e.target.value })} /></label>
    </fieldset>)}
    <p className="muted">確認状態を保存しても、元の警告は残ります。</p>
  </section>;
}
