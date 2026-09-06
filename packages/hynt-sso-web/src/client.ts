/**
 * Browser SSO client for a Hynt platform SPA.
 *
 * The access token is held in memory only — never in localStorage. Renewal goes
 * through a hidden iframe hitting `/oauth/authorize?prompt=none`, which succeeds
 * against the `hynt_sso` cookie on `.hynt.one` and needs no long-lived
 * credential in the page. A tab that is reloaded gets a new token the same way,
 * silently, before it renders.
 */
import { challengeFor, decodeJwt, randomString } from "./pkce";
import type { AccessClaims, HyntSsoConfig, HyntUser, TokenResponse } from "./types";

const VERIFIER_KEY = "hynt.pkce.verifier";
const STATE_KEY = "hynt.pkce.state";
const RETURN_KEY = "hynt.return_to";

/** sessionStorage, not localStorage: the verifier is valid for one redirect and
 *  must not outlive the tab or leak to another one. */
function stash(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* private mode — the redirect will fail loudly rather than silently */
  }
}

function take(key: string): string | null {
  try {
    const value = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    return value;
  } catch {
    return null;
  }
}

function toUser(claims: AccessClaims): HyntUser {
  return {
    id: claims.sub,
    email: claims.email,
    name: claims.name,
    orgId: claims.org,
    role: claims.role,
    rank: claims.rank,
    permissions: claims.perms ?? [],
    plan: claims.plan,
    planStatus: claims.plan_status,
    entitlements: claims.ent ?? [],
    limits: claims.lim ?? {},
    emailVerified: claims.email_verified,
  };
}

const ROLE_RANK: Record<string, number> = { superadmin: 40, admin: 30, staff: 20, user: 10 };

export class HyntSso {
  private readonly config: Required<Pick<HyntSsoConfig, "scope" | "renewSkewSeconds">> &
    HyntSsoConfig;

  private accessToken: string | null = null;
  private claims: AccessClaims | null = null;
  private renewTimer: ReturnType<typeof setTimeout> | null = null;
  /** In-flight renewal, so ten concurrent 401s trigger one renewal, not ten. */
  private renewal: Promise<boolean> | null = null;

  constructor(config: HyntSsoConfig) {
    this.config = {
      scope: "openid profile email",
      renewSkewSeconds: 60,
      ...config,
      issuer: config.issuer.replace(/\/$/, ""),
    };
  }

  // ------------------------------------------------------------------ state
  get token(): string | null {
    return this.accessToken;
  }

  get user(): HyntUser | null {
    return this.claims ? toUser(this.claims) : null;
  }

  get isAuthenticated(): boolean {
    return this.accessToken !== null && !this.isExpired();
  }

  hasRole(minimum: string): boolean {
    return (this.claims?.rank ?? 0) >= (ROLE_RANK[minimum] ?? 999);
  }

  hasPermission(code: string): boolean {
    const perms = this.claims?.perms ?? [];
    if (perms.includes("*") || perms.includes(code)) return true;
    return perms.includes(`${code.split(":")[0]}:*`);
  }

  hasEntitlement(code: string): boolean {
    const status = this.claims?.plan_status;
    if (status !== "active" && status !== "trialing") return false;
    return (this.claims?.ent ?? []).includes(code);
  }

  limit<T = unknown>(key: string, fallback: T): T {
    const value = this.claims?.lim?.[key];
    return value === undefined ? fallback : (value as T);
  }

  private isExpired(skew = 0): boolean {
    if (!this.claims) return true;
    return Date.now() / 1000 >= this.claims.exp - skew;
  }

  // ------------------------------------------------------------------- flow
  /** Send the browser to accounts.hynt.one to sign in. */
  async signIn(options: { returnTo?: string; prompt?: "login" } = {}): Promise<void> {
    const url = await this.authorizeUrl({ prompt: options.prompt });
    stash(RETURN_KEY, options.returnTo ?? window.location.pathname + window.location.search);
    window.location.assign(url);
  }

  private async authorizeUrl(options: { prompt?: string } = {}): Promise<string> {
    const verifier = randomString();
    const state = randomString(16);
    stash(VERIFIER_KEY, verifier);
    stash(STATE_KEY, state);

    const params = new URLSearchParams({
      client_id: this.config.clientId,
      redirect_uri: this.config.redirectUri,
      response_type: "code",
      scope: this.config.scope,
      state,
      code_challenge: await challengeFor(verifier),
      code_challenge_method: "S256",
    });
    if (options.prompt) params.set("prompt", options.prompt);
    return `${this.config.issuer}/oauth/authorize?${params}`;
  }

  /**
   * Complete the redirect. Call this on the callback route.
   * Returns where the app should navigate next.
   */
  async handleCallback(): Promise<{ user: HyntUser; returnTo: string }> {
    const params = new URLSearchParams(window.location.search);
    const error = params.get("error");
    if (error) {
      throw new Error(params.get("error_description") || error);
    }

    const code = params.get("code");
    const returnedState = params.get("state");
    const verifier = take(VERIFIER_KEY);
    const expectedState = take(STATE_KEY);
    const returnTo = take(RETURN_KEY) ?? "/";

    if (!code || !verifier) throw new Error("The sign-in response was incomplete.");
    // CSRF on the callback: without this check another site can complete the
    // flow in this tab using a code it obtained.
    if (!expectedState || returnedState !== expectedState) {
      throw new Error("The sign-in response did not match this request.");
    }

    await this.exchange(code, verifier);
    if (!this.claims) throw new Error("The sign-in response was incomplete.");
    return { user: toUser(this.claims), returnTo };
  }

  private async exchange(code: string, verifier: string): Promise<void> {
    const response = await fetch(`${this.config.issuer}/oauth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        client_id: this.config.clientId,
        code,
        code_verifier: verifier,
        redirect_uri: this.config.redirectUri,
      }),
    });

    const data = (await response.json()) as TokenResponse & { error_description?: string };
    if (!response.ok) throw new Error(data.error_description || "Sign-in failed.");

    this.adopt(data.access_token);
  }

  private adopt(token: string): void {
    this.accessToken = token;
    this.claims = decodeJwt<AccessClaims>(token);
    this.scheduleRenewal();
  }

  // ---------------------------------------------------------------- renewal
  /**
   * Try to obtain a token without user interaction.
   *
   * Call once at startup: it is how a page reload stays signed in, and how a
   * user who signed in on a sibling platform is already signed in here.
   */
  async silentSignIn(): Promise<boolean> {
    if (this.renewal) return this.renewal;
    this.renewal = this.runSilent().finally(() => {
      this.renewal = null;
    });
    return this.renewal;
  }

  private async runSilent(): Promise<boolean> {
    let url: string;
    try {
      url = await this.authorizeUrl({ prompt: "none" });
    } catch {
      return false;
    }

    const result = await new Promise<{ code?: string; state?: string; error?: string }>(
      (resolve) => {
        const frame = document.createElement("iframe");
        frame.style.display = "none";
        // A timeout is required: if the iframe never lands on our origin (a
        // network stall, a proxy interstitial), the promise would otherwise
        // never settle and the app would hang on a blank screen forever.
        const timer = setTimeout(() => finish({ error: "timeout" }), 12_000);

        const onMessage = (event: MessageEvent) => {
          if (event.origin !== window.location.origin) return;
          if (!event.data || event.data.type !== "hynt-sso-callback") return;
          finish(event.data.payload);
        };

        function finish(payload: { code?: string; state?: string; error?: string }) {
          clearTimeout(timer);
          window.removeEventListener("message", onMessage);
          frame.remove();
          resolve(payload);
        }

        window.addEventListener("message", onMessage);
        frame.src = url;
        document.body.appendChild(frame);
      },
    );

    const verifier = take(VERIFIER_KEY);
    const expectedState = take(STATE_KEY);

    if (result.error || !result.code || !verifier) return false;
    if (!expectedState || result.state !== expectedState) return false;

    try {
      await this.exchange(result.code, verifier);
      return true;
    } catch {
      return false;
    }
  }

  private scheduleRenewal(): void {
    if (this.renewTimer) clearTimeout(this.renewTimer);
    if (!this.claims) return;

    const seconds = this.claims.exp - Date.now() / 1000 - this.config.renewSkewSeconds;
    this.renewTimer = setTimeout(
      () => {
        void this.silentSignIn().then((ok) => {
          if (!ok) this.handleSignedOut();
        });
      },
      Math.max(seconds, 5) * 1000,
    );
  }

  private handleSignedOut(): void {
    this.accessToken = null;
    this.claims = null;
    if (this.renewTimer) clearTimeout(this.renewTimer);
    this.config.onSignedOut?.();
  }

  // ----------------------------------------------------------------- logout
  /** End the session everywhere, not just in this app. */
  signOut(): void {
    const params = new URLSearchParams({ client_id: this.config.clientId });
    if (this.config.postLogoutRedirectUri) {
      params.set("post_logout_redirect_uri", this.config.postLogoutRedirectUri);
    }
    this.handleSignedOut();
    window.location.assign(`${this.config.issuer}/oauth/logout?${params}`);
  }

  // ------------------------------------------------------------------ fetch
  /**
   * `fetch` with the bearer token attached, renewing once on a 401.
   *
   * The retry matters: a token that expired between the check and the request
   * would otherwise surface to the user as a random failure.
   */
  async fetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    if (!this.accessToken || this.isExpired(10)) {
      await this.silentSignIn();
    }

    const send = async (): Promise<Response> => {
      const headers = new Headers(init.headers);
      if (this.accessToken) headers.set("Authorization", `Bearer ${this.accessToken}`);
      return fetch(input, { ...init, headers });
    };

    let response = await send();
    if (response.status === 401) {
      if (await this.silentSignIn()) {
        response = await send();
      } else {
        this.handleSignedOut();
      }
    }
    return response;
  }

  /** Patch `window.fetch` so widgets doing raw fetches are covered too.
   *
   * Scoped to same-origin `/api/` paths. A substring match on "/api/" would send
   * this desk's bearer token to any third-party URL that merely contained it. */
  installFetchInterceptor(pathPrefix = "/api/"): void {
    const original = window.fetch.bind(window);
    const self = this;

    window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const raw =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      let sameOriginApi = false;
      try {
        const resolved = new URL(raw, window.location.href);
        sameOriginApi =
          resolved.origin === window.location.origin && resolved.pathname.startsWith(pathPrefix);
      } catch {
        sameOriginApi = false;
      }
      if (!sameOriginApi) return original(input, init);
      return self.fetch(input, init);
    };
  }
}

/**
 * Run this on the callback page when it may be inside the silent-renewal iframe.
 * Returns true when it handled the message, so the app knows not to render.
 */
export function relaySilentCallback(): boolean {
  if (window.parent === window) return false;
  const params = new URLSearchParams(window.location.search);
  window.parent.postMessage(
    {
      type: "hynt-sso-callback",
      payload: {
        code: params.get("code") ?? undefined,
        state: params.get("state") ?? undefined,
        error: params.get("error") ?? undefined,
      },
    },
    window.location.origin,
  );
  return true;
}

export type { AccessClaims, HyntSsoConfig, HyntUser } from "./types";
