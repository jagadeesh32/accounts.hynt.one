/**
 * The accounts SPA is same-origin with its API, so requests carry the SSO
 * cookie and nothing else — there is no bearer token on this side of the estate.
 */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError((data as { detail?: string }).detail || `Request failed (${response.status})`, response.status);
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

export interface Me {
  id: string;
  email: string;
  full_name: string;
  status: string;
  is_superadmin: boolean;
  mfa_enabled: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface PlatformTile {
  slug: string;
  name: string;
  description: string;
  icon: string;
  url: string;
  member: boolean;
  role: string | null;
  plan: string | null;
  plan_status: string | null;
  entitlements: string[];
}

export interface SessionRow {
  id: string;
  current: boolean;
  user_agent: string | null;
  ip: string | null;
  created_at: string;
  last_seen_at: string;
}
