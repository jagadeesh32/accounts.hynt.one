export interface HyntSsoConfig {
  /** e.g. https://accounts.hynt.one */
  issuer: string;
  /** OAuth client id, e.g. "terminal-web" */
  clientId: string;
  /** Must exactly match a URI registered for this client. */
  redirectUri: string;
  scope?: string;
  /** Where to send the user after signing out. */
  postLogoutRedirectUri?: string;
  /** Seconds before expiry at which to renew silently. */
  renewSkewSeconds?: number;
  /** Called when the session is definitively over. */
  onSignedOut?: () => void;
}

export interface AccessClaims {
  sub: string;
  email: string;
  email_verified: boolean;
  name: string;
  org: string;
  aud: string;
  exp: number;
  role: string;
  rank: number;
  perms: string[];
  plan: string | null;
  plan_status: string | null;
  ent: string[];
  lim: Record<string, unknown>;
  sid: string | null;
  tv: number;
}

export interface HyntUser {
  id: string;
  email: string;
  name: string;
  orgId: string;
  role: string;
  rank: number;
  permissions: string[];
  plan: string | null;
  planStatus: string | null;
  entitlements: string[];
  limits: Record<string, unknown>;
  emailVerified: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  scope: string;
  id_token?: string;
  platform: string;
  role: string;
  plan: string | null;
}
