"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { TechnicalDetails, friendlyStatus } from "@/components/ui";

interface Submission { id: string; submission_key: string; attempt_number: number }
interface Run { id: string; status: string; source_sha256: string; pipeline_version: string }
interface Result { question_id: string; status: string; normalized_sha256: string | null; reconstruction: {answer_text: string; status: string; context_sha256: string} | null }

export function ReconstructionInspection({testId}: {testId: string}) {
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [submission, setSubmission] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { apiFetch<Submission[]>(`/tests/${testId}/submissions`).then(v => {setSubmissions(v); setSubmission(v[0]?.id || "");}).catch(e => setError(String(e))); }, [testId]);
  useEffect(() => { if (!submission) return; apiFetch<Run[]>(`/tests/${testId}/submissions/${submission}/answer-reconstruction-runs`).then(setRuns).catch(e => setError(String(e))); }, [testId, submission]);
  useEffect(() => { const run = runs[0]; if (!run) {setResults([]); return;} apiFetch<{results: Result[]}>(`/answer-reconstruction-runs/${run.id}/results`).then(v => setResults(v.results)).catch(e => setError(String(e))); }, [runs]);
  return <section className="panel section" aria-label="答案の読み取り内容">
    <h2>答案の読み取り内容</h2>
    <p>手書き答案を読み取り、採点に使用する形に整理した内容です。必要な場合のみ確認してください。</p>
    {error && <p role="alert">{error}</p>}
    {!submissions.length ? <p>答案はまだ登録されていません。</p> : <label>答案を選択 <select value={submission} onChange={e => setSubmission(e.target.value)}>{submissions.map(v => <option key={v.id} value={v.id}>答案 {v.attempt_number}回目</option>)}</select></label>}
    {runs.length === 0 ? <p>読み取り結果はまだありません。</p> : <>{runs.map(run => <TechnicalDetails key={run.id} label={`読み取り処理：${friendlyStatus(run.status)}`}><p>Run {run.id.slice(0, 8)} · {run.status} · source SHA {run.source_sha256}</p></TechnicalDetails>)}{results.map(result => <article key={result.question_id}><h3>問題の読み取り結果</h3>{result.reconstruction && <><pre>{result.reconstruction.answer_text}</pre><TechnicalDetails label="技術情報"><p>Question ID {result.question_id} · Context SHA {result.reconstruction.context_sha256}</p></TechnicalDetails></>}</article>)}</>}
  </section>;
}
