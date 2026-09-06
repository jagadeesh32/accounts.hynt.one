import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";

interface AuditRow {
  at: string; action: string; actor: string | null; target: string | null;
  ip: string | null; meta?: Record<string, unknown> | null;
}

export function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  // `action` and `limit` are sent to the server, which filters there. The text
  // and date boxes narrow what already came back — the count line below says so,
  // because a filter that silently only searches the last 100 rows is a trap.
  const [action, setAction] = useState("");
  const [limit, setLimit] = useState(100);
  const [text, setText] = useState("");
  const [since, setSince] = useState("");

  const load = useCallback(async () => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (action) query.set("action", action);
    setRows((await api.get<{ events: AuditRow[] }>(`/api/v1/superadmin/audit?${query}`)).events);
  }, [action, limit]);

  useEffect(() => { void load(); }, [load]);

  // Built from what has loaded, so the list reflects what actually happens on
  // this estate rather than a hardcoded catalogue that drifts from the backend.
  const actions = useMemo(() => [...new Set(rows.map((e) => e.action))].sort(), [rows]);

  const shown = useMemo(() => {
    const needle = text.trim().toLowerCase();
    const from = since ? new Date(since).getTime() : null;
    return rows.filter((e) => {
      if (from !== null && new Date(e.at).getTime() < from) return false;
      if (!needle) return true;
      return [e.actor, e.target, e.action, e.ip].some((v) => (v ?? "").toLowerCase().includes(needle));
    });
  }, [rows, text, since]);

  function exportCsv() {
    const cell = (v: unknown) => {
      const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
      // Always quoted, inner quotes doubled: an audit target can legally contain
      // a comma, and an unquoted CSV would shift every later column silently.
      return `"${s.replace(/"/g, '""')}"`;
    };
    const csv = [
      ["at", "action", "actor", "target", "ip", "meta"].join(","),
      ...shown.map((e) => [e.at, e.action, e.actor, e.target, e.ip, e.meta].map(cell).join(",")),
    ].join("\n");

    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `hynt-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Audit</h1>
        <p className="muted">
          Every administrative action, and who took it. Written on the server, so a change made
          directly in the database does not appear here.
        </p>
      </header>

      <div className="card">
        <div className="card-head">
          <h2>{shown.length} event{shown.length === 1 ? "" : "s"}</h2>
          <button className="btn" onClick={exportCsv} disabled={!shown.length}>Export CSV</button>
        </div>

        <div className="filters">
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Every action</option>
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <input placeholder="Filter actor, target or IP" value={text} onChange={(e) => setText(e.target.value)} />
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {[100, 250, 500].map((n) => <option key={n} value={n}>Last {n}</option>)}
          </select>
          {(text || since || action) && (
            <button className="btn small ghost" onClick={() => { setText(""); setSince(""); setAction(""); }}>
              Clear
            </button>
          )}
        </div>

        <table className="table">
          <thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Target</th><th>IP</th></tr></thead>
          <tbody>
            {shown.map((e, i) => (
              <tr key={`${e.at}-${i}`}>
                <td className="muted">{new Date(e.at).toLocaleString()}</td>
                <td className="mono">{e.action}</td>
                <td>{e.actor ?? "—"}</td>
                <td className="muted">{e.target ?? "—"}</td>
                <td className="mono muted">{e.ip ?? "—"}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={5} className="muted">Nothing matches those filters.</td></tr>}
          </tbody>
        </table>

        <p className="count-note">
          Showing {shown.length} of {rows.length} loaded{shown.length !== rows.length && " (filtered)"}.
          {" "}The action list and row cap are applied by the server; the text and date boxes narrow
          what has already loaded — widen the cap to search further back.
        </p>
      </div>
    </section>
  );
}
