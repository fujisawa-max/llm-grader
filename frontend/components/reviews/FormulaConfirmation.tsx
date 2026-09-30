"use client";

import type { Decision } from "@/types/reviews";
import { formulaIsConfirmed } from "@/lib/formulaConfirmation";

export function FormulaConfirmation({ label, decision, disabled, onChange }: {
  label: string; decision?: Decision; disabled: boolean; onChange: (next: "unreviewed" | "confirmed") => void;
}) {
  return <label className="formula-confirmation">{label}
    <select aria-label={label} value={formulaIsConfirmed(decision) ? "confirmed" : "unreviewed"}
      disabled={disabled} onChange={event => onChange(event.target.value as "unreviewed" | "confirmed")}>
      <option value="unreviewed">未確認</option>
      <option value="confirmed">確認済み</option>
    </select>
  </label>;
}
