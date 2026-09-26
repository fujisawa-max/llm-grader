"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import type { User } from "@/types/domain";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}
const AuthContext = createContext<AuthContextValue>({ user: null, loading: true, refresh: async () => {}, logout: async () => {} });

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = async () => {
    try { setUser(await apiFetch<User>("/auth/me")); }
    catch { setUser(null); }
    finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener("llm-grader-auth-expired", expired);
    return () => window.removeEventListener("llm-grader-auth-expired", expired);
  }, []);
  useEffect(() => {
    if (!loading && !user && pathname !== "/login" && pathname !== "/setup") {
      fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1"}/setup/status`, { credentials: "include", cache: "no-store" })
        .then(r => r.json()).then(v => router.replace(v.setup_required ? "/setup" : `/login?next=${encodeURIComponent(pathname || "/")}`))
        .catch(() => router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`));
    }
    if (!loading && !user && pathname === "/login") {
      fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1"}/setup/status`, { credentials: "include", cache: "no-store" })
        .then(r => r.json()).then(v => { if (v.setup_required) router.replace("/setup"); });
    }
    if (!loading && !user && pathname === "/setup") {
      fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1"}/setup/status`, { credentials: "include", cache: "no-store" })
        .then(r => r.json()).then(v => { if (!v.setup_required) router.replace("/login"); });
    }
    if (!loading && user && pathname === "/login") router.replace(user.must_change_password ? "/change-password" : "/");
    if (!loading && user?.must_change_password && pathname !== "/change-password" && pathname !== "/login") router.replace("/change-password");
  }, [loading, user, pathname, router]);
  const logout = async () => { try { await apiFetch("/auth/logout", { method: "POST" }); } finally { setUser(null); router.replace("/login"); } };
  return <AuthContext.Provider value={{ user, loading, refresh, logout }}>{children}</AuthContext.Provider>;
}
export function useAuth() { return useContext(AuthContext); }
export function useCurrentUser() { return useContext(AuthContext).user; }
