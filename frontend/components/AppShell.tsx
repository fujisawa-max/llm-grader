"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/currentUser";

export function AppShell({ children }: { children: ReactNode }) {
  const appName = process.env.NEXT_PUBLIC_APP_NAME || "AI採点支援システム";
  const { user, loading, logout } = useAuth();
  const roleLabel = user?.role === "admin" ? "管理者" : user?.role === "teacher" ? "教員" : "学生";
  if (!loading && !user) return <main>{children}</main>;
  return <div className="shell"><header className="header"><Link href="/" className="brand">{appName}</Link><span className="context">授業運用ワークスペース</span>{user && <><span className="user-label">{user.display_name}（{roleLabel}）</span><button className="button secondary" type="button" onClick={() => void logout()}>ログアウト</button></>}</header><div className="body"><aside className="sidebar"><nav aria-label="メインナビゲーション"><Link href="/">ホーム</Link><Link href="/courses">科目</Link><span className="disabled">採点（テストから開く）</span><span className="disabled">要確認（テストから開く）</span>{user?.role === "admin" && <Link href="/admin/users">ユーザ管理</Link>}</nav></aside><main className="main">{children}</main></div></div>;
}
