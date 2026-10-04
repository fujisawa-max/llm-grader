import type { ApiError } from "@/types/domain";

const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "");
export class ApiRequestError extends Error {
  status: number; code?: string; details?: unknown; routeNotFound: boolean;
  constructor(status: number, body: ApiError) {
    super(body.error?.message || "通信に失敗しました");
    this.status = status; this.code = body.error?.code; this.details = body.error?.details;
    this.routeNotFound = status === 404 && ((body as ApiError & {detail?: unknown}).detail === "Not Found"
      || (body.error?.code === "http_error" && body.error?.message === "Not Found"));
  }
}
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const studentPath = path.startsWith("/student/");
  const identityHeaders: Record<string, string> = studentPath && process.env.NEXT_PUBLIC_STUDENT_ID
    ? { "X-Role": "student", "X-Student-ID": process.env.NEXT_PUBLIC_STUDENT_ID } : {};
  const response = await fetch(`${base}${path.startsWith("/") ? path : `/${path}`}`, { ...init,
    credentials: "include", headers: { "Content-Type": "application/json", ...identityHeaders, ...(init?.headers || {}) }, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("llm-grader-auth-expired"));
    }
    throw new ApiRequestError(response.status, body);
  }
  return body as T;
}
export const json = (value: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(value) });
