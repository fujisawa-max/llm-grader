"use client";
import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/currentUser";
import { ErrorState } from "@/components/ui";

function LoginForm() {
  const router = useRouter(); const params = useSearchParams(); const { refresh } = useAuth();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }); await refresh(); router.replace(params.get("next") || "/"); } catch (e) { setError(e instanceof Error ? e.message : "ログインに失敗しました"); } finally { setBusy(false); } }
  return <main className="login-page"><section className="panel login-card"><h1>ログイン</h1><p className="muted">教員・管理者アカウントでログインしてください。</p>{error && <ErrorState message={error}/>}<form className="form" onSubmit={submit}><div className="field"><label htmlFor="email">メールアドレス</label><input id="email" type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></div><div className="field"><label htmlFor="password">パスワード</label><input id="password" type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></div><button className="button" disabled={busy}>{busy ? "ログイン中…" : "ログイン"}</button></form></section></main>;
}

export default function LoginPage() {
  return <Suspense fallback={<main className="login-page"><section className="panel login-card">読み込み中…</section></main>}><LoginForm /></Suspense>;
}
