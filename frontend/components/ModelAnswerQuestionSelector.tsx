"use client";

export interface QuestionSelectorOption { id: string; label: string }

export function ModelAnswerQuestionSelector({ label, options, selectedId, onChange, children }: {
  label: string;
  options: QuestionSelectorOption[];
  selectedId: string;
  onChange: (id: string) => void;
  children?: React.ReactNode;
}) {
  const value = options.some((option) => option.id === selectedId) ? selectedId : options[0]?.id || "";
  return <div className="model-answer-target-picker"><label className="field">{label}
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {children || options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
    </select>
  </label></div>;
}
