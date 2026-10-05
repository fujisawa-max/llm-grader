import { reviewWarningId } from "@/lib/reviewIssues";
import type { ReviewWarning, WarningResolution } from "@/types/reviews";
import { reviewIssueLabel, reviewIssueReason, reviewStateLabel } from "@/lib/reviewLabels";

export function WarningPanel({ warnings, states, readonly, onChange, targetLabel, onJump }: {
  warnings: ReviewWarning[]; states: Record<string, WarningResolution>; readonly: boolean;
  onChange: (id: string, resolution: WarningResolution) => void;
  targetLabel?: (warning: ReviewWarning) => string; onJump?: (warning: ReviewWarning) => void;
}) {
  return <section className="panel" aria-label="確認事項一覧"><h3>確認事項</h3>
    {!warnings.length && <p>確認が必要な項目はありません。</p>}
    {warnings.map((warning, index) => {
      const target = targetLabel?.(warning) || "試験全体";
      const pending = (states[warning.id]?.state || "unreviewed") === "unreviewed";
      return <div id={reviewWarningId(warning.id)} key={warning.id} className={pending ? "review-warning-wrap needs-check" : "review-warning-wrap"}>
        <fieldset disabled={readonly} className="review-warning">
          <legend>確認事項 {index + 1}: {target} {pending && <span className="review-needs-check">要確認</span>}</legend>
          <strong>{reviewIssueLabel(warning.code)}</strong>
          <p>{reviewIssueReason(warning.code)}</p>
          <label>確認状態<select aria-label={`確認事項 ${index + 1}の状態`} value={states[warning.id]?.state || "unreviewed"}
            onChange={event => onChange(warning.id, { ...states[warning.id], state: event.target.value as WarningResolution["state"] })}>
            {(["unreviewed", "acknowledged", "resolved"] as const).map(state => <option key={state} value={state}>{reviewStateLabel(state)}</option>)}
          </select></label>
          <label>教師メモ<input maxLength={2000} value={states[warning.id]?.note || ""} onChange={event => onChange(warning.id, { state: states[warning.id]?.state || "unreviewed", note: event.target.value })} /></label>
          <details><summary>技術情報</summary><code>{warning.source_id} · {warning.code}</code></details>
        </fieldset>
        {onJump && <button type="button" onClick={() => onJump(warning)}>{target}を確認</button>}
      </div>;
    })}
    <p className="muted">確認状態を保存しても、元の警告は残ります。</p>
  </section>;
}
