/** The audit trail. Read-only by design — there is no edit path in the API. */
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type AuditEntry } from "../lib/api";
import { Alert, Badge, Empty, Spinner, formatDate } from "../components/ui";

const FILTERS = [
  { label: "Everything", value: "" },
  { label: "Sign-ins", value: "auth.login.success" },
  { label: "Failed sign-ins", value: "auth.login.failed" },
  { label: "Tokens issued", value: "oauth.token.issued" },
  { label: "Access denied", value: "oauth.authorize.denied" },
  { label: "Token reuse", value: "oauth.token.reuse_detected" },
  { label: "Role changes", value: "admin.membership.role_changed" },
  { label: "Suspensions", value: "admin.user.suspended" },
];

function tone(action: string): string {
  if (action.includes("failed") || action.includes("denied") || action.includes("reuse")) return "suspended";
  if (action.includes("success") || action.includes("issued")) return "active";
  if (action.startsWith("admin.")) return "admin";
  return "user";
}

export default function AdminAudit() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.admin.audit({ offset, action: action || undefined });
      setEntries(result.entries);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the audit log.");
    } finally {
      setLoading(false);
    }
  }, [offset, action]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="content">
      <h1 className="page-title">Audit log</h1>
      <p className="page-sub">Every authentication decision and administrative change.</p>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="card">
        <div className="card-head">
          <select
            value={action}
            onChange={(e) => { setOffset(0); setAction(e.target.value); }}
            style={{ maxWidth: 240 }}
          >
            {FILTERS.map((filter) => (
              <option key={filter.value} value={filter.value}>{filter.label}</option>
            ))}
          </select>
          <span className="faint">{total} entries</span>
        </div>

        {loading ? (
          <Empty><Spinner /></Empty>
        ) : entries.length === 0 ? (
          <Empty>Nothing recorded yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Platform</th>
                  <th>IP</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>
                      {formatDate(entry.created_at)}
                    </td>
                    <td><Badge kind={tone(entry.action)}>{entry.action}</Badge></td>
                    <td className="muted">{entry.platform_slug ?? "—"}</td>
                    <td className="mono">{entry.ip_address ?? "—"}</td>
                    <td className="faint mono" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {Object.keys(entry.meta ?? {}).length ? JSON.stringify(entry.meta) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > 50 ? (
          <div className="row-between" style={{ marginTop: 14 }}>
            <button className="btn btn-sm" disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
            <span className="faint">{offset + 1}–{Math.min(offset + 50, total)} of {total}</span>
            <button className="btn btn-sm" disabled={offset + 50 >= total}
                    onClick={() => setOffset(offset + 50)}>Next</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
