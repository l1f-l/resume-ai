import type {
  Application,
  ApplicationSummary,
  ApplicationStatus,
  Job,
  MatchReport,
  MatchResponse,
  SessionSummary,
  User,
} from "./types";

/** 直连 FastAPI（SSE 需要真正的流式，不经 Next 代理缓冲） */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

/** 预览 / 导出走同源代理：iframe 不跨域，下载能保留文件名 */
export const PROXY_BASE = "/backend";

const TOKEN_KEY = "rp_token";

// --------------------------------------------------------------------------- //
// 凭证
// --------------------------------------------------------------------------- //
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  // 同时写 Cookie：middleware 做路由守卫、iframe 预览与 <a download> 无法带自定义头
  document.cookie = `${"rp_token"}=${token}; path=/; max-age=${7 * 86400}; SameSite=Lax`;
}

export function clearToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem("rp_sid");
  document.cookie = `${"rp_token"}=; path=/; max-age=0; SameSite=Lax`;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: authHeaders(init.headers as Record<string, string> | undefined),
  });
  if (resp.status === 401 && typeof window !== "undefined") {
    clearToken();
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new Error("登录已过期，请重新登录");
  }
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    const err = new Error((detail as { detail?: string })?.detail || `请求失败（${resp.status}）`);
    (err as Error & { status?: number }).status = resp.status;
    throw err;
  }
  return resp.json() as Promise<T>;
}

// --------------------------------------------------------------------------- //
// 认证
// --------------------------------------------------------------------------- //
export interface AuthResult {
  token: string;
  user: User;
  expires_in: number;
}

export const register = (email: string, password: string, display_name = "") =>
  req<AuthResult>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name }),
  });

export const login = (email: string, password: string) =>
  req<AuthResult>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

export const me = () => req<User>("/api/auth/me");

// --------------------------------------------------------------------------- //
// 岗位
// --------------------------------------------------------------------------- //
export interface JobList {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

export const listJobs = (params: { q?: string; city?: string; seniority?: string; limit?: number; offset?: number } = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  });
  return req<JobList>(`/api/jobs${qs.toString() ? `?${qs}` : ""}`);
};

export const jobDetail = (jobId: string) => req<Job>(`/api/jobs/${jobId}`);

export const jobFilters = () =>
  req<{ cities: string[]; seniorities: string[]; total: number }>("/api/jobs/filters");

// --------------------------------------------------------------------------- //
// 匹配
// --------------------------------------------------------------------------- //
export const recommendJobs = (sid: string) =>
  req<MatchResponse>(`/api/sessions/${sid}/match`, { method: "POST" });

export const listMatches = (sid: string) =>
  req<{
    session_id: string;
    job_id: string;
    items: {
      job_id: string;
      title: string;
      company: string;
      city: string;
      seniority: string;
      salary: string;
      skills: string[];
      match_score: number;
      rank: number;
      reason: string;
      has_report: boolean;
    }[];
    pool_size: number;
  }>(`/api/sessions/${sid}/matches`);

export function currentReport(sid: string): Promise<MatchReport | null> {
  return getSession(sid).then((s) => (s.match_report as MatchReport | null) ?? null);
}

// --------------------------------------------------------------------------- //
// 投递
// --------------------------------------------------------------------------- //
export const applyToJob = (session_id: string, job_id: string, note = "") =>
  req<{
    application: Application;
    mail: { status: string; to: string; subject: string; error: string; preview: string; smtp_ready: boolean };
    note: string;
  }>("/api/applications", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, job_id, note }),
  });

export const listApplications = (status = "") =>
  req<{ items: Application[]; summary: ApplicationSummary; smtp_ready: boolean }>(
    `/api/applications${status ? `?status=${status}` : ""}`,
  );

export const updateApplication = (id: string, status: ApplicationStatus, note = "") =>
  req<{ application: Application }>(`/api/applications/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });

export const applicationEvents = (id: string) =>
  req<{ items: { from_status: string | null; to_status: string; note: string; created_at: number; label: string }[] }>(
    `/api/applications/${id}/events`,
  );

// --------------------------------------------------------------------------- //
// 会话
// --------------------------------------------------------------------------- //
export interface HealthInfo {
  status: string;
  llm_mode: "mock" | "deepseek";
  llm_label: string;
  model: string;
  llm: { mode: string; degraded: boolean; reason: string; last_error: string; has_key: boolean };
  ocr: { enabled: boolean; engines: string[]; min_chars: number };
  db: { path: string; sessions: number };
  rag: { backend: string; templates: number };
  jobs?: { total: number; index: string };
  mail?: { smtp_ready: boolean; host: string };
}

export async function health(): Promise<HealthInfo> {
  const r = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
  if (!r.ok) throw new Error("后端未就绪");
  return r.json();
}

/** 熔断后重连真实模型（401/402 修复后不必重启进程） */
export async function resetLlm() {
  const r = await fetch(`${API_BASE}/api/llm/reset`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!r.ok) throw new Error("重连失败");
  return r.json();
}

export async function uploadResume(file: File, jd: string, jobId = "") {
  const form = new FormData();
  form.append("file", file);
  form.append("jd", jd);
  if (jobId) form.append("job_id", jobId);
  const resp = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string })?.detail || `上传失败（${resp.status}）`);
  }
  return resp.json();
}

export const getSession = (sid: string) => req<SessionSummary>(`/api/sessions/${sid}`);

export const listSessions = (limit = 20) =>
  req<{ items: { id: string; stage: string; file_name: string; job_id: string | null; updated_at: number; created_at: number }[] }>(
    `/api/sessions?limit=${limit}`,
  );

export const deleteSession = (sid: string) =>
  req<{ ok: boolean }>(`/api/sessions/${sid}`, { method: "DELETE" });

// --------------------------------------------------------------------------- //
// SSE
// --------------------------------------------------------------------------- //
export interface SSEEvent {
  event: string;
  data: Record<string, any>;
}

/**
 * POST + text/event-stream 的解析器。
 * EventSource 只支持 GET，所以这里用 fetch + ReadableStream 手写帧解析。
 */
export async function* streamSSE(
  url: string,
  body?: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const resp = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: authHeaders(body ? { "Content-Type": "application/json" } : undefined),
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });

  if (resp.status === 401 && typeof window !== "undefined") {
    clearToken();
    window.location.href = "/login";
    throw new Error("登录已过期，请重新登录");
  }
  if (!resp.ok || !resp.body) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as { detail?: string })?.detail || `请求失败（${resp.status}）`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const parsed = parseBlock(block);
      if (parsed) yield parsed;
    }
  }
  const tail = parseBlock(buffer);
  if (tail) yield tail;
}

function parseBlock(block: string): SSEEvent | null {
  if (!block.trim()) return null;
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

export const previewUrl = (sid: string, variant: string, v: number) =>
  `${PROXY_BASE}/api/sessions/${sid}/preview?variant=${variant}&v=${v}`;

export const exportUrl = (sid: string, format: "html" | "pdf", variant = "optimized") =>
  `${PROXY_BASE}/api/sessions/${sid}/export?format=${format}&variant=${variant}`;

export const applyResumeUrl = (appId: string) =>
  `${PROXY_BASE}/api/applications/${appId}/resume`;
