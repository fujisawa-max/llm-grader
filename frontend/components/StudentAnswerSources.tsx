"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { grading, type GradingDetail } from "@/lib/api/grading";
import { orderedGradableQuestions, gradingQuestionRank, teacherQuestionLabel } from "@/lib/questionOrder";
import type { Question, Submission, Student } from "@/types/domain";
import { TechnicalDetails, friendlyStatus } from "@/components/ui";

interface Page { page_id: string; sha256: string; mime_type: string }
interface PageIndex { submission_id: string; source_sha256?: string; page_count: number; pages: Page[] }
interface Run { id: string; status: string; source_sha256: string; pipeline_version: string }
interface StudentIdentity { submission_id?: string; student_number?: string; student_name?: string; display_label?: string; confidence?: number; review_required?: boolean; }
const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "");

export function StudentAnswerSources({testId, submissions, students, questions}: {testId: string; submissions: Submission[]; students: Student[]; questions: Question[]}) {
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [pageIndex, setPageIndex] = useState<PageIndex>();
  const [pageNumber, setPageNumber] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [detail, setDetail] = useState<GradingDetail>();
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");
  const [identities, setIdentities] = useState<Record<string, StudentIdentity>>({});
  const [identityLoaded, setIdentityLoaded] = useState(false);
  const orderedQuestions = useMemo(() => orderedGradableQuestions(questions), [questions]);
  const identityFor = (id: string): StudentIdentity => {
    const identity = identities[id];
    if (identity?.student_number) return identity;
    const sub = submissions.find(value => value.id === id);
    const student = students.find(value => value.id === sub?.student_id);
    // Explicit teacher roster mapping is display context, not OCR identity confirmation.
    return student ? {...identity, student_number: student.student_identifier, student_name: student.display_name || "", display_label: `${student.student_identifier} ${student.display_name || ""}（登録時の対応）`, review_required: true} : identity || {};
  };
  const orderedSubmissions = useMemo(() => [...submissions].sort((a, b) => {
    const an = identityFor(a.id).student_number || ""; const bn = identityFor(b.id).student_number || "";
    if (!an && !bn) return a.id.localeCompare(b.id); if (!an) return 1; if (!bn) return -1; return an.localeCompare(bn) || a.id.localeCompare(b.id);
  }), [submissions, identities]);
  const selectedSubmission = orderedSubmissions.find(s => s.id === selectedId) || orderedSubmissions[0];
  const displayName = (submission: Submission) => identityFor(submission.id).student_name || "学生情報未確認";
  const displayLabel = (submission: Submission) => identityFor(submission.id).display_label || `${identityFor(submission.id).student_number || "学生情報未確認"} ${displayName(submission)}`;
  const filtered = useMemo(() => { const needle = search.trim().toLowerCase(); return orderedSubmissions.filter(s => !needle || `${identityFor(s.id).student_number || ""} ${displayName(s)}`.toLowerCase().includes(needle)); }, [search, orderedSubmissions, identities]);
  const selectedIndex = Math.max(0, orderedSubmissions.findIndex(s => s.id === selectedSubmission?.id));
  const detailRows = useMemo(() => [...(detail?.questions || [])].sort((a, b) => gradingQuestionRank(a.question.stable_key, a.question.label) - gradingQuestionRank(b.question.stable_key, b.question.label)), [detail]);
  const questionLabel = (id: string) => { const q = questions.find(item => item.id === id); return q ? teacherQuestionLabel(q, questions) : detailRows.find(row => row.question.id === id)?.question.label || "問題"; };
  useEffect(() => { let active = true; setIdentityLoaded(false); apiFetch<StudentIdentity[]>(`/tests/${testId}/student-identities`).then(values => { if (active) { setIdentities(Object.fromEntries(values.filter(value => value.submission_id).map(value => [value.submission_id as string, value]))); setIdentityLoaded(true); } }).catch(() => { if (active) { setIdentities({}); setIdentityLoaded(true); } }); return () => { active = false; }; }, [testId, submissions]);
  useEffect(() => { if (identityLoaded && !selectedId && orderedSubmissions[0]) setSelectedId(orderedSubmissions[0].id); if (selectedId && !orderedSubmissions.some(s => s.id === selectedId)) setSelectedId(orderedSubmissions[0]?.id || ""); }, [identityLoaded, selectedId, orderedSubmissions]);
  useEffect(() => { if (!selectedSubmission) return; let active = true; setError(""); setPageIndex(undefined); setPageNumber(0); setZoom(1); setRuns([]); setDetail(undefined); setSelectedQuestionId(""); apiFetch<PageIndex>(`/tests/${testId}/submissions/${selectedSubmission.id}/answer-pages`).then(v => { if (active) setPageIndex(v); }).catch(() => { if (active) setError("原答案を読み込めませんでした。技術情報で詳細を確認できます。"); }); apiFetch<Run[]>(`/tests/${testId}/submissions/${selectedSubmission.id}/answer-reconstruction-runs`).then(v => { if (active) setRuns(v); }).catch(() => { if (active) setRuns([]); }); grading.detail(testId, selectedSubmission.id).then(v => { if (active) setDetail(v); }).catch(() => { if (active) setError("答案の読み取り内容を取得できませんでした。技術情報で詳細を確認できます。"); }); return () => { active = false; }; }, [testId, selectedSubmission?.id]);
  useEffect(() => { if (!selectedQuestionId && detailRows[0]) setSelectedQuestionId(detailRows[0].question.id); if (selectedQuestionId && detail && !detailRows.some(value => value.question.id === selectedQuestionId)) setSelectedQuestionId(detailRows[0]?.question.id || ""); }, [detail, detailRows, selectedQuestionId]);
  if (!submissions.length) return <p className="muted">答案はまだ登録されていません。</p>;
  const page = pageIndex?.pages[pageNumber]; const sourceUrl = page && selectedSubmission ? `${apiBase}/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(selectedSubmission.id)}/source-pages/${encodeURIComponent(page.page_id)}` : "";
  const moveStudent = (delta: number) => { const next = Math.min(orderedSubmissions.length - 1, Math.max(0, selectedIndex + delta)); setSelectedId(orderedSubmissions[next]?.id || ""); setSearch(""); };
  const movePage = (delta: number) => setPageNumber(value => Math.min((pageIndex?.pages.length || 1) - 1, Math.max(0, value + delta)));
  const selectedDetail = detailRows.find(value => value.question.id === selectedQuestionId);
  const visualAsset = selectedDetail?.visual_assets.find(asset => ["student_visual_answer", "student_visual_answer_asset"].includes(String(asset.role || "").toLowerCase()));
  const visualUrl = visualAsset && selectedSubmission ? `${apiBase}/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(selectedSubmission.id)}/questions/${encodeURIComponent(selectedQuestionId)}/visual-assets/${encodeURIComponent(String(visualAsset.asset_id))}` : "";
  return <section aria-label="学生答案の原画像と読み取り内容" className="student-answer-workspace-section">
    <div className="student-selection"><label>学生を選択<input aria-label="学生を検索" placeholder="学籍番号・氏名で検索" value={search} onChange={e => setSearch(e.target.value)} list="student-options" /><datalist id="student-options">{filtered.map(s => <option key={s.id} value={`${displayLabel(s)} / 答案${s.attempt_number}回目`} />)}</datalist><select aria-label="学生一覧" value={selectedSubmission?.id || ""} onChange={e => setSelectedId(e.target.value)}>{filtered.map(s => <option key={s.id} value={s.id}>{displayLabel(s)} / 答案{s.attempt_number}回目</option>)}</select></label><button type="button" className="button secondary" disabled={selectedIndex <= 0} onClick={() => moveStudent(-1)}>← 前の学生</button><button type="button" className="button secondary" disabled={selectedIndex >= orderedSubmissions.length - 1} onClick={() => moveStudent(1)}>次の学生 →</button></div>
    {selectedSubmission && <p className="muted selected-student-summary">{displayLabel(selectedSubmission)}　·　答案 {selectedSubmission.attempt_number}回目　·　{identityFor(selectedSubmission.id).review_required ? "学生情報を確認" : friendlyStatus(selectedSubmission.status)}</p>}
    <div className="student-answer-workspace"><section className="student-answer-preview-pane" aria-label="選択中の学生の原答案"><h2>原答案</h2>{error && <TechnicalDetails label="詳細を表示"><p>{error}</p></TechnicalDetails>}{page && selectedSubmission ? <div className="student-inline-viewer"><div className="student-inline-toolbar"><button type="button" className="button secondary" disabled={pageNumber <= 0} onClick={() => movePage(-1)}>← 前のページ</button><span>{pageNumber + 1} / {pageIndex?.page_count || 1}ページ</span><button type="button" className="button secondary" disabled={pageNumber >= (pageIndex?.pages.length || 1) - 1} onClick={() => movePage(1)}>次のページ →</button><span className="inline-zoom-label">倍率 {Math.round(zoom * 100)}%</span><button type="button" className="button secondary" onClick={() => setZoom(value => Math.max(.6, Number((value - .2).toFixed(1))))} aria-label="縮小">−</button><button type="button" className="button secondary" onClick={() => setZoom(1)}>100%</button><button type="button" className="button secondary" onClick={() => setZoom(value => Math.min(2.4, Number((value + .2).toFixed(1))))} aria-label="拡大">＋</button></div><div className="student-inline-canvas"><img className="student-inline-image" src={sourceUrl} alt={`${displayLabel(selectedSubmission)}の原答案`} style={{transform: `scale(${zoom})`}} /></div></div> : <p className="muted">原答案を読み込み中…</p>}</section>
      <section className="student-answer-reading" aria-label="現在の読み取り内容"><h2>現在の読み取り内容</h2><p className="muted">選択中の学生の答案だけを表示しています。</p>{detailRows.length ? <><label className="question-reading-selector">設問を選択<select aria-label="設問を選択" value={selectedQuestionId} onChange={e => setSelectedQuestionId(e.target.value)}>{detailRows.map(row => <option key={row.question.id} value={row.question.id}>{questionLabel(row.question.id)}</option>)}</select></label>{selectedDetail ? <article className="selected-answer-reading"><h3>{questionLabel(selectedQuestionId)}</h3>{selectedDetail.student_answer.answer_text?.trim() ? <pre className="answer-text">{selectedDetail.student_answer.answer_text}</pre> : visualUrl ? <><p className="muted">図・グラフ答案</p><img className="student-visual-answer-preview" src={visualUrl} alt={`${questionLabel(selectedQuestionId)}の図・グラフ答案`} /></> : <p className="muted">読み取り内容はまだありません。</p>}<span className="badge">{selectedDetail.authoritative ? "採点済み" : selectedDetail.student_answer.answer_text || visualUrl ? "読み取り済み" : "要確認"}</span></article> : null}</> : <p className="muted">読み取り内容を読み込み中…</p>}{runs.length > 0 && <TechnicalDetails label="技術情報を表示"><p>読み取り履歴 {runs.length}件</p>{runs.map(run => <p key={run.id}>{run.status} · {run.pipeline_version}</p>)}</TechnicalDetails>}</section></div>
  </section>;
}
