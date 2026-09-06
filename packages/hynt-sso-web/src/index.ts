/**
 * Browser SDK for single sign-on against accounts.hynt.one.
 *
 * The token lives in memory for the lifetime of the tab — never localStorage.
 * A token in localStorage survives the tab, is readable by any script on the
 * page, and has to be long-lived to be worth keeping. Instead this renews
 * silently against the `hynt_sso` cookie on `.hynt.one`, which is HttpOnly and
 * therefore not reachable from script at all.
 */

export interface HyntUser {
  id: string;
  email: string;
  name: string;
  role: string;
  rank: number;
  permissions: string[];
  plan: string | null;
  /** camelCase on this side of the wire; the token endpoint sends plan_status. */
  planStatus: string | null;
  entitlements: string[];
  limits: Record<string, unknown>;
}

/** Exactly what /oauth/token returns, before it is normalised for the app. */
interface WireUser extends Omit<HyntUser, "planStatus"> {
  plan_status: string | null;
}

export interface HyntSsoOptions {
  issuer: string;
  clientId: string;
  redirectUri: string;
  postLogoutRedirectUri?: string;
  /** Called when renewal fails and a real sign-in is needed. */
  onSignedOut?: () => void;
  /** Renew this many seconds before expiry. */
  renewSkewSeconds?: number;
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
  user: WireUser;
}

const PENDING = "hynt_sso_pending";
const SILENT_MESSAGE = "hynt-sso:silent-result";

function base64UrlEncode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(bytes = 48): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return base64UrlEncode(buf);
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Call at the very top of the callback route. Returns true when the page is
 * running inside the hidden renewal iframe, in which case it has already
 * posted the result to the parent and the route should render nothing.
 */
export function relaySilentCallback(): boolean {
  if (window.parent === window) return false;
  const params = new URLSearchParams(window.location.search);
  if (!params.has("code") && !params.has("error")) return false;
  window.parent.postMessage(
    {
      type: SILENT_MESSAGE,
      code: params.get("code"),
      state: params.get("state"),
      error: params.get("error"),
    },
    window.location.origin,
  );
  return true;
}

export class HyntSso {
  readonly issuer: string;
  private opts: HyntSsoOptions;
  private accessToken: string | null = null;
  private currentUser: HyntUser | null = null;
  private expiresAt = 0;
  private renewTimer: ReturnType<typeof setTimeout> | null = null;
  private inFlight: Promise<boolean> | null = null;

  constructor(options: HyntSsoOptions) {
    this.opts = options;
    this.issuer = options.issuer.replace(/\/$/, "");
  }

  get token(): string | null {
    return this.accessToken;
  }

  get user(): HyntUser | null {
    return this.currentUser;
  }

  get isSignedIn(): boolean {
    return this.accessToken !== null && Date.now() < this.expiresAt;
  }

  hasPermission(code: string): boolean {
    return this.currentUser?.permissions.includes(code) ?? false;
  }

  hasEntitlement(code: string): boolean {
    return this.currentUser?.entitlements.includes(code) ?? false;
  }

  limit<T>(key: string, fallback: T): T {
    const value = this.currentUser?.limits?.[key];
    return (value === undefined ? fallback : value) as T;
  }

  /** Full-page redirect to the sign-in page. */
  async signIn(returnTo?: string): Promise<void> {
    const url = await this.authorizeUrl("login", returnTo ?? window.location.pathname + window.location.search);
    window.location.assign(url);
  }

  /**
   * Ask for a token without user interaction, in a hidden iframe against the
   * SSO cookie. Resolves false when a real sign-in is needed.
   */
  async silentSignIn(): Promise<boolean> {
    if (this.isSignedIn) return true;
    // Concurrent callers (a page render and a 401 retry) must not each open
    // their own iframe — the second code would invalidate the first.
    if (this.inFlight) return this.inFlight;
    this.inFlight = this.doSilentSignIn().finally(() => {
      this.inFlight = null;
    });
    return this.inFlight;
  }

  private async doSilentSignIn(): Promise<boolean> {
    const verifier = randomString();
    const state = randomString(16);
    const url = await this.buildAuthorizeUrl(verifier, state, "none");

    const result = await new Promise<{ code?: string | null; error?: string | null }>((resolve) => {
      const frame = document.createElement("iframe");
      frame.style.display = "none";
      frame.setAttribute("aria-hidden", "true");

      const done = (value: { code?: string | null; error?: string | null }) => {
        window.removeEventListener("message", onMessage);
        clearTimeout(timer);
        frame.remove();
        resolve(value);
      };

      const onMessage = (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data as { type?: string; code?: string; state?: string; error?: string };
        if (data?.type !== SILENT_MESSAGE) return;
        if (data.state !== state) return; // not our renewal
        done({ code: data.code, error: data.error });
      };

      // A renewal that never comes back must not hang the app forever: the
      // iframe is torn down and the caller falls through to a real sign-in.
      const timer = setTimeout(() => done({ error: "timeout" }), 10_000);

      window.addEventListener("message", onMessage);
      frame.src = url;
      document.body.appendChild(frame);
    });

    if (!result.code) {
      this.clear();
      this.opts.onSignedOut?.();
      return false;
    }

    try {
      await this.exchange(result.code, verifier);
      return true;
    } catch {
      this.clear();
      this.opts.onSignedOut?.();
      return false;
    }
  }

  /** Handles the redirect back from a real sign-in. */
  async handleCallback(): Promise<{ returnTo: string }> {
    const params = new URLSearchParams(window.location.search);
    const error = params.get("error");
    const code = params.get("code");
    const state = params.get("state");

    const rawPending = sessionStorage.getItem(PENDING);
    sessionStorage.removeItem(PENDING);

    if (error) throw new Error(this.describe(error));
    if (!code || !rawPending) throw new Error("Sign-in could not be completed. Please try again.");

    const pending = JSON.parse(rawPending) as { verifier: string; state: string; returnTo: string };
    // State is the CSRF check: a code we did not ask for must not be redeemed.
    if (state !== pending.state) throw new Error("Sign-in could not be verified. Please try again.");

    await this.exchange(code, pending.verifier);
    return { returnTo: pending.returnTo || "/" };
  }

  /** Signs out of Hynt entirely — every platform, not just this one. */
  signOut(): void {
    this.clear();
    const target = this.opts.postLogoutRedirectUri ?? window.location.origin;
    const url = new URL(`${this.issuer}/oauth/logout`);
    url.searchParams.set("client_id", this.opts.clientId);
    url.searchParams.set("redirect_uri", target);
    window.location.assign(url.toString());
  }

  /**
   * Attach the token to same-origin calls under `prefix`, and retry once
   * through a silent renewal on a 401.
   *
   * Scoped to this origin: a substring match on the prefix would send the
   * token to any third-party URL that happened to contain it.
   */
  installFetchInterceptor(prefix = "/api/"): void {
    const original = window.fetch.bind(window);
    const self = this;

    window.fetch = async function patched(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      let sameOrigin = false;
      try {
        const url = new URL(raw, window.location.origin);
        sameOrigin = url.origin === window.location.origin && url.pathname.startsWith(prefix);
      } catch {
        sameOrigin = false;
      }
      if (!sameOrigin) return original(input, init);

      const withToken = (token: string | null): RequestInit => {
        const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
        if (token) headers.set("Authorization", `Bearer ${token}`);
        return { ...init, headers };
      };

      if (!self.isSignedIn) await self.silentSignIn();
      let response = await original(input, withToken(self.token));
      if (response.status !== 401) return response;

      const renewed = await self.silentSignIn();
      if (!renewed) return response;
      response = await original(input, withToken(self.token));
      return response;
    };
  }

  // -- internals ----------------------------------------------------------

  private async authorizeUrl(_prompt: "login", returnTo: string): Promise<string> {
    const verifier = randomString();
    const state = randomString(16);
    sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state, returnTo }));
    return this.buildAuthorizeUrl(verifier, state, "");
  }

  private async buildAuthorizeUrl(verifier: string, state: string, prompt: string): Promise<string> {
    const url = new URL(`${this.issuer}/oauth/authorize`);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", this.opts.clientId);
    url.searchParams.set("redirect_uri", this.opts.redirectUri);
    url.searchParams.set("code_challenge", await challengeFor(verifier));
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("state", state);
    if (prompt) url.searchParams.set("prompt", prompt);
    return url.toString();
  }

  private async exchange(code: string, verifier: string): Promise<void> {
    const response = await fetch(`${this.issuer}/oauth/token`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        code,
        client_id: this.opts.clientId,
        redirect_uri: this.opts.redirectUri,
        code_verifier: verifier,
      }),
    });
    if (!response.ok) {
      const detail = (await response.json().catch(() => ({}))) as { detail?: string };
      throw new Error(this.describe(detail.detail ?? "invalid_grant"));
    }
    const data = (await response.json()) as TokenResponse;
    const { plan_status, ...rest } = data.user;
    this.accessToken = data.access_token;
    this.currentUser = { ...rest, planStatus: plan_status };
    this.expiresAt = Date.now() + data.expires_in * 1000;
    this.scheduleRenewal(data.expires_in);
  }

  private scheduleRenewal(expiresIn: number): void {
    if (this.renewTimer) clearTimeout(this.renewTimer);
    const skew = this.opts.renewSkewSeconds ?? 60;
    const delay = Math.max((expiresIn - skew) * 1000, 5_000);
    this.renewTimer = setTimeout(() => {
      void this.silentSignIn();
    }, delay);
  }

  private clear(): void {
    this.accessToken = null;
    this.currentUser = null;
    this.expiresAt = 0;
    if (this.renewTimer) clearTimeout(this.renewTimer);
    this.renewTimer = null;
  }

  private describe(code: string): string {
    switch (code) {
      case "access_denied":
      case "no_membership":
        return "Your Hynt account does not have access to this platform yet.";
      case "login_required":
        return "Your session has ended. Please sign in again.";
      default:
        return "Sign-in failed. Please try again.";
    }
  }
}
