"use client";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/currentUser";
import { ErrorState } from "@/components/ui";

export default function ChangePasswordPage() {
  const router = useRouter(); const { refresh } = useAuth(); const [current,setCurrent]=useState(""); const [next,setNext]=useState(""); const [confirm,setConfirm]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setError(""); if (next !== confirm) { setError("新しいパスワードが一致しません"); return; } setBusy(true); try { await apiFetch("/auth/change-password", {method:"POST",body:JSON.stringify({current_password:current,new_password:next})}); await refresh(); router.replace("/"); } catch(e) { setError(e instanceof Error ? e.message : "パスワードを変更できませんでした"); } finally { setBusy(false); } }
  return <main className="login-page"><section className="panel login-card"><h1>パスワード変更</h1><p className="muted">初回ログインのため、新しいパスワードを設定してください（8文字以上）。</p>{error&&<ErrorState message={error}/>}<form className="form" onSubmit={submit}><div className="field"><label htmlFor="current-password">現在のパスワード</label><input id="current-password" type="password" required value={current} onChange={e=>setCurrent(e.target.value)}/></div><div className="field"><label htmlFor="new-password">新しいパスワード</label><input id="new-password" type="password" minLength={8} required value={next} onChange={e=>setNext(e.target.value)}/></div><div className="field"><label htmlFor="confirm-password">新しいパスワード（確認）</label><input id="confirm-password" type="password" minLength={8} required value={confirm} onChange={e=>setConfirm(e.target.value)}/></div><button className="button" disabled={busy}>{busy?"保存中…":"変更する"}</button></form></section></main>;
}
