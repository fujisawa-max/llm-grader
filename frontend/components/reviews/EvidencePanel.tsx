"use client";
import { useEffect, useState } from "react";
import { reviews } from "@/lib/api/reviews";
import type { Decision, Json, RegionEvidence } from "@/types/reviews";

export function EvidencePanel({ id, regionId, decision, readonly, onDecision }: {
  id: string; regionId: string; decision: Decision; readonly: boolean; onDecision: (d: Decision) => void;
}) {
  const [data, setData] = useState<RegionEvidence>();
  const [raw, setRaw] = useState<Json>();
  const [error, setError] = useState("");
  const [rawError, setRawError] = useState("");
  const [rawLoading, setRawLoading] = useState(false);
  const [cropError, setCropError] = useState(false);
  useEffect(() => {
    let active = true;
    setData(undefined); setRaw(undefined); setError(""); setRawError(""); setCropError(false);
    reviews.evidence(id, regionId).then(d => { if (active) setData(d); })
      .catch(() => { if (active) setError("Evidenceを取得できません。hashまたは通信状態を確認してください。"); });
    return () => { active = false; };
  }, [id, regionId]);
  async function loadRaw() {
    setRawLoading(true); setRawError("");
    try { setRaw((await reviews.raw(id, regionId)).raw); }
    catch { setRawError("Raw evidenceの取得に失敗しました。"); }
    finally { setRawLoading(false); }
  }
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p>Evidenceを読み込み中…</p>;
  const { region, parsed_view: parsed, pin } = data;
  const formula = region.region_type === "formula";
  const flags = [...new Set([...region.review_flags, ...(parsed?.review_flags || []), ...(parsed?.parser_warnings || [])])];
  const candidate = parsed?.transcription_normalized || parsed?.output.recognized_expression;
  return <article className="panel review-evidence" data-testid="evidence-panel">
    <h3>{formula ? "Formula" : "Figure"} · {regionId}</h3>
    <p>割当: {region.assigned_question_key || "未割当"} · Page {region.page_index + 1}</p>
    <p className="muted">bbox: {region.bbox.map(n => n.toFixed(2)).join(", ")}</p>
    {data.crop_source === "review_preview" && <p className="notice">Native-only region：比較用PDF cropです。Visionは実行されていません。</p>}
    {data.crop_available ? <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="review-crop" alt={`${regionId} original crop`} src={reviews.cropUrl(id, regionId)} onError={() => setCropError(true)} />
      {cropError && <p className="error">Cropの取得に失敗しました。</p>}
    </> : <p className="notice">Native-only region：Vision cropはありません。左の原PDFで確認してください。</p>}
    <div className="evidence-comparison">
      <section><h4>Native evidence</h4>
        {formula ? <pre>{region.text_fragments?.map(t => t.native_text).join("\n") || "Native transcriptionなし"}</pre>
          : <p>画像evidence {region.image_evidence?.length || 0}件 · source要素 {region.source_element_ids.length}件</p>}
        <details><summary>Native math / image / vector evidence</summary><pre>{JSON.stringify({ routing: region.routing_evidence, elements: data.native_elements }, null, 2)}</pre></details>
      </section>
      <section><h4>Vision candidate</h4>
        {!parsed ? <p>Vision evidenceなし</p> : <>
          {!formula && <p className="notice"><strong>{parsed.parse_status === "partial" ? "Partial · Needs review" : parsed.parse_status}</strong> · structured={String(parsed.structured)}</p>}
          {formula ? <pre>{typeof candidate === "string" ? candidate : "Candidateなし"}</pre> :
            ["visible_text", "labels", "visual_elements", "spatial_relations"].map(key => <div key={key}><strong>{key}</strong><pre>{JSON.stringify(parsed.output[key] || [], null, 2)}</pre></div>)}
          <p className="muted">Source field: {parsed.source_field || "不明"}<br />Parser: {parsed.parser_name || "legacy"} / {parsed.parser_version || "legacy"}</p>
          {parsed.unstructured_observation && <details><summary>Unstructured observation（未確定）</summary><pre>{parsed.unstructured_observation}</pre></details>}
        </>}
      </section>
    </div>
    {flags.length > 0 && <div className="notice" aria-label="Evidence warnings">{flags.map(f => <div key={f}>{f}</div>)}</div>}
    {data.raw_available && <details key={regionId} onToggle={event => { if (event.currentTarget.open && raw === undefined && !rawLoading) void loadRaw(); }}>
      <summary>Raw Vision response（読み取り専用）</summary>
      {rawLoading && <p>Rawを読み込み中…</p>}{rawError && <p role="alert">{rawError}<button onClick={loadRaw}>再試行</button></p>}
      {raw !== undefined && <pre data-testid="raw-vision-output">{JSON.stringify(raw, null, 2)}</pre>}
    </details>}
    <fieldset disabled={readonly} className="review-fields"><legend>教師の判断</legend>
      <label>Decision<select aria-label={`${regionId} decision`} value={decision.decision} onChange={e => onDecision({ ...decision, decision: e.target.value })}>
        <option value="unreviewed">unreviewed — 未確認</option>
        {formula ? <><option value="use_native" disabled={!region.text_fragments?.length}>use_native</option>
          <option value="use_vision" disabled={!pin?.has_candidate}>use_vision</option><option value="teacher_edit">teacher_edit</option></>
          : <><option value="accepted_as_evidence">accepted_as_evidence</option><option value="needs_correction">needs_correction</option></>}
      </select></label>
      {formula && decision.decision === "teacher_edit" && <label>Teacher transcription<textarea aria-label="Teacher transcription" maxLength={20000} value={decision.teacher_transcription || ""}
        onChange={e => onDecision({ ...decision, teacher_transcription: e.target.value })} /><small>教師入力をReview Revisionへ保存します。</small></label>}
      <label>Teacher note<textarea aria-label="Teacher note" maxLength={2000} value={decision.note || ""} onChange={e => onDecision({ ...decision, note: e.target.value })} /></label>
    </fieldset>
    <details><summary>Source provenance / pinned hashes</summary><pre>{JSON.stringify({ region_id: regionId, source_elements: region.source_element_ids, pin }, null, 2)}</pre></details>
  </article>;
}
