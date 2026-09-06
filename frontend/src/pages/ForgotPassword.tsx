import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { Alert, Field, Spinner } from "../components/ui";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.forgotPassword(email.trim());
      setSent(result.message);
      // Present only when the server runs with DEBUG on, so the flow can be
      // exercised without a mail server.
      setDevToken(result.reset_token ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1 className="auth-title">Reset your password</h1>
        <p className="auth-sub">We will email you a link to set a new one.</p>

        {error ? <Alert kind="error">{error}</Alert> : null}
        {sent ? <Alert kind="success">{sent}</Alert> : null}
        {devToken ? (
          <Alert kind="info">
            Development mode — use this token directly:
            <div className="mono" style={{ marginTop: 6, wordBreak: "break-all" }}>{devToken}</div>
            <Link to={`/reset-password?token=${encodeURIComponent(devToken)}`}>Continue →</Link>
          </Alert>
        ) : null}

        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </Field>

        <div style={{ marginTop: 18 }}>
          <button className="btn btn-primary btn-block" disabled={busy || !email}>
            {busy ? <Spinner /> : null} Send reset link
          </button>
        </div>

        <div className="auth-foot">
          <Link to="/login">Back to sign in</Link>
        </div>
      </form>
    </div>
  );
}
