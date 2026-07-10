import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api from "../api";

const fmtMoney = (v) => `$${Math.round(v).toLocaleString()}`;
const fmtK = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`);

function Tip({ active, payload, label, money = true }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="k">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey}>
          <span className="k">{p.name || p.dataKey}</span>
          <strong>{money ? fmtMoney(p.value) : p.value.toLocaleString()}</strong>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.dashboard().then(setSummary).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="page"><p style={{ color: "var(--status-critical)" }}>Backend unreachable: {error}</p></div>;
  if (!summary) return <div className="page"><p className="page-sub">Loading…</p></div>;

  const t = summary.today;
  const revAvg = summary.revenue_30d.reduce((s, d) => s + d.revenue, 0) / summary.revenue_30d.length;
  const delta = ((t.revenue - revAvg) / revAvg) * 100;

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
          <div className="stat-label">Upcoming reservations</div>
          <div className="stat-value">{summary.upcoming_reservations}</div>
          <div className="page-sub" style={{ margin: 0 }}>next 14 days</div>
        </div>
        <div className="card">
          <div className="stat-label">VIP guests on file</div>
          <div className="stat-value">{summary.vip_guests}</div>
          <div className="page-sub" style={{ margin: 0 }}>loyalty programme</div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", marginTop: 16 }}>
        <div className="card">
          <h3>Revenue — last 30 days</h3>
          <div className="sub">Nightly takings, all channels</div>
          <ResponsiveContainer width="100%" height={240}>
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
