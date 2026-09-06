/**
 * DataTable — one sortable, filterable, paginated table for the whole console.
 *
 * Every list in this app was its own hand-rolled <table>: each one sorted
 * differently (or not at all), each one filtered differently, and none of them
 * paginated — so a five-hundred-account estate rendered five hundred rows and
 * the browser wore it. This replaces all of them.
 *
 * Two things are deliberate:
 *
 *  · Facets derive their options FROM THE DATA. A hardcoded status list drifts
 *    from the backend the first time someone adds a state, and the drift shows
 *    up as a filter that silently matches nothing. Here, if a value exists in
 *    the rows it is offered, with its own count beside it.
 *
 *  · The footer always says what is being counted — shown, filtered, loaded.
 *    A table that pages, filters AND has a server-side row cap can otherwise
 *    let a reader conclude "there are 41 audit events" when there are 4,000.
 */
import {
  useEffect, useMemo, useState, type ReactNode,
} from "react";
import { Icon } from "../ui";

export interface Column<T> {
  key: string;
  header: string;
  /** The sortable/filterable/exportable value. Omit for action columns. */
  value?: (row: T) => string | number | null | undefined;
  /** The rendered cell. Falls back to `value`. */
  render?: (row: T) => ReactNode;
  align?: "left" | "right";
  /** Defaults to true when `value` is given. */
  sortable?: boolean;
  className?: string;
  width?: string;
}

export interface Facet<T> {
  key: string;
  label: string;
  /** The row's value for this facet, or null to exclude it from the counts. */
  of: (row: T) => string | null | undefined;
}

type Dir = "asc" | "desc";

const PAGE_SIZES = [10, 25, 50, 100];

function cellText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function DataTable<T>({
  id, rows, columns, facets = [], getKey, searchPlaceholder = "Search",
  right, empty = "Nothing matches those filters.", loading, initialSort, initialDir = "desc",
  note, dense, exportName,
}: {
  /** Stable id — the page size and column sort are remembered per table. */
  id: string;
  rows: T[];
  columns: Column<T>[];
  facets?: Facet<T>[];
  getKey: (row: T) => string;
  searchPlaceholder?: string;
  right?: ReactNode;
  empty?: string;
  loading?: boolean;
  initialSort?: string;
  initialDir?: Dir;
  /** Extra sentence for the footer — e.g. the server-side row cap. */
  note?: ReactNode;
  dense?: boolean;
  /** Base name for the CSV. Omit to hide the export button. */
  exportName?: string;
}) {
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<string | null>(initialSort ?? null);
  const [dir, setDir] = useState<Dir>(initialDir);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(`hynt.table.${id}.size`));
      return PAGE_SIZES.includes(saved) ? saved : 25;
    } catch {
      return 25;
    }
  });

  useEffect(() => {
    try { localStorage.setItem(`hynt.table.${id}.size`, String(size)); } catch { /* private mode */ }
  }, [id, size]);

  // Any change to what is being shown puts the reader back on page 1 — paging
  // to row 200 of a list that just became 12 rows long shows an empty table.
  useEffect(() => { setPage(0); }, [q, picked, size, rows.length]);

  const facetOptions = useMemo(
    () =>
      facets.map((f) => {
        const counts = new Map<string, number>();
        for (const row of rows) {
          const v = f.of(row);
          if (v === null || v === undefined || v === "") continue;
          counts.set(v, (counts.get(v) ?? 0) + 1);
        }
        return { facet: f, options: [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])) };
      }),
    [facets, rows],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((row) => {
      for (const f of facets) {
        const want = picked[f.key];
        if (want && f.of(row) !== want) return false;
      }
      if (!needle) return true;
      return columns.some((c) => c.value && cellText(c.value(row)).toLowerCase().includes(needle));
    });
  }, [rows, columns, facets, picked, q]);

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort);
    if (!col?.value) return filtered;
    const sign = dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = col.value!(a);
      const bv = col.value!(b);
      // Blanks sort last in both directions: an account that has never signed in
      // is not "the oldest sign-in", and putting it first buries the real answer.
      if (av === null || av === undefined || av === "") return bv === null || bv === undefined || bv === "" ? 0 : 1;
      if (bv === null || bv === undefined || bv === "") return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sign;
      return cellText(av).localeCompare(cellText(bv), undefined, { numeric: true }) * sign;
    });
  }, [filtered, columns, sort, dir]);

  const pages = Math.max(1, Math.ceil(sorted.length / size));
  const current = Math.min(page, pages - 1);
  const slice = sorted.slice(current * size, current * size + size);
  const activeFilters = Object.values(picked).filter(Boolean).length + (q ? 1 : 0);

  function toggleSort(col: Column<T>) {
    if (!col.value || col.sortable === false) return;
    if (sort !== col.key) { setSort(col.key); setDir("desc"); return; }
    if (dir === "desc") { setDir("asc"); return; }
    setSort(null);
  }

  function exportCsv() {
    const cols = columns.filter((c) => c.value);
    // Always quoted, inner quotes doubled: an audit target can legally contain a
    // comma, and an unquoted CSV shifts every later column without saying so.
    const cell = (v: unknown) => `"${cellText(v).replace(/"/g, '""')}"`;
    const csv = [
      cols.map((c) => cell(c.header)).join(","),
      ...sorted.map((row) => cols.map((c) => cell(c.value!(row))).join(",")),
    ].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportName}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className={`dt ${dense ? "dense" : ""} ${loading ? "loading" : ""}`}>
      <div className="dt-bar">
        <span className="dt-search">
          <Icon name="search" size={14} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
          />
          {q && <button className="dt-clear" onClick={() => setQ("")} aria-label="Clear search"><Icon name="x" size={12} /></button>}
        </span>

        {facetOptions.map(({ facet, options }) => (
          options.length > 1 && (
            <select
              key={facet.key}
              value={picked[facet.key] ?? ""}
              onChange={(e) => setPicked((p) => ({ ...p, [facet.key]: e.target.value }))}
              aria-label={facet.label}
              className="dt-facet"
            >
              <option value="">{facet.label}: any</option>
              {options.map(([value, count]) => (
                <option key={value} value={value}>{value} ({count})</option>
              ))}
            </select>
          )
        ))}

        {activeFilters > 0 && (
          <button className="btn small ghost" onClick={() => { setQ(""); setPicked({}); }}>
            Clear {activeFilters} filter{activeFilters === 1 ? "" : "s"}
          </button>
        )}

        <span className="dt-spacer" />
        {exportName && (
          <button className="btn small ghost" onClick={exportCsv} disabled={!sorted.length} title="Download the filtered rows">
            <Icon name="arrow-up-right" size={13} /> CSV
          </button>
        )}
        {right}
      </div>

      <div className="dt-scroll">
        <table className="dt-table">
          <thead>
            <tr>
              {columns.map((c) => {
                const on = sort === c.key;
                const can = !!c.value && c.sortable !== false;
                return (
                  <th
                    key={c.key}
                    style={{ width: c.width, textAlign: c.align ?? "left" }}
                    aria-sort={on ? (dir === "asc" ? "ascending" : "descending") : "none"}
                    className={can ? "sortable" : ""}
                  >
                    {can ? (
                      <button onClick={() => toggleSort(c)} className={`dt-sort ${on ? "on" : ""}`}>
                        {c.header}
                        <span className="dt-arrow">{on ? (dir === "asc" ? "↑" : "↓") : "↕"}</span>
                      </button>
                    ) : c.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {slice.map((row) => (
              <tr key={getKey(row)}>
                {columns.map((c) => (
                  <td key={c.key} className={c.className} style={{ textAlign: c.align ?? "left" }}>
                    {c.render ? c.render(row) : cellText(c.value?.(row))}
                  </td>
                ))}
              </tr>
            ))}
            {!slice.length && (
              <tr className="dt-empty"><td colSpan={columns.length}>{loading ? "Loading…" : empty}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="dt-foot">
        <span className="dt-count">
          {sorted.length === 0
            ? "No rows"
            : `${current * size + 1}–${Math.min(sorted.length, current * size + size)} of ${sorted.length}`}
          {sorted.length !== rows.length && ` filtered from ${rows.length}`}
          {note && <span className="dt-note"> · {note}</span>}
        </span>

        <span className="dt-pager">
          <select value={size} onChange={(e) => setSize(Number(e.target.value))} aria-label="Rows per page">
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
          </select>
          <button className="dt-page" onClick={() => setPage(0)} disabled={current === 0} aria-label="First page">«</button>
          <button className="dt-page" onClick={() => setPage(current - 1)} disabled={current === 0} aria-label="Previous page">‹</button>
          <span className="dt-pageno">{current + 1} / {pages}</span>
          <button className="dt-page" onClick={() => setPage(current + 1)} disabled={current >= pages - 1} aria-label="Next page">›</button>
          <button className="dt-page" onClick={() => setPage(pages - 1)} disabled={current >= pages - 1} aria-label="Last page">»</button>
        </span>
      </div>
    </div>
  );
}
