"use client";
import { useEffect, useRef, useState } from "react";
import { apiFetch, json, ApiRequestError } from "@/lib/api/client";

import type { DiagramRecord, DiagramSelection } from "@/types/diagrams";
export type { DiagramRecord, DiagramSelection } from "@/types/diagrams";
const clean = (record: DiagramRecord) => {const value = {...record}; delete value.preview_url; return value;};
function errorMessage(e: unknown) {
  const code = e instanceof ApiRequestError ? e.code : undefined;
  return `図の出典または範囲を確認できません。${code ? `（${code}）` : "再試行してください。"}`;
}

export function DiagramReview({path, revision, records = [], disabled, sourceStale, targetQuestionId, disabledReason, label, onChange, onSelect}: {
  path: string; revision: number; records?: DiagramRecord[]; disabled: boolean; sourceStale?: boolean; targetQuestionId?: string; disabledReason?: string; label: string;
  onChange: (records: DiagramRecord[]) => void; onSelect: (selection: DiagramSelection) => void;
}) {
  const requestPath = (suffix = "") => `${path}${suffix}${targetQuestionId ? `?question_id=${encodeURIComponent(targetQuestionId)}` : ""}`;
  const scope = `${path}:${revision}:${sourceStale}:${targetQuestionId}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const [candidates, setCandidates] = useState<DiagramRecord[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false), [editing, setEditing] = useState<DiagramRecord>();
  const [box, setBox] = useState<number[]>([]), [preview, setPreview] = useState<DiagramRecord>();
  useEffect(() => {
    let active = true;
    setBusy(false); setCandidates(sourceStale ? records.map(r => ({...r, state: "candidate", status: "unresolved", reason_code: "diagram_source_stale"})) : []); setLoaded(false); setEditing(undefined); setPreview(undefined); setError("");
    // Resuming saved review never requests discovery/vision.
    if (records.length && !sourceStale) apiFetch<{diagrams: DiagramRecord[]}>(requestPath()).then(r => {
      if (active) {
        setCandidates(r.diagrams); setLoaded(true);
        // Server revalidation can invalidate a saved accepted record. Keep
        // registration readiness in sync without persisting or rediscovering.
        const invalid = r.diagrams.filter(record => record.status === "unresolved");
        if (records.some(record => record.state === "accepted" && invalid.some(value => value.id === record.id))) {
          onChange(records.map(record => clean(invalid.find(value => value.id === record.id) || record)));
        }
      }
    }).catch(e => { if (active) setError(errorMessage(e)); });
    return () => {active = false;};
    // Each explicit revision/target transition reloads saved source state only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, revision, sourceStale, targetQuestionId]);
  async function discover() {
    setBusy(true); setError("");
    try {
      const result = await apiFetch<{diagrams: DiagramRecord[]}>(requestPath(), json({expected_revision: revision}));
      if (currentScope.current !== scope) return;
      setCandidates(result.diagrams.map(c => ({...c, ...records.find(r => r.id === c.id && r.context_sha256 === c.context_sha256), preview_url: c.preview_url})));
      setLoaded(true);
      if (result.diagrams[0]) onSelect({record: result.diagrams[0], manual: false});
    } catch (e) { if (currentScope.current === scope) setError(errorMessage(e)); }
    finally {if (currentScope.current === scope) setBusy(false);}
  }
  function decide(candidate: DiagramRecord, state: DiagramRecord["state"]) {
    const record = {...candidate, state};
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
      const result = await apiFetch<DiagramRecord>(requestPath(`/${editing.id}/crop-preview`), json({expected_revision: revision, final_bbox: box}));
      if (currentScope.current !== scope) return;
      setPreview(result); onSelect({record: result, manual: true, onBounds: value => {setBox(value); setPreview(undefined);}});
    } catch (e) {if (currentScope.current === scope) setError(errorMessage(e));} finally {if (currentScope.current === scope) setBusy(false);}
  }
  return <section className="panel section diagram-review" aria-label={label} aria-busy={busy} tabIndex={-1}>
    <h3>{label}</h3>
    <p className="muted">図の出典・範囲を確認して選択します。保存・登録は上部の操作から行います。</p>
    <button type="button" disabled={disabled || busy || sourceStale || !!disabledReason} onClick={discover}>{busy ? "図の範囲を確認中…" : "図候補を確認"}</button>
    {!loaded && !records.length && <p className="muted">まだ図候補を確認していません。</p>}
    {disabledReason && <p className="muted">{disabledReason}</p>}
    {sourceStale && <p className="notice">設問の構造・対応先の変更を保存してから、図候補を確認してください。</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {loaded && !candidates.length && <p>この設問の出典範囲には図候補が見つかりませんでした。</p>}
    {candidates.map(c => ({...c, ...records.find(r => r.id === c.id && r.context_sha256 === c.context_sha256), preview_url: c.preview_url})).map((candidate, index) => <article key={candidate.id} data-diagram-id={candidate.id}>
      <h4><button type="button" onClick={() => onSelect({record: candidate, manual: false})}>図{index+1} · ページ {candidate.page_index+1}</button></h4>
      <p>{candidate.state === "accepted" ? "使用中" : candidate.state === "excluded" ? "対象外" : "候補"} · {candidate.teacher_adjusted ? "教師が範囲を修正" : "自動検出"}</p>
      {candidate.preview_url && <img className="review-crop" src={candidate.preview_url} alt={`図${index+1}の切り出し範囲`} /> /* eslint-disable-line @next/next/no-img-element */}
      {candidate.status === "unresolved" && <p className="notice">出典範囲の確認が必要です。（{candidate.reason_code}）</p>}
      <div className="review-toolbar">
        <button type="button" disabled={disabled || busy || sourceStale || candidate.status === "unresolved"} onClick={() => decide(candidate, "accepted")}>この図を使用</button>
        <button type="button" disabled={disabled || busy || sourceStale || !candidate.crop_sha256} onClick={() => edit(candidate)}>範囲を修正</button>
        <button type="button" disabled={disabled || busy || sourceStale || candidate.reason_code === "diagram_source_stale"} onClick={() => decide(candidate, "excluded")}>対象外にする</button>
        {candidate.reason_code === "diagram_source_stale" && <button type="button" disabled={disabled || busy} onClick={() => {onChange(records.filter(r => r.id !== candidate.id)); setCandidates(c => c.filter(r => r.id !== candidate.id));}}>古い図の記録を削除</button>}
      </div>
      <details><summary>図の出典情報</summary><pre>{JSON.stringify(clean(candidate), null, 2)}</pre></details>
    </article>)}
    {editing && <fieldset disabled={disabled || busy} aria-label="図の範囲を修正">
      <legend>図の範囲を修正</legend>
      <p>左のPDF上で範囲をドラッグしてください。座標でも調整できます。</p>
      <div className="diagram-bounds">{["左", "上", "右", "下"].map((label, i) => <label key={label}>{label}<input type="number" step="0.1" aria-label={`図の範囲 ${label}`} value={box[i] ?? ""} onChange={e => {setBox(b => b.map((v, j) => j === i ? Number(e.target.value) : v)); setPreview(undefined);}} /></label>)}</div>
      <button type="button" onClick={updatePreview}>プレビューを更新</button>
      {preview?.preview_url && <img className="review-crop" src={preview.preview_url} alt="修正後の図の範囲" /> /* eslint-disable-line @next/next/no-img-element */}
      <button type="button" disabled={!preview} onClick={() => {if (preview) decide({...preview, state: editing.state}, editing.state); setEditing(undefined);}}>範囲を適用</button>
      <button type="button" onClick={() => {onSelect({record: editing, manual: false}); setEditing(undefined); setPreview(undefined);}}>キャンセル</button>
    </fieldset>}
  </section>;
}
