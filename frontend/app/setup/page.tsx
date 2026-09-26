"use client";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import { ErrorState } from "@/components/ui";

export default function SetupPage() {
  const router = useRouter(); const [started,setStarted] = useState(false); const [done,setDone] = useState(false);
  const [name,setName] = useState(""); const [email,setEmail] = useState(""); const [password,setPassword] = useState(""); const [confirm,setConfirm] = useState(""); const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function submit(e: FormEvent) { e.preventDefault(); setError(""); if(password !== confirm){setError("パスワードが一致しません");return;} setBusy(true); try { await apiFetch("/setup/initialize",{method:"POST",body:JSON.stringify({display_name:name,email,password})}); setDone(true); } catch(e) { setError(e instanceof Error ? e.message : "初期設定に失敗しました"); } finally { setBusy(false); } }
  return <main className="login-page"><section className="panel login-card"><h1>自動採点システムの初期設定</h1>{done ? <><p>初期設定が完了しました。</p><button className="button" onClick={()=>router.replace("/login")}>ログインへ進む</button></> : !started ? <><p className="muted">最初の管理者アカウントを作成します。この操作は通常、初回起動時のみ実行します。</p><button className="button" onClick={()=>setStarted(true)}>初期設定を開始</button></> : <><p className="muted">最初の管理者アカウントを登録してください。</p>{error&&<ErrorState message={error}/>}<form className="form" onSubmit={submit}><div className="field"><label htmlFor="setup-name">氏名</label><input id="setup-name" required value={name} onChange={e=>setName(e.target.value)}/></div><div className="field"><label htmlFor="setup-email">メールアドレス</label><input id="setup-email" type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></div><div className="field"><label htmlFor="setup-password">パスワード</label><input id="setup-password" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)}/></div><div className="field"><label htmlFor="setup-confirm">パスワード（確認）</label><input id="setup-confirm" type="password" required minLength={8} autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)}/></div><button className="button" disabled={busy}>{busy?"作成中…":"管理者を作成"}</button></form></>}</section></main>;
}
