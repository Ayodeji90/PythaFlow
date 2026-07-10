import { useEffect, useState } from "react";
import api from "../api";

const CHANNELS = [
  { id: "instagram", label: "Instagram" },
  { id: "facebook", label: "Facebook" },
  { id: "email", label: "Email newsletter" },
];
const STATUS_BADGE = {
  draft: { label: "Draft", color: "var(--ink-2)" },
  approved: { label: "✓ Approved", color: "var(--status-good)" },
  scheduled: { label: "◷ Scheduled", color: "var(--series-2)" },
};

export default function MarketingPage() {
  const [channel, setChannel] = useState("instagram");
  const [topic, setTopic] = useState("");
  const [drafts, setDrafts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState({}); // id -> body text

  useEffect(() => { api.drafts().then(setDrafts).catch((e) => setError(e.message)); }, []);

  async function generate() {
    setBusy(true); setError(null);
    try {
      const d = await api.generateMarketing({ channel, topic: topic || null, tone: "elegant" });
      setDrafts((list) => [d, ...list]);
      setTopic("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id, status) {
    const updated = await api.updateDraft(id, { status });
    setDrafts((list) => list.map((d) => (d.id === id ? updated : d)));
  }

  async function saveBody(id) {
    const updated = await api.updateDraft(id, { body: editing[id] });
    setDrafts((list) => list.map((d) => (d.id === id ? updated : d)));
    setEditing(({ [id]: _, ...rest }) => rest);
  }

  return (
    <div className="page" style={{ maxWidth: 760 }}>
      <h1 className="page-title">AI Marketing Studio</h1>
      <p className="page-sub">
        On-brand copy drafted from live sales data, events, and the season — you approve before anything ships.
      </p>

      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {CHANNELS.map((c) => (
            <button key={c.id} className={`chip ${channel === c.id ? "active" : ""}`}
                    onClick={() => setChannel(c.id)}>
              {c.label}
            </button>
          ))}
          <input
            style={{ flex: 1, minWidth: 200 }}
            placeholder="Optional angle (e.g. 'wine cellar dinner on the 24th')"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <button className="btn primary" onClick={generate} disabled={busy}>
            {busy ? "Writing…" : "Generate"}
          </button>
        </div>
      </div>

      {error && <p style={{ color: "var(--status-critical)" }}>⚠ {error}</p>}

      {drafts.map((d) => (
        <div className="card" key={d.id} style={{ marginTop: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
            <h3 style={{ margin: 0 }}>{d.title}</h3>
            <span className="badge" style={{ color: STATUS_BADGE[d.status].color }}>
              {STATUS_BADGE[d.status].label}
            </span>
          </div>
          <div className="sub">{d.channel} · {d.created_at}{d.engine ? ` · ${d.engine === "claude" ? "Claude AI" : "template (no API key)"}` : ""}</div>

          {editing[d.id] !== undefined ? (
            <>
              <textarea rows={6} style={{ width: "100%" }} value={editing[d.id]}
                        onChange={(e) => setEditing((s) => ({ ...s, [d.id]: e.target.value }))} />
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn primary" onClick={() => saveBody(d.id)}>Save</button>
                <button className="btn ghost" onClick={() => setEditing(({ [d.id]: _, ...r }) => r)}>Cancel</button>
              </div>
            </>
          ) : (
            <p style={{ whiteSpace: "pre-wrap", color: "var(--ink)", fontSize: 14 }}>{d.body}</p>
          )}

          {d.status === "draft" && editing[d.id] === undefined && (
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn primary" onClick={() => setStatus(d.id, "approved")}>Approve</button>
              <button className="btn" onClick={() => setEditing((s) => ({ ...s, [d.id]: d.body }))}>Edit</button>
            </div>
          )}
          {d.status === "approved" && (
            <button className="btn" onClick={() => setStatus(d.id, "scheduled")}>Schedule</button>
          )}
        </div>
      ))}

      {drafts.length === 0 && !error && (
        <p className="page-sub" style={{ marginTop: 18 }}>No drafts yet — generate your first piece above.</p>
      )}
    </div>
  );
}
