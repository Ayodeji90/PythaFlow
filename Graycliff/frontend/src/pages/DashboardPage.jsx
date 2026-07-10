import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api from "../api";

const fmtMoney = (v) => `$${Math.round(v).toLocaleString()}`;
const fmtK = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`);

function Tip({ active, payload, label, money = true }) {
  if (!active || !payload?.length) return null;
  const event = payload[0]?.payload?.event;
  return (
    <div className="tip">
      <div className="k">{label}</div>
      {payload.filter((p) => p.value != null).map((p) => (
        <div key={p.dataKey}>
          <span className="k">{p.name || p.dataKey}</span>
          <strong>{money ? fmtMoney(p.value) : p.value.toLocaleString()}</strong>
        </div>
      ))}
      {event && <div style={{ color: "var(--gold)", marginTop: 4 }}>◆ {event}</div>}
    </div>
  );
}

function SeriesLegend({ items }) {
  return (
    <div style={{ display: "flex", gap: 18, marginBottom: 8 }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, color: "var(--ink-2)" }}>
          <span style={{
            width: 16, height: 0, borderTop: `2.5px ${it.dashed ? "dashed" : "solid"} ${it.color}`,
            display: "inline-block",
          }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [fc, setFc] = useState(null);
  const [waste, setWaste] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState(null);

  const loadAll = useCallback(() => {
    api.dashboard().then(setSummary).catch((e) => setError(e.message));
    api.forecast().then(setFc).catch(() => {});
    api.wasteRisk().then(setWaste).catch(() => {});
    api.suggestions().then(setSuggestions).catch(() => {});
  }, []);
  useEffect(loadAll, [loadAll]);

  const fcData = useMemo(() => {
    if (!fc) return [];
    const hist = fc.history.map((h) => ({ date: h.date, actual: h.covers }));
    const last = fc.history[fc.history.length - 1];
    return [
      ...hist,
      { date: last.date, actual: last.covers, forecast: last.covers },
      ...fc.forecast.map((f) => ({ date: f.date, forecast: f.covers, event: f.event })),
    ];
  }, [fc]);

  async function decide(id, status) {
    const updated = await api.decideSuggestion(id, status);
    setSuggestions((list) => list.map((s) => (s.id === id ? updated : s)));
  }

  if (error) return <div className="page"><p style={{ color: "var(--status-critical)" }}>Backend unreachable: {error}</p></div>;
  if (!summary) return <div className="page"><p className="page-sub">Loading…</p></div>;

  const t = summary.today;
  const revAvg = summary.revenue_30d.reduce((s, d) => s + d.revenue, 0) / summary.revenue_30d.length;
  const delta = ((t.revenue - revAvg) / revAvg) * 100;
  const pending = suggestions.filter((s) => s.status === "pending");
  const decided = suggestions.filter((s) => s.status !== "pending");

  return (
    <div className="page">
      <h1 className="page-title">Manager Dashboard</h1>
      <p className="page-sub">Graycliff Restaurant · service date {summary.as_of}</p>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        <div className="card">
          <div className="stat-label">Tonight's revenue</div>
          <div className="stat-value">{fmtMoney(t.revenue)}</div>
          <div className={delta >= 0 ? "delta-up" : "delta-down"}>
            {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(0)}% vs 30-day avg
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Covers</div>
          <div className="stat-value">{t.covers}</div>
          <div className="page-sub" style={{ margin: 0 }}>{t.orders} orders</div>
        </div>
        <div className="card">
          <div className="stat-label">Waste at risk — 7 days</div>
          <div className="stat-value" style={{ color: waste?.total_at_risk > 0 ? "var(--status-serious)" : "var(--ink)" }}>
            {waste ? fmtMoney(waste.total_at_risk) : "—"}
          </div>
          <div className="page-sub" style={{ margin: 0 }}>perishables above forecast</div>
        </div>
        <div className="card">
          <div className="stat-label">Price actions pending</div>
          <div className="stat-value">{pending.length}</div>
          <div className="page-sub" style={{ margin: 0 }}>awaiting your approval</div>
        </div>
      </div>

      {/* ---- Smart Menu & Dynamic Pricing ---- */}
      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", marginTop: 16 }}>
        <div className="card">
          <h3>Covers — actual & 14-day forecast</h3>
          <div className="sub">Demand model: trailing level × weekday profile × event uplift</div>
          <SeriesLegend items={[
            { label: "Actual", color: "var(--series-1)" },
            { label: "Forecast", color: "var(--series-2)", dashed: true },
          ]} />
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={fcData} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} minTickGap={30}
                     tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis width={38} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<Tip money={false} />} cursor={{ stroke: "var(--muted)", strokeDasharray: "3 3" }} />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="var(--series-1)"
                    strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
              <Line type="monotone" dataKey="forecast" name="Forecast" stroke="var(--series-2)"
                    strokeWidth={2} strokeDasharray="6 4" dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3>Waste risk</h3>
          <div className="sub">Perishable stock above forecast demand</div>
          {waste?.items?.slice(0, 6).map((w) => (
            <div className="row" key={w.item_id}>
              <span style={{ fontSize: 13 }}>
                {w.name}
                <span style={{ color: "var(--muted)", display: "block", fontSize: 11.5 }}>
                  {w.stock} on hand · {w.forecast_7d} forecast
                </span>
              </span>
              <span className="badge" style={{ color: "var(--status-serious)", borderColor: "rgba(236,131,90,0.4)" }}>
                {fmtMoney(w.at_risk_value)}
              </span>
            </div>
          ))}
          {waste?.items?.length === 0 && <p className="page-sub">No perishable overstock.</p>}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Dynamic pricing — suggested actions</h3>
        <div className="sub">AI-suggested, manager-approved. Guardrails: margin ≥ 2× cost, changes capped at ±15%.</div>
        {pending.length === 0 && decided.length === 0 && <p className="page-sub">No suggestions right now.</p>}
        {pending.map((s) => (
          <div className="row" key={s.id} style={{ alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14.5 }}>
                {s.item_name}
                <span className="badge" style={{ marginLeft: 8 }}>{s.category}</span>
              </div>
              <div style={{ color: "var(--ink-2)", fontSize: 12.5, marginTop: 3, maxWidth: 640 }}>{s.rationale}</div>
            </div>
            <div style={{ textAlign: "right", minWidth: 210 }}>
              <div style={{ fontSize: 14 }}>
                <span style={{ color: "var(--muted)", textDecoration: "line-through", marginRight: 8 }}>
                  ${s.current_price.toFixed(2)}
                </span>
                <strong style={{ color: "var(--gold)" }}>${s.suggested_price.toFixed(2)}</strong>
                <span className={s.change_pct >= 0 ? "delta-up" : "delta-down"} style={{ marginLeft: 6 }}>
                  {s.change_pct >= 0 ? "+" : ""}{s.change_pct}%
                </span>
              </div>
              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 7 }}>
                <button className="btn primary" onClick={() => decide(s.id, "accepted")}>Apply</button>
                <button className="btn ghost" onClick={() => decide(s.id, "rejected")}>Dismiss</button>
              </div>
            </div>
          </div>
        ))}
        {decided.length > 0 && (
          <details style={{ marginTop: 10 }}>
            <summary style={{ color: "var(--muted)", fontSize: 12.5, cursor: "pointer" }}>
              {decided.length} decided
            </summary>
            {decided.map((s) => (
              <div className="row" key={s.id}>
                <span style={{ fontSize: 13 }}>{s.item_name}</span>
                <span className="badge" style={{
                  color: s.status === "accepted" ? "var(--status-good)" : "var(--muted)",
                }}>
                  {s.status === "accepted" ? `✓ applied $${s.suggested_price.toFixed(2)}` : "dismissed"}
                </span>
              </div>
            ))}
          </details>
        )}
      </div>

      {/* ---- Sales overview ---- */}
      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", marginTop: 16 }}>
        <div className="card">
          <h3>Revenue — last 30 days</h3>
          <div className="sub">Nightly takings, all channels</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={summary.revenue_30d} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} minTickGap={30}
                     tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={fmtK} width={46}
                     tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<Tip />} cursor={{ stroke: "var(--muted)", strokeDasharray: "3 3" }} />
              <Line type="monotone" dataKey="revenue" name="Revenue" stroke="var(--series-1)"
                    strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3>Low stock</h3>
          <div className="sub">Below par level — reorder</div>
          {summary.low_stock.length === 0 && <p className="page-sub">All items at par.</p>}
          {summary.low_stock.map((s) => {
            const severe = s.stock / s.par_level < 0.5;
            return (
              <div className="row" key={s.item_id}>
                <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span className="dot" style={{ background: severe ? "var(--status-critical)" : "var(--status-serious)" }} />
                  <span style={{ fontSize: 13.5 }}>{severe ? "⚠ " : ""}{s.name}</span>
                </span>
                <span className="badge">{s.stock} / par {s.par_level}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr", marginTop: 16 }}>
        <div className="card">
          <h3>Top sellers — last 7 days</h3>
          <div className="sub">By portions sold</div>
          <ResponsiveContainer width="100%" height={Math.max(200, summary.top_sellers_7d.length * 34)}>
            <BarChart data={summary.top_sellers_7d} layout="vertical"
                      margin={{ top: 0, right: 24, left: 0, bottom: 0 }} barCategoryGap="26%">
              <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 11 }}
                     axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="name" width={230}
                     tick={{ fill: "var(--ink-2)", fontSize: 12.5 }} axisLine={false} tickLine={false} />
              <Tooltip content={<Tip money={false} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="qty" name="Portions" fill="var(--series-1)" radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
