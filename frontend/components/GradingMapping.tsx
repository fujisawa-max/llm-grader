"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { TechnicalDetails, friendlyStatus, friendlyWarning } from "@/components/ui";

interface Submission { id: string; submission_key: string; attempt_number: number }
interface Context { effective_text: string; context_sha256: string; assets: {asset_id: string; sha256: string}[] }
interface Bundle {
  bundle_sha256: string;
  student_answer: {question_id: string; pages: {page_id: string; sha256: string}[]; sha256: string};
  model_answer: {id: string; question_id: string; content: string};
  rubric: {id: string; question_id: string; entry: unknown};
}
interface Row {
  question_id: string; display_label: string; stable_question_key: string;
  state: string; student_answer_mapped: boolean; model_answer_mapped: boolean; rubric_mapped: boolean;
  context: Context | null; bundle: Bundle | null;
  blockers: {code: string; message: string}[]; warnings: {code: string}[];
}
interface Mapping {
  gradable_count: number; ready_bundle_count: number; blocked_bundle_count: number;
  orphan_answer_count: number; orphan_rubric_entry_count: number; can_build_all_inputs: boolean;
  questions: Row[];
}

export function GradingMapping({testId}: {testId: string}) {
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [submission, setSubmission] = useState("");
  const [mapping, setMapping] = useState<Mapping>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [generation, reload] = useState(0);
  useEffect(() => {
    let active = true;
    apiFetch<Submission[]>(`/tests/${testId}/submissions`).then(values => {
      if (active) {setSubmissions(values); setSubmission(values[0]?.id || "");}
    }).catch(e => {if (active) setError(String(e));});
    return () => {active = false;};
  }, [testId]);
  useEffect(() => {
    let active = true;
    setMapping(undefined); setError("");
    if (submission) apiFetch<Mapping>(`/tests/${testId}/submissions/${submission}/grading-input-readiness`)
      .then(value => {if (active) {setMapping(value); setSelected(value.questions[0]?.question_id || "");}})
      .catch(e => {if (active) setError(String(e));});
    return () => {active = false;};
  }, [testId, submission, generation]);
  const row = mapping?.questions.find(q => q.question_id === selected);
  return <section className="panel section" aria-label="Grading input mapping">
    <h2>採点入力の対応確認</h2>
    <p>答案・問題・模範解答・承認済み採点基準の対応を読み取り専用で確認します。ここでは答案の読み取りや採点は実行しません。</p>
    {error && <p role="alert">{error}</p>}
    {!submissions.length ? <p>答案はまだ登録されていません。</p> : <>
      <label>答案を選択 <select aria-label="Mapping submission" value={submission} onChange={e => setSubmission(e.target.value)}>
        {submissions.map(s => <option key={s.id} value={s.id}>答案 {s.attempt_number}回目</option>)}
      </select></label>
      <button type="button" onClick={() => reload(v => v + 1)}>対応を再確認</button>
    </>}
    {mapping && <>
      <p role="status">{mapping.can_build_all_inputs ? "採点入力の準備完了" : "追加の確認が必要です"} · 対象 {mapping.gradable_count}問 · 準備完了 {mapping.ready_bundle_count}問</p>
      <TechnicalDetails label="技術情報"><p>未対応答案 {mapping.orphan_answer_count} / 未対応採点基準 {mapping.orphan_rubric_entry_count}</p></TechnicalDetails>
      <label>問題を選択 <select aria-label="Mapping question" value={selected} onChange={e => setSelected(e.target.value)}>
        {mapping.questions.map(q => <option key={q.question_id} value={q.question_id}>{q.display_label}</option>)}
      </select></label>
    </>}
    {row && <article data-testid="mapping-preview">
      <h3>{row.display_label}: {friendlyStatus(row.state)}</h3>
      <p>答案 {row.student_answer_mapped ? "対応済み" : "要確認"} · 模範解答 {row.model_answer_mapped ? "対応済み" : "要確認"} · 採点基準 {row.rubric_mapped ? "対応済み" : "要確認"}</p>
      {row.blockers.map(v => <TechnicalDetails key={v.code} label={friendlyWarning(v.code)}><p role="alert"><code>{v.code}</code>: {v.message}</p></TechnicalDetails>)}
      {row.warnings.map(v => <TechnicalDetails key={v.code} label={friendlyWarning(v.code)}><code>{v.code}</code></TechnicalDetails>)}
      {row.context && <>
        <h4>採点に使う問題情報</h4><pre>{row.context.effective_text}</pre>
        <TechnicalDetails label="技術情報"><p>Context hash: <code>{row.context.context_sha256}</code></p><p>Assets: {row.context.assets.length}</p>{row.context.assets.map(a => <p key={a.asset_id}>{a.asset_id} · SHA {a.sha256}</p>)}</TechnicalDetails>
      </>}
      {row.bundle && <>
        <h4>Student Answer pages</h4><p>Question ID: {row.bundle.student_answer.question_id}</p>
        {row.bundle.student_answer.pages.map(p => <p key={p.page_id}>{p.page_id} · SHA {p.sha256}</p>)}
        <h4>Model Answer</h4><p>Question ID: {row.bundle.model_answer.question_id}</p><pre>{row.bundle.model_answer.content}</pre>
        <h4>Approved Rubric entry</h4><p>Question ID: {row.bundle.rubric.question_id}</p><pre>{JSON.stringify(row.bundle.rubric.entry, null, 2)}</pre>
        <p>Bundle hash: <code>{row.bundle.bundle_sha256}</code></p>
      </>}
    </article>}
  </section>;
}
