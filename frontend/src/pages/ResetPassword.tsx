import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { Alert, Field, Spinner } from "../components/ui";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const mismatch = confirm.length > 0 && password !== confirm;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await api.resetPassword(token, password);
      setDone(true);
      setTimeout(() => navigate("/login", { replace: true }), 1800);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1 className="auth-title">Invalid link</h1>
          <p className="auth-sub">This reset link is missing its token.</p>
          <Link className="btn btn-block" to="/forgot-password">Request a new one</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1 className="auth-title">Choose a new password</h1>
        <p className="auth-sub">Signing in elsewhere will end when you save this.</p>

        {error ? <Alert kind="error">{error}</Alert> : null}
        {done ? <Alert kind="success">Password updated. Taking you to sign in…</Alert> : null}

        <Field label="New password" hint="At least 10 characters.">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            minLength={10}
          />
        </Field>

        <Field label="Confirm password">
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
          />
        </Field>
        {mismatch ? <div className="faint" style={{ color: "var(--danger)", marginTop: 6 }}>Passwords do not match.</div> : null}

        <div style={{ marginTop: 18 }}>
          <button
            className="btn btn-primary btn-block"
            disabled={busy || done || mismatch || password.length < 10}
          >
            {busy ? <Spinner /> : null} Update password
          </button>
        </div>
      </form>
    </div>
  );
}
