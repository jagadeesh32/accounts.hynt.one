/**
 * API client for accounts.hynt.one.
 *
 * Every call is same-origin and credentialed — the SSO cookie is HttpOnly, so
 * the browser attaches it and this code never sees it. That is deliberate: a
 * session token JavaScript can read is a session token XSS can steal.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : {};

  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.error ?? "error",
      data.message ?? `Request failed (${response.status})`,
      data,
    );
  }
  return data as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

// --------------------------------------------------------------------- types
export interface User {
  id: string;
  email: string;
  email_verified: boolean;
  full_name: string;
  avatar_url: string | null;
  status: "active" | "pending" | "suspended";
  is_superadmin: boolean;
  mfa_enabled: boolean;
  org_id: string;
  last_login_at: string | null;
  created_at: string;
}

export interface Platform {
  id: string;
  slug: string;
  name: string;
  description: string;
  base_url: string;
  icon: string;
  active: boolean;
  sort_order: number;
}

export interface Plan {
  id: string;
  platform_id: string;
  code: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
  interval: string;
  trial_days: number;
  features: string[];
  limits: Record<string, unknown>;
  entitlements: string[];
  is_default: boolean;
  active: boolean;
  sort_order: number;
}

export interface Subscription {
  id: string;
  platform_id: string;
  plan: Plan;
  status: string;
  started_at: string;
  current_period_end: string | null;
  canceled_at: string | null;
}

export interface AccessEntry {
  platform: Platform;
  role: string;
  rank: number;
  permissions: string[];
  active: boolean;
  subscription: Subscription | null;
}

export interface SessionRow {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string;
  rank: number;
  is_default: boolean;
  permissions: string[];
}

export interface Membership {
  id: string;
  user_id: string;
  platform: Platform;
  role: Role;
  active: boolean;
  extra_permissions: string[];
  created_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor_user_id: string | null;
  target_type: string | null;
  target_id: string | null;
  platform_slug: string | null;
  ip_address: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ActivityEntry extends AuditEntry {
  user_agent?: string | null;
  outcome?: "success" | "failed" | "logout";
}

export interface UserOverview {
  user: User;
  organization: { id: string; name: string; slug: string } | null;
  access: { membership: Membership; subscription: Subscription | null }[];
  sessions: SessionRow[];
  active_refresh_tokens: number;
  token_version: number;
  recent_activity: ActivityEntry[];
}

export interface EstateOverview {
  users: { total: number; suspended: number };
  sessions: { live: number };
  logins_24h: { success: number; failed: number };
  platforms: (Platform & { member_count: number; subscription_count: number })[];
  revocations_live: number;
}

export interface SessionState {
  authenticated: boolean;
  user?: User;
  access?: AccessEntry[];
  session?: SessionRow;
}

// ------------------------------------------------------------------ endpoints
export const api = {
  session: () => get<SessionState>("/api/v1/auth/session"),
  login: (email: string, password: string) =>
    post<{ user: User; access: AccessEntry[] }>("/api/v1/auth/login", { email, password }),
  logout: () => post<{ ok: boolean }>("/api/v1/auth/logout"),
  register: (email: string, password: string, full_name: string) =>
    post<{ user: User; access: AccessEntry[] }>("/api/v1/auth/register", {
      email,
      password,
      full_name,
    }),
  forgotPassword: (email: string) =>
    post<{ ok: boolean; message: string; reset_token?: string }>("/api/v1/auth/password/forgot", {
      email,
    }),
  resetPassword: (token: string, password: string) =>
    post<{ ok: boolean; message: string }>("/api/v1/auth/password/reset", { token, password }),
  changePassword: (current_password: string, new_password: string) =>
    post<{ ok: boolean; sessions_revoked: number }>("/api/v1/auth/password/change", {
      current_password,
      new_password,
    }),

  me: () => get<{ user: User }>("/api/v1/me"),
  updateMe: (body: { full_name?: string; avatar_url?: string }) =>
    patch<{ user: User }>("/api/v1/me", body),
  myAccess: () => get<{ access: AccessEntry[]; is_superadmin: boolean }>("/api/v1/me/access"),
  mySessions: () => get<{ sessions: SessionRow[] }>("/api/v1/me/sessions"),
  endSession: (id: string) => del<{ ok: boolean }>(`/api/v1/me/sessions/${id}`),
  revokeAllSessions: () =>
    post<{ ok: boolean; sessions_revoked: number }>("/api/v1/me/sessions/revoke-all"),

  platforms: () => get<{ platforms: Platform[] }>("/api/v1/platforms"),
  publicPlans: (slug: string) =>
    get<{ platform: Platform; plans: Plan[] }>(`/api/v1/platforms/${slug}/plans`),

  admin: {
    users: (params: { q?: string; limit?: number; offset?: number } = {}) => {
      const search = new URLSearchParams();
      if (params.q) search.set("q", params.q);
      search.set("limit", String(params.limit ?? 50));
      search.set("offset", String(params.offset ?? 0));
      return get<{ users: User[]; total: number; limit: number; offset: number }>(
        `/api/v1/admin/users?${search}`,
      );
    },
    user: (id: string) =>
      get<{
        user: User;
        memberships: Membership[];
        subscriptions: Subscription[];
        sessions: number;
      }>(`/api/v1/admin/users/${id}`),
    createUser: (body: {
      email: string;
      password?: string;
      full_name?: string;
      is_superadmin?: boolean;
    }) => post<{ user: User; activation_token?: string }>("/api/v1/admin/users", body),
    updateUser: (id: string, body: Record<string, unknown>) =>
      patch<{ user: User }>(`/api/v1/admin/users/${id}`, body),
    revokeUserSessions: (id: string) =>
      post<{ ok: boolean; sessions_revoked: number }>(`/api/v1/admin/users/${id}/revoke-sessions`),

    platforms: () =>
      get<{ platforms: (Platform & { roles: Role[]; member_count: number })[] }>(
        "/api/v1/admin/platforms",
      ),
    members: (slug: string, offset = 0) =>
      get<{
        members: { membership: Membership; user: User | null; subscription: Subscription | null }[];
        total: number;
      }>(`/api/v1/admin/platforms/${slug}/members?offset=${offset}&limit=50`),
    addMember: (slug: string, email: string, role: string) =>
      post<{ membership: Membership }>(`/api/v1/admin/platforms/${slug}/members`, { email, role }),
    updateMember: (slug: string, userId: string, body: Record<string, unknown>) =>
      patch<{ membership: Membership }>(
        `/api/v1/admin/platforms/${slug}/members/${userId}`,
        body,
      ),
    removeMember: (slug: string, userId: string) =>
      del<{ ok: boolean }>(`/api/v1/admin/platforms/${slug}/members/${userId}`),
    setSubscription: (slug: string, userId: string, plan: string, status?: string) =>
      put<{ subscription: Subscription }>(
        `/api/v1/admin/platforms/${slug}/members/${userId}/subscription`,
        status ? { plan, status } : { plan },
      ),

    plans: (slug: string) => get<{ plans: Plan[] }>(`/api/v1/admin/platforms/${slug}/plans`),
    updatePlan: (slug: string, planId: string, body: Record<string, unknown>) =>
      patch<{ plan: Plan }>(`/api/v1/admin/platforms/${slug}/plans/${planId}`, body),

    // --- superadmin: total control over one account ---
    overview: () => get<EstateOverview>("/api/v1/admin/overview"),
    userOverview: (id: string) => get<UserOverview>(`/api/v1/admin/users/${id}/overview`),
    userActivity: (id: string, params: { offset?: number; action?: string; days?: number } = {}) => {
      const search = new URLSearchParams();
      search.set("limit", "50");
      search.set("offset", String(params.offset ?? 0));
      if (params.action) search.set("action", params.action);
      if (params.days) search.set("days", String(params.days));
      return get<{ user: User; entries: ActivityEntry[]; total: number }>(
        `/api/v1/admin/users/${id}/activity?${search}`,
      );
    },
    userLogins: (id: string, offset = 0) =>
      get<{ logins: ActivityEntry[]; total: number }>(
        `/api/v1/admin/users/${id}/logins?offset=${offset}&limit=50`,
      ),
    userSessions: (id: string) =>
      get<{ sessions: SessionRow[]; token_version: number }>(`/api/v1/admin/users/${id}/sessions`),
    endUserSession: (id: string, sessionId: string) =>
      del<{ ok: boolean }>(`/api/v1/admin/users/${id}/sessions/${sessionId}`),
    revokeAll: (id: string, reason: string) =>
      post<{ ok: boolean; sessions_ended: number; token_version: number; note: string }>(
        `/api/v1/admin/users/${id}/revoke`,
        { reason },
      ),
    revokePlatform: (id: string, slug: string) =>
      post<{ ok: boolean; platform: string }>(`/api/v1/admin/users/${id}/platforms/${slug}/revoke`),
    grantPlatform: (id: string, slug: string, role: string, plan?: string) =>
      post<{ ok: boolean; membership: Membership }>(
        `/api/v1/admin/users/${id}/platforms/${slug}/grant`,
        plan ? { role, plan } : { role },
      ),
    deleteUser: (id: string, confirmEmail: string) =>
      request<{ ok: boolean; deleted: string }>(`/api/v1/admin/users/${id}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm_email: confirmEmail }),
      }),

    audit: (params: { limit?: number; offset?: number; action?: string; platform?: string } = {}) => {
      const search = new URLSearchParams();
      search.set("limit", String(params.limit ?? 50));
      search.set("offset", String(params.offset ?? 0));
      if (params.action) search.set("action", params.action);
      if (params.platform) search.set("platform", params.platform);
      return get<{ entries: AuditEntry[]; total: number }>(`/api/v1/admin/audit?${search}`);
    },
  },
};
