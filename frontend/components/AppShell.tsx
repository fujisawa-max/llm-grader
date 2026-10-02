"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/lib/currentUser";

const storageKey = "llm-grader-navigation-collapsed";

export function AppShell({ children }: { children: ReactNode }) {
  const appName = process.env.NEXT_PUBLIC_APP_NAME || "AI採点支援システム";
  const { user, loading, logout } = useAuth();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => { setCollapsed(window.localStorage.getItem(storageKey) === "true"); }, []);
  const toggle = () => setCollapsed((current) => {
    window.localStorage.setItem(storageKey, String(!current));
    return !current;
  });
  const roleLabel = user?.role === "admin" ? "管理者" : user?.role === "teacher" ? "教員" : "学生";
  const section = pathname.startsWith("/model-answer-import-reviews") ? "模範解答"
    : pathname.startsWith("/question-import-reviews") ? "問題"
      : pathname.startsWith("/tests") ? "試験"
        : pathname.startsWith("/courses") ? "科目"
          : pathname.startsWith("/admin") ? "管理" : "ホーム";
  if (!loading && !user) return <main>{children}</main>;
  const items = [
    { href: "/", label: "ホーム", icon: "⌂", active: pathname === "/" },
    { href: "/courses", label: "科目", icon: "▤", active: pathname.startsWith("/courses") },
    ...(user?.role === "admin" ? [{ href: "/admin/users", label: "ユーザ管理", icon: "♙", active: pathname.startsWith("/admin") }] : []),
  ];
  return <div className="shell">
    <header className="header"><Link href="/" className="brand">{appName}</Link><span className="context">授業運用ワークスペース</span>
      {user && <><span className="user-label">{user.display_name}（{roleLabel}）</span><button className="button secondary" type="button" onClick={() => void logout()}>ログアウト</button></>}
    </header>
    <div className="body"><aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <button type="button" className="sidebar-toggle" aria-label={collapsed ? "ナビゲーションを展開" : "ナビゲーションを折りたたむ"} aria-expanded={!collapsed} onClick={toggle}>
        <span aria-hidden="true">{collapsed ? "»" : "«"}</span><span className="sidebar-label">{collapsed ? "展開" : "折りたたむ"}</span>
      </button>
      <nav aria-label="メインナビゲーション">
        {items.map((item) => <Link key={item.href} href={item.href} title={item.label} aria-label={item.label} aria-current={item.active ? "page" : undefined}>
          <span className="sidebar-icon" aria-hidden="true">{item.icon}</span><span className="sidebar-label">{item.label}</span>
        </Link>)}
      </nav>
      <p className="sidebar-current" aria-label={`現在の画面: ${section}`} title={`現在の画面: ${section}`}><span aria-hidden="true">●</span><span className="sidebar-label">{section}</span></p>
    </aside><main className={`main ${pathname.startsWith("/model-answer-import-reviews") ? "main-review-wide" : ""}`}>{children}</main></div>
  </div>;
}
