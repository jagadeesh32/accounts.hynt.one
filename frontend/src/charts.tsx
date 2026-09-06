/**
 * The chart kit — hand-rolled inline SVG, no library.
 *
 * Not asceticism: this host's CSP is `script-src 'self'` with no external
 * origin, because it holds the password form and the estate's SSO cookie. A
 * charting bundle from a CDN cannot load here at all, and vendoring one to draw
 * six shapes would cost more bytes than the shapes.
 *
 * Colour rules (styles/charts.css holds the values):
 *   · One series  → the sequential hue. No legend: the card title names it.
 *   · Two or more → the categorical slots IN FIXED ORDER, never cycled and never
 *     reassigned when a filter changes the series count, so a colour keeps
 *     meaning the same thing across a page and across a reload.
 *   · Magnitude   → one hue, light→dark (the heatmap).
 *   · State       → the status four, and never as a series colour.
 * The eight slots were validated for colour-vision separation against this app's
 * own light and dark surfaces before being written down; do not add a ninth.
 *
 * Every chart here ships its hover layer, and every chart that carries values a
 * reader might need exactly ships a table view behind a toggle — the light-mode
 * slots for aqua, yellow and magenta sit under 3:1 against the panel, and the
 * numbers being reachable without hovering is what makes that legal.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

/* =========================================================
   Formatting
   ========================================================= */

export function fmtInt(n: number): string {
  return n.toLocaleString();
}

/** 1,284 · 12.9K · 4.2M — for tiles and axis ticks, where width is scarce. */
export function fmtCompact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 10_000) return `${Math.round(n / 1e3)}K`;
  if (abs >= 1000) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return n.toLocaleString();
}

export function fmtInr(n: number): string {
  return `₹${fmtCompact(n)}`;
}

export function fmtDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Axis ticks land on 1/2/5×10ⁿ so the reader gets 0 / 50 / 100, never 0 / 37 / 74. */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(Math.round(v * 1e6) / 1e6);
  if (out.length < 2) out.push(step);
  return out;
}

/* =========================================================
   Sizing — charts are px-accurate, so text never scales
   ========================================================= */

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // preserveAspectRatio="none" would stretch the labels with the box, so the
    // SVG is drawn at the container's real width instead of being scaled.
    const ro = new ResizeObserver(([entry]) => setW(entry.contentRect.width));
    ro.observe(el);
    setW(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/* =========================================================
   Chart card — title, filters slot, table view
   ========================================================= */

export interface TableView {
  columns: string[];
  rows: (string | number)[][];
}

export function ChartCard({
  title, subtitle, right, table, children, tall,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  /** The numbers behind the picture. Present ⇒ the reader can read them. */
  table?: TableView;
  children: ReactNode;
  tall?: boolean;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className={`chart-card ${tall ? "tall" : ""}`}>
      <header className="chart-head">
        <div className="chart-id">
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="chart-actions">
          {right}
          {table && (
            <button
              className={`chart-toggle ${showTable ? "on" : ""}`}
              onClick={() => setShowTable((s) => !s)}
              aria-pressed={showTable}
              title={showTable ? "Show the chart" : "Show the numbers"}
            >
              {showTable ? "Chart" : "Numbers"}
            </button>
          )}
        </div>
      </header>
      {showTable && table ? (
        <div className="chart-table-wrap">
          <table className="chart-table">
            <thead><tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>{r.map((cell, j) => <td key={j}>{typeof cell === "number" ? fmtInt(cell) : cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-body">{children}</div>
      )}
    </section>
  );
}

/* =========================================================
   Tooltip — one floating readout, shared by every chart
   ========================================================= */

interface TipState { x: number; y: number; title: string; rows: { label: string; value: string; color?: string }[] }

function Tooltip({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  // Flip before the card's edge rather than after it: a tooltip that opens off
  // the right of the last data point is exactly where the interesting points are.
  const flip = tip.x > width - 150;
  return (
    <div
      className={`viz-tip ${flip ? "flip" : ""}`}
      style={{ left: tip.x, top: tip.y }}
      role="status"
    >
      <div className="viz-tip-title">{tip.title}</div>
      {tip.rows.map((r, i) => (
        <div className="viz-tip-row" key={i}>
          {r.color && <span className="viz-key" style={{ background: r.color }} />}
          <span className="viz-tip-value">{r.value}</span>
          <span className="viz-tip-label">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

/* =========================================================
   Time series — line / area, 1..4 series, crosshair
   ========================================================= */

export interface SeriesDef { key: string; label: string; color: string }

/** A day plus one numeric field per series. Only `d` is named, so a caller can
 *  hand over its own row type — `{d, v}` from the API, or a joined row it built
 *  — without a cast at every call site. */
export interface DayRow { d: string }

function at(row: DayRow, key: string): number {
  return Number((row as unknown as Record<string, unknown>)[key] ?? 0);
}

export function TimeSeries({
  data, series, height = 190, area, format = fmtInt,
}: {
  data: readonly DayRow[];
  series: SeriesDef[];
  height?: number;
  /** Fill under the line. Honest for one series; noise for four. */
  area?: boolean;
  format?: (n: number) => string;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const pad = { t: 12, r: 14, b: 22, l: 40 };
  const iw = Math.max(10, w - pad.l - pad.r);
  const ih = height - pad.t - pad.b;

  const max = useMemo(() => {
    let m = 0;
    for (const row of data) for (const s of series) m = Math.max(m, at(row, s.key));
    return m;
  }, [data, series]);

  const ticks = useMemo(() => niceTicks(max), [max]);
  const top = ticks[ticks.length - 1] || 1;
  const x = (i: number) => (data.length < 2 ? iw / 2 : (i / (data.length - 1)) * iw);
  const y = (v: number) => ih - (v / top) * ih;

  const idx = hover === null ? null : Math.max(0, Math.min(data.length - 1, hover));
  const row = idx === null ? null : data[idx];

  const tip: TipState | null = row
    ? {
        x: pad.l + x(idx!),
        y: pad.t + 4,
        title: fmtDay(row.d),
        rows: series.map((s) => ({ label: s.label, value: format(at(row, s.key)), color: s.color })),
      }
    : null;

  // Date ticks: first, last and a couple between — never one per day.
  const xTicks = useMemo(() => {
    if (data.length <= 2) return data.map((_, i) => i);
    const want = Math.min(5, data.length);
    return Array.from({ length: want }, (_, k) => Math.round((k / (want - 1)) * (data.length - 1)));
  }, [data.length]);

  return (
    <div className="viz" ref={ref}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={`${series.map((s) => s.label).join(", ")} over time`}>
          <g transform={`translate(${pad.l},${pad.t})`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="viz-grid" x1={0} x2={iw} y1={y(t)} y2={y(t)} />
                <text className="viz-tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">{fmtCompact(t)}</text>
              </g>
            ))}
            {xTicks.map((i) => (
              <text key={i} className="viz-tick" x={x(i)} y={ih + 15} textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}>
                {fmtDay(data[i].d)}
              </text>
            ))}

            {series.map((s) => {
              const pts = data.map((r, i) => `${x(i)},${y(at(r, s.key))}`).join(" ");
              return (
                <g key={s.key}>
                  {area && (
                    <polygon
                      className="viz-area"
                      fill={s.color}
                      points={`0,${ih} ${pts} ${x(data.length - 1)},${ih}`}
                    />
                  )}
                  <polyline className="viz-line" stroke={s.color} points={pts} />
                  {data.length > 0 && (
                    <circle
                      className="viz-dot"
                      cx={x(data.length - 1)}
                      cy={y(at(data[data.length - 1], s.key))}
                      r={4}
                      fill={s.color}
                    />
                  )}
                </g>
              );
            })}

            {idx !== null && (
              <g>
                <line className="viz-cross" x1={x(idx)} x2={x(idx)} y1={0} y2={ih} />
                {series.map((s) => (
                  <circle key={s.key} className="viz-dot" cx={x(idx)} cy={y(at(data[idx], s.key))} r={4.5} fill={s.color} />
                ))}
              </g>
            )}

            {/* The reader aims at a date, not at a 2px line. */}
            <rect
              width={iw} height={ih} fill="transparent"
              onPointerMove={(e) => {
                const bounds = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                const rel = e.clientX - bounds.left;
                setHover(Math.round((rel / iw) * (data.length - 1)));
              }}
              onPointerLeave={() => setHover(null)}
            />
          </g>
        </svg>
      )}
      <Tooltip tip={tip} width={w} />
      {series.length > 1 && (
        <div className="viz-legend">
          {series.map((s) => (
            <span key={s.key}><span className="viz-key line" style={{ background: s.color }} />{s.label}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/* =========================================================
   Sparkline — the trend inside a stat tile
   ========================================================= */

export function Sparkline({ values, color, width = 92, height = 26 }: {
  values: number[]; color?: string; width?: number; height?: number;
}) {
  if (values.length < 2) return <span className="spark-empty" />;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * (width - 2) + 1},${height - 2 - ((v - min) / span) * (height - 4)}`)
    .join(" ");
  return (
    <svg className="spark" width={width} height={height} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color || "var(--seq-450)"} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* =========================================================
   Stat tile — label · value · delta vs a NAMED period · trend
   ========================================================= */

export function StatTile({
  label, value, hint, delta, deltaLabel, upIsGood = true, trend, tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  /** Fractional change, e.g. 0.12 for +12%. */
  delta?: number | null;
  deltaLabel?: string;
  upIsGood?: boolean;
  trend?: number[];
  tone?: "good" | "warning" | "critical";
}) {
  const dir = delta === null || delta === undefined ? 0 : delta > 0.0001 ? 1 : delta < -0.0001 ? -1 : 0;
  const good = dir === 0 ? null : (dir > 0) === upIsGood;
  return (
    <div className={`stat-tile ${tone ? `tone-${tone}` : ""}`}>
      <div className="st-label">{label}</div>
      <div className="st-value">{typeof value === "number" ? fmtCompact(value) : value}</div>
      <div className="st-foot">
        {dir !== 0 && (
          <span className={`st-delta ${good ? "up" : "down"}`}>
            {dir > 0 ? "▲" : "▼"} {Math.abs(Math.round((delta ?? 0) * 100))}%
            {deltaLabel && <span className="st-vs"> {deltaLabel}</span>}
          </span>
        )}
        {dir === 0 && hint && <span className="st-hint">{hint}</span>}
        {trend && trend.length > 1 && <Sparkline values={trend} />}
      </div>
    </div>
  );
}

/* =========================================================
   Bars — magnitude, one hue, value at the tip
   ========================================================= */

export function BarList({
  rows, format = fmtInt, max, color = "var(--seq-450)",
}: {
  rows: { label: string; value: number; hint?: string }[];
  format?: (n: number) => string;
  max?: number;
  color?: string;
}) {
  const top = max ?? Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="barlist">
      {rows.map((r) => (
        <div className="barlist-row" key={r.label} title={r.hint ? `${r.label} — ${r.hint}` : r.label}>
          <span className="bl-label">{r.label}</span>
          <span className="bl-track">
            <span className="bl-fill" style={{ width: `${Math.max(1.5, (r.value / top) * 100)}%`, background: color }} />
          </span>
          <span className="bl-value">{format(r.value)}</span>
        </div>
      ))}
      {!rows.length && <p className="viz-empty">Nothing in this window.</p>}
    </div>
  );
}

/* =========================================================
   Stacked bar — part-to-whole, 2px surface gaps between parts
   ========================================================= */

export function StackedBar({
  parts, total, format = fmtInt,
}: {
  parts: { label: string; value: number; color: string }[];
  total?: number;
  format?: (n: number) => string;
}) {
  const sum = total ?? parts.reduce((a, p) => a + p.value, 0);
  const shown = parts.filter((p) => p.value > 0);
  return (
    <div className="stackwrap">
      <div className="stack" role="img" aria-label={shown.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {shown.map((p) => (
          <span
            key={p.label}
            className="stack-part"
            style={{ flexGrow: p.value, background: p.color }}
            title={`${p.label}: ${format(p.value)}`}
          />
        ))}
        {!shown.length && <span className="stack-part empty" style={{ flexGrow: 1 }} />}
      </div>
      <div className="stack-legend">
        {parts.map((p) => (
          <span key={p.label}>
            <span className="viz-key" style={{ background: p.color }} />
            {p.label}
            <b>{format(p.value)}</b>
            {sum > 0 && <i>{Math.round((p.value / sum) * 100)}%</i>}
          </span>
        ))}
      </div>
    </div>
  );
}

/* =========================================================
   Meter — one ratio against its limit
   ========================================================= */

export function Meter({ value, total, label, invert }: {
  value: number; total: number; label?: string; invert?: boolean;
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  const bad = invert ? pct > 20 : pct < 60;
  const mid = invert ? pct > 5 : pct < 85;
  const tone = bad ? "critical" : mid ? "warning" : "good";
  return (
    <div className="meter">
      <div className="meter-top">
        <span>{label}</span>
        <b>{pct}%</b>
      </div>
      <div className={`meter-track tone-${tone}`}>
        <span style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <div className="meter-foot">{fmtInt(value)} of {fmtInt(total)}</div>
    </div>
  );
}

/* =========================================================
   Heatmap — weekday × hour, one hue, more-is-darker
   ========================================================= */

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const SEQ = ["var(--seq-100)", "var(--seq-200)", "var(--seq-300)", "var(--seq-400)", "var(--seq-500)", "var(--seq-600)", "var(--seq-700)"];

export function Heatmap({ cells }: { cells: { dow: number; hour: number; v: number }[] }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);

  const grid = useMemo(() => {
    const g = new Map<string, number>();
    let max = 0;
    for (const c of cells) {
      g.set(`${c.dow}-${c.hour}`, c.v);
      max = Math.max(max, c.v);
    }
    return { g, max };
  }, [cells]);

  const labelW = 32;
  const cell = Math.max(6, Math.floor((w - labelW - 24) / 24));
  const gap = 2;

  return (
    <div className="viz heat" ref={ref}>
      {w > 0 && (
        <svg width={w} height={7 * (cell + gap) + 18}>
          {DOW.map((name, d) => (
            <g key={name}>
              <text className="viz-tick" x={labelW - 8} y={d * (cell + gap) + cell / 2} dy="0.32em" textAnchor="end">{name}</text>
              {Array.from({ length: 24 }, (_, h) => {
                const v = grid.g.get(`${d}-${h}`) ?? 0;
                const step = grid.max === 0 ? -1 : Math.min(SEQ.length - 1, Math.floor((v / grid.max) * SEQ.length));
                return (
                  <rect
                    key={h}
                    x={labelW + h * (cell + gap)}
                    y={d * (cell + gap)}
                    width={cell}
                    height={cell}
                    rx={2}
                    className="heat-cell"
                    fill={v === 0 || step < 0 ? "var(--panel-2)" : SEQ[step]}
                    onPointerEnter={() => setTip({
                      x: labelW + h * (cell + gap),
                      y: d * (cell + gap) + cell + 6,
                      title: `${name} ${String(h).padStart(2, "0")}:00`,
                      rows: [{ label: "events", value: fmtInt(v) }],
                    })}
                    onPointerLeave={() => setTip(null)}
                  />
                );
              })}
            </g>
          ))}
          {[0, 6, 12, 18, 23].map((h) => (
            <text key={h} className="viz-tick" x={labelW + h * (cell + gap) + cell / 2} y={7 * (cell + gap) + 12} textAnchor="middle">
              {String(h).padStart(2, "0")}
            </text>
          ))}
        </svg>
      )}
      <Tooltip tip={tip} width={w} />
    </div>
  );
}

/* =========================================================
   The categorical slots, in fixed order. Import, never invent.
   ========================================================= */

export const SERIES = [
  "var(--v1)", "var(--v2)", "var(--v3)", "var(--v4)",
  "var(--v5)", "var(--v6)", "var(--v7)", "var(--v8)",
] as const;

/** Fold anything past the eighth slot into one "Other" row rather than
 *  inventing a ninth hue that nobody with CVD can tell from the third. */
export function foldToSlots<T>(items: T[], value: (t: T) => number, label: (t: T) => string, cap = 7) {
  const sorted = [...items].sort((a, b) => value(b) - value(a));
  const head = sorted.slice(0, cap).map((it, i) => ({ label: label(it), value: value(it), color: SERIES[i] }));
  const tail = sorted.slice(cap);
  if (tail.length) {
    head.push({ label: `Other (${tail.length})`, value: tail.reduce((a, t) => a + value(t), 0), color: "var(--v8)" });
  }
  return head;
}

/** Reduced motion is honoured by CSS; this is for charts that animate on mount. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}
