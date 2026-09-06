# @hynt/sso-web

Browser SDK for single sign-on against `accounts.hynt.one`.

```ts
import { HyntSso, relaySilentCallback } from "@hynt/sso-web";

export const sso = new HyntSso({
  issuer: "https://accounts.hynt.one",
  clientId: "terminal-web",
  redirectUri: `${window.location.origin}/auth/callback`,
  postLogoutRedirectUri: `${window.location.origin}/`,
  onSignedOut: () => { /* bounce to the gate */ },
});

await sso.silentSignIn();     // renew against the hynt_sso cookie
sso.installFetchInterceptor("/api/");
```

The callback route must call `relaySilentCallback()` first: the same route is
loaded inside the hidden renewal iframe, and that call is what tells the two
cases apart.

Install from the estate checkout — this package is not published to npm:

```jsonc
// package.json
"dependencies": { "@hynt/sso-web": "file:../../accounts.hynt.one/packages/hynt-sso-web" }
```

Then `npm install && npm run build --prefix node_modules/@hynt/sso-web` (or build
once here and commit `dist/`).
