import { useEffect, useState } from "react";
import api from "../api";

const CATEGORIES = ["property", "hours", "dining", "services", "policies", "faq"];
const CATEGORY_LABEL = {
  property: "The Property", hours: "Hours", dining: "Dining",
  services: "Services & Experiences", policies: "Policies", faq: "FAQ",
};
const EMPTY_FORM = { category: "faq", topic: "", question: "", content: "", keywords: "", priority: 5 };

export default function KnowledgePage() {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState({});   // id -> draft content
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);

  const load = () => api.knowledge().then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function save(id) {
    await api.updateKnowledge(id, { content: editing[id] });
    setEditing(({ [id]: _, ...rest }) => rest);
    load();
  }
  async function toggleVerified(entry) {
    await api.updateKnowledge(entry.id, { verified: !entry.verified });
    load();
  }
  async function remove(id) {
    await api.deleteKnowledge(id);
    load();
  }
  async function create() {
    try {
      await api.createKnowledge({ ...form, priority: Number(form.priority) });
      setForm(EMPTY_FORM); setAdding(false); setError(null);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (error && !data) return <div className="page"><p style={{ color: "var(--status-critical)" }}>Backend unreachable: {error}</p></div>;
  if (!data) return <div className="page"><p className="page-sub">Loading…</p></div>;

  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <h1 className="page-title">Concierge Knowledge</h1>
      <p className="page-sub">
        Everything the AI concierge is allowed to say about the house. {data.total} entries ·{" "}
        {data.needs_confirmation > 0
          ? <span style={{ color: "var(--status-warning)" }}>{data.needs_confirmation} need client confirmation before go-live</span>
          : <span style={{ color: "var(--status-good)" }}>all confirmed</span>}
      </p>

      <div style={{ marginBottom: 18 }}>
        {!adding ? (
          <button className="btn primary" onClick={() => setAdding(true)}>+ Add entry</button>
        ) : (
          <div className="card">
            <h3>New entry</h3>
            <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
                </select>
                <input placeholder="Topic (e.g. happy_hour)" value={form.topic}
                       onChange={(e) => setForm({ ...form, topic: e.target.value })} style={{ flex: 1, minWidth: 160 }} />
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  {[10, 9, 8, 7, 6, 5, 4, 3].map((p) => <option key={p} value={p}>priority {p}{p >= 8 ? " (always in prompt)" : ""}</option>)}
                </select>
              </div>
              <input placeholder="Guest question this answers (optional)" value={form.question}
                     onChange={(e) => setForm({ ...form, question: e.target.value })} />
              <textarea rows={3} placeholder="What the concierge should say…" value={form.content}
                        onChange={(e) => setForm({ ...form, content: e.target.value })} />
              <input placeholder="Keywords, comma-separated (how guests ask for it)" value={form.keywords}
                     onChange={(e) => setForm({ ...form, keywords: e.target.value })} />
              {error && <span style={{ color: "var(--status-critical)", fontSize: 12.5 }}>⚠ {error}</span>}
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn primary" onClick={create}>Save entry</button>
                <button className="btn ghost" onClick={() => { setAdding(false); setError(null); }}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {CATEGORIES.map((cat) => {
        const entries = data.entries.filter((e) => e.category === cat);
        if (entries.length === 0) return null;
        return (
          <section key={cat} style={{ marginBottom: 26 }}>
            <h2 style={{ fontSize: 18, color: "var(--gold)", borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
              {CATEGORY_LABEL[cat]}
            </h2>
            {entries.map((e) => (
              <div className="card" key={e.id} style={{ marginTop: 10, padding: "14px 16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                  <div>
                    <strong style={{ fontSize: 14 }}>{e.topic.replace(/_/g, " ")}</strong>
                    {e.question && <span style={{ color: "var(--muted)", fontSize: 12.5, marginLeft: 8 }}>“{e.question}”</span>}
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {e.priority >= 8 && <span className="badge gold">core</span>}
                    <button className="badge" style={{
                      cursor: "pointer", background: "none",
                      color: e.verified ? "var(--status-good)" : "var(--status-warning)",
                      borderColor: e.verified ? "rgba(12,163,12,.45)" : "rgba(250,178,25,.45)",
                    }} onClick={() => toggleVerified(e)}
                       title="Toggle confirmation status">
                      {e.verified ? "✓ confirmed" : "⚠ confirm with client"}
                    </button>
                    <button className="btn ghost" style={{ padding: "2px 9px" }} title="Remove"
                            onClick={() => remove(e.id)}>✕</button>
                  </div>
                </div>

                {editing[e.id] !== undefined ? (
                  <>
                    <textarea rows={3} style={{ width: "100%", marginTop: 8 }} value={editing[e.id]}
                              onChange={(ev) => setEditing((s) => ({ ...s, [e.id]: ev.target.value }))} />
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <button className="btn primary" onClick={() => save(e.id)}>Save</button>
                      <button className="btn ghost" onClick={() => setEditing(({ [e.id]: _, ...r }) => r)}>Cancel</button>
                    </div>
                  </>
                ) : (
                  <p style={{ color: "var(--ink-2)", fontSize: 13.5, margin: "8px 0 0", cursor: "text" }}
                     onClick={() => setEditing((s) => ({ ...s, [e.id]: e.content }))}
                     title="Click to edit">
                    {e.content}
                  </p>
                )}
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
