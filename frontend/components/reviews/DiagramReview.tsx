"use client";
import { useEffect, useRef, useState } from "react";
import { apiFetch, json, ApiRequestError } from "@/lib/api/client";

import type { DiagramRecord, DiagramSelection } from "@/types/diagrams";
export type { DiagramRecord, DiagramSelection } from "@/types/diagrams";
type DiagramScope = "exact" | "parent" | "pdf";
type Discovery = {diagrams: DiagramRecord[]; diagnostics?: Record<string, unknown>; fallback?: {scope: "parent" | "pdf"; source_question_path?: string} | null};
const clean = (record: DiagramRecord) => {const value = {...record}; delete value.preview_url; return value;};
function trust(record: DiagramRecord) {
  if (record.trust_state === "hard_invalid" || record.reason_code === "diagram_source_stale") return "hard_invalid";
  if (record.trust_state === "teacher_confirmable") return "teacher_confirmable";
  return record.status === "unresolved" || record.reason_code ? "hard_invalid" : "trusted";
}
function mergeRecord(candidate: DiagramRecord, records: DiagramRecord[]): DiagramRecord {
  if (trust(candidate) === "hard_invalid") return candidate;
  const local = records.find(r => r.id === candidate.id && r.context_sha256 === candidate.context_sha256);
  return {...candidate, ...local, trust_state: candidate.trust_state, preview_url: candidate.preview_url};
}
function errorCode(e: unknown) { return e instanceof ApiRequestError ? e.code : undefined; }
function errorMessage(e: unknown) {
  if (errorCode(e) === "diagram_source_boundary") return "図の範囲が設問の出典範囲を超えています。範囲を狭めるか、別候補を選択してください。";
  return "図の出典または範囲を確認できません。範囲を見直すか、再度図候補を確認してください。";
}

export function DiagramReview({path, revision, records = [], disabled, sourceStale, targetQuestionId, disabledReason, label, onChange, onSelect}: {
  path: string; revision: number; records?: DiagramRecord[]; disabled: boolean; sourceStale?: boolean; targetQuestionId?: string; disabledReason?: string; label: string;
  onChange: (records: DiagramRecord[]) => void; onSelect: (selection: DiagramSelection) => void;
}) {
  const requestPath = (suffix = "", selectedScope?: DiagramScope) => {
    const params = new URLSearchParams();
    if (targetQuestionId) params.set("question_id", targetQuestionId);
    if (targetQuestionId && selectedScope) params.set("scope", selectedScope);
    return `${path}${suffix}${params.size ? `?${params}` : ""}`;
  };
  const scope = `${path}:${revision}:${sourceStale}:${targetQuestionId}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const [diagnostics, setDiagnostics] = useState<Discovery["diagnostics"]>();
  const [fallback, setFallback] = useState<Discovery["fallback"]>();
  const [discoveryScope, setDiscoveryScope] = useState<DiagramScope>("exact");
  const [candidates, setCandidates] = useState<DiagramRecord[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState<string>();
  const [loaded, setLoaded] = useState(false), [editing, setEditing] = useState<DiagramRecord>();
  const [box, setBox] = useState<number[]>([]), [preview, setPreview] = useState<DiagramRecord>();
  useEffect(() => {
    let active = true;
    setDiagnostics(undefined); setFallback(undefined); setDiscoveryScope("exact");
    setBusy(false); setCandidates(sourceStale ? records.map(r => ({...r, state: "candidate", status: "unresolved", reason_code: "diagram_source_stale", trust_state: "hard_invalid", teacher_confirmed: false})) : []); setLoaded(false); setEditing(undefined); setPreview(undefined); setError("");
    // Resuming saved review never requests discovery/vision.
    if (records.length && !sourceStale) apiFetch<Discovery>(requestPath()).then(r => {
      if (active) {
        setCandidates(r.diagrams); setLoaded(true); setFallback(r.fallback); setDiagnostics(r.diagnostics); setDiscoveryScope(r.diagrams[0]?.scope || "exact");
        // Server revalidation can invalidate a saved accepted record. Keep
        // registration readiness in sync without persisting or rediscovering.
        const invalid = r.diagrams.filter(record => trust(record) === "hard_invalid" || (record.state === "accepted" && trust(record) === "teacher_confirmable" && !record.teacher_confirmed));
        if (records.some(record => record.state === "accepted" && invalid.some(value => value.id === record.id))) {
          onChange(records.map(record => clean(invalid.find(value => value.id === record.id) || record)));
        }
      }
    }).catch(e => {
      if (active) {
        setError(errorMessage(e)); setErrorDetails(errorCode(e));
        // Failed source revalidation must not leave saved acceptance/readiness
        // usable. This affects local review state only, never persists implicitly.
        const invalid: DiagramRecord[] = records.map(record => ({...record,
          state: "candidate", status: "unresolved", trust_state: "hard_invalid",
          reason_code: errorCode(e) || "diagram_source_validation_failed",
          teacher_confirmed: false, trust_state_at_accept: null,
          confirmation_reason_code: null, acceptance_method: null}));
        setCandidates(invalid); setLoaded(true); onChange(invalid.map(clean));
      }
    });
    return () => {active = false;};
    // Each explicit revision/target transition reloads saved source state only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, revision, sourceStale, targetQuestionId]);
  async function discover(selectedScope: DiagramScope = "exact") {
    setBusy(true); setError("");
    try {
      const result = await apiFetch<Discovery>(requestPath("", selectedScope), json({expected_revision: revision}));
      if (currentScope.current !== scope) return;
      setCandidates(result.diagrams.map(c => mergeRecord(c, records)));
      setLoaded(true); setFallback(result.fallback); setDiagnostics(result.diagnostics); setDiscoveryScope(selectedScope);
      if (result.diagrams[0]) onSelect({record: result.diagrams[0], manual: false});
    } catch (e) { if (currentScope.current === scope) {setError(errorMessage(e)); setErrorDetails(errorCode(e));} }
    finally {if (currentScope.current === scope) setBusy(false);}
  }
  function decide(candidate: DiagramRecord, state: DiagramRecord["state"]) {
    const confirmed = state === "accepted" && trust(candidate) === "teacher_confirmable";
    const record: DiagramRecord = {...candidate, state, teacher_confirmed: confirmed,
      trust_state_at_accept: state === "accepted" ? trust(candidate) : null,
      confirmation_reason_code: confirmed ? candidate.reason_code : null,
      acceptance_method: confirmed ? "accepted_by_teacher_after_unresolved_detection" : state === "accepted" ? "accepted_by_teacher" : null};
    setCandidates(current => current.map(c => c.id === record.id ? record : c));
    onChange([...records.filter(r => r.id !== record.id), clean(record)]);
    onSelect({record, manual: false});
  }
  function edit(candidate: DiagramRecord) {
    const initial = candidate.final_bbox || candidate.automatic_bbox;
    setEditing(candidate); setBox(initial); setPreview(undefined); setError("");
    onSelect({record: {...candidate, final_bbox: initial}, manual: true, onBounds: value => {setBox(value); setPreview(undefined);}});
  }
  async function updatePreview() {
    if (!editing) return;
    setBusy(true); setError("");
    try {
      const result = await apiFetch<DiagramRecord>(requestPath(`/${editing.id}/crop-preview`, editing.scope || "exact"), json({expected_revision: revision, final_bbox: box}));
      if (currentScope.current !== scope) return;
      setPreview(result); onSelect({record: result, manual: true, onBounds: value => {setBox(value); setPreview(undefined);}});
    } catch (e) {if (currentScope.current === scope) {setError(errorMessage(e)); setErrorDetails(errorCode(e));}} finally {if (currentScope.current === scope) setBusy(false);}
  }
  return <section className="panel section diagram-review" aria-label={label} aria-busy={busy} tabIndex={-1}>
    <h3>{label}</h3>
    <p className="muted">図の出典・範囲を確認して選択します。保存・登録は上部の操作から行います。</p>
    <button type="button" disabled={disabled || busy || sourceStale || !!disabledReason} onClick={() => discover()}>{busy ? "図の範囲を確認中…" : "図候補を確認"}</button>
    {!loaded && !records.length && <p className="muted">まだ図候補を確認していません。</p>}
    {disabledReason && <p className="muted">{disabledReason}</p>}
    {sourceStale && <p className="notice">設問の構造・対応先の変更を保存してから、図候補を確認してください。</p>}
    {error && <><p role="alert" className="error">{error}</p>{errorDetails && <details><summary>図の検証情報</summary><pre>{errorDetails}</pre></details>}</>}
    {loaded && !candidates.length && <>
      <p>{fallback?.scope === "pdf" ? "この設問および親設問には図候補が見つかりませんでした。" : "この設問の出典範囲には図候補が見つかりませんでした。"}</p>
      {fallback?.scope === "parent" && <>
        <p>親設問「{fallback.source_question_path}」に図候補があります。</p>
        <button type="button" disabled={disabled || busy || sourceStale} onClick={() => discover("parent")}>親設問の図候補を表示</button>
      </>}
      {fallback?.scope === "pdf" && <button type="button" disabled={disabled || busy || sourceStale} onClick={() => discover("pdf")}>このPDFのすべての図候補を表示</button>}
    </>}
    {!!candidates.length && discoveryScope !== "exact" && <p className="muted">図の出典: {discoveryScope === "parent" ? `親設問 ${candidates[0].source_question_path || ""}` : "PDF全体"}（編集対象は変わりません）</p>}
    {candidates.map(c => mergeRecord(c, records)).map((candidate, index) => <article key={candidate.id} data-diagram-id={candidate.id}>
      <h4><button type="button" onClick={() => onSelect({record: candidate, manual: false})}>図{index+1} · ページ {candidate.page_index+1}</button></h4>
      {candidate.scope && candidate.scope !== "exact" && <p>出典: {candidate.scope === "parent" ? `親設問 ${candidate.source_question_path}` : `PDF全体${candidate.source_question_path ? ` · ${candidate.source_question_path}` : ""}`} · p.{candidate.page_index + 1}</p>}
      <p>{candidate.state === "accepted" ? "使用中" : candidate.state === "excluded" ? "対象外" : "候補"} · {candidate.teacher_adjusted ? "教師が範囲を修正" : "自動検出"}</p>
      {candidate.preview_url && <img className="review-crop" src={candidate.preview_url} alt={`図${index+1}の切り出し範囲`} /> /* eslint-disable-line @next/next/no-img-element */}
      {trust(candidate) === "teacher_confirmable" && <p className="notice">図の出典範囲を自動では確認できませんでした。PDFと図の範囲を確認してください。教師が確認した図は使用できます。</p>}
      {trust(candidate) === "hard_invalid" && <p className="notice">この図は元PDFとの対応を確認できないため使用できません。変更を保存して再度図候補を確認するか、別候補を選択してください。</p>}
      {disabled && <p className="muted">現在は編集できません。編集可能な修正版で再開してください。</p>}
      {busy && <p className="muted">範囲の確認中です。完了後に図を選択できます。</p>}
      <div className="review-toolbar">
        <button type="button" disabled={disabled || busy || sourceStale || trust(candidate) === "hard_invalid"} onClick={() => decide(candidate, "accepted")}>{trust(candidate) === "teacher_confirmable" ? "この図を確認して使用" : "この図を使用"}</button>
        <button type="button" disabled={disabled || busy || sourceStale || !candidate.crop_sha256} onClick={() => edit(candidate)}>範囲を修正</button>
        <button type="button" disabled={disabled || busy || sourceStale || candidate.reason_code === "diagram_source_stale"} onClick={() => decide(candidate, "excluded")}>対象外にする</button>
        {candidate.reason_code === "diagram_source_stale" && <button type="button" disabled={disabled || busy} onClick={() => {onChange(records.filter(r => r.id !== candidate.id)); setCandidates(c => c.filter(r => r.id !== candidate.id));}}>古い図の記録を削除</button>}
      </div>
      <details><summary>図の出典情報</summary><pre>{JSON.stringify(clean(candidate), null, 2)}</pre></details>
    </article>)}
    {diagnostics && <details><summary>図の探索情報</summary><pre>{JSON.stringify(diagnostics, null, 2)}</pre></details>}
    {editing && <fieldset disabled={disabled || busy} aria-label="図の範囲を修正">
      <legend>図の範囲を修正</legend>
      <p>左のPDF上で範囲をドラッグしてください。座標でも調整できます。</p>
      <div className="diagram-bounds">{["左", "上", "右", "下"].map((label, i) => <label key={label}>{label}<input type="number" step="0.1" aria-label={`図の範囲 ${label}`} value={box[i] ?? ""} onChange={e => {setBox(b => b.map((v, j) => j === i ? Number(e.target.value) : v)); setPreview(undefined);}} /></label>)}</div>
      <button type="button" onClick={updatePreview}>プレビューを更新</button>
      {preview?.preview_url && <img className="review-crop" src={preview.preview_url} alt="修正後の図の範囲" /> /* eslint-disable-line @next/next/no-img-element */}
      <button type="button" disabled={!preview} onClick={() => {if (preview) decide(preview, trust(preview) === "teacher_confirmable" ? "candidate" : editing.state); setEditing(undefined);}}>範囲を適用</button>
      <button type="button" onClick={() => {onSelect({record: editing, manual: false}); setEditing(undefined); setPreview(undefined);}}>キャンセル</button>
    </fieldset>}
  </section>;
}
