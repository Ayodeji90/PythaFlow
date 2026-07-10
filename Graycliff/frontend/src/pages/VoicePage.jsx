import { useEffect, useRef, useState } from "react";
import api from "../api";

const SUGGESTIONS = [
  "I'd like the lobster thermidor and a glass of Chablis",
  "Book a table for four tomorrow at 8pm",
  "Two conch fritters and a Bahama Mama please",
];

export default function VoicePage() {
  const [supported, setSupported] = useState(true);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const recRef = useRef(null);

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setSupported(false); return; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0].transcript).join(" ");
      setTranscript(text);
      if (e.results[e.results.length - 1].isFinal) send(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
  }, []);

  function toggleMic() {
    if (!recRef.current) return;
    if (listening) { recRef.current.stop(); setListening(false); }
    else { setTranscript(""); setResult(null); recRef.current.start(); setListening(true); }
  }

  async function send(text) {
    if (!text.trim()) return;
    setBusy(true); setError(null);
    try {
      const r = await api.voice({ transcript: text });
      setResult(r);
      if (window.speechSynthesis) {
        const u = new SpeechSynthesisUtterance(r.reply);
        u.rate = 0.95;
        window.speechSynthesis.speak(u);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <h1 className="page-title">Voice Concierge</h1>
      <p className="page-sub">Speak an order or book a table — AI handles the rest.</p>

      <div className="card" style={{ textAlign: "center", padding: "30px 20px" }}>
        <button
          className="btn primary"
          onClick={toggleMic}
          disabled={!supported}
          style={{
            width: 92, height: 92, borderRadius: "50%", fontSize: 34,
            boxShadow: listening ? "0 0 0 12px rgba(201,162,39,0.15)" : "none",
          }}
        >
          {listening ? "◼" : "🎙"}
        </button>
        <p className="page-sub" style={{ marginTop: 14, marginBottom: 0 }}>
          {supported
            ? listening ? "Listening… speak naturally" : "Tap to speak"
            : "This browser has no speech recognition — type below instead"}
        </p>
        {transcript && <p style={{ color: "var(--cream)", fontStyle: "italic" }}>"{transcript}"</p>}

        <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <input
            style={{ flex: 1 }}
            placeholder="…or type your request"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { setTranscript(typed); send(typed); } }}
          />
          <button className="btn" disabled={busy || !typed.trim()}
                  onClick={() => { setTranscript(typed); send(typed); }}>
            {busy ? "…" : "Send"}
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12, justifyContent: "center" }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => { setTyped(s); setTranscript(s); send(s); }}>
              "{s}"
            </button>
          ))}
        </div>
      </div>

      {error && <p style={{ color: "var(--status-critical)" }}>⚠ {error}</p>}

      {result && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>
            {result.action.type === "order" ? "Order sent to kitchen" :
             result.action.type === "reservation" ? "Reservation confirmed" : "Heard you"}
          </h3>
          <div className="sub">
            intent: {result.intent} · engine: {result.engine === "rules" ? "rule-based (no AI provider)" : `AI (${result.engine})`}
          </div>
          <p style={{ color: "var(--cream)" }}>"{result.reply}"</p>

          {result.action.type === "order" && (
            <>
              {result.action.order.items.map((it) => (
                <div className="row" key={it.item_id}>
                  <span>{it.qty} × {it.name}</span>
                  <span style={{ color: "var(--gold)" }}>${(it.unit_price * it.qty).toFixed(0)}</span>
                </div>
              ))}
              <div className="row" style={{ fontWeight: 600 }}>
                <span>Order #{result.action.order.id}</span>
                <span style={{ color: "var(--gold)" }}>${result.action.order.total.toFixed(0)}</span>
              </div>
            </>
          )}

          {result.action.type === "reservation" && (
            <div className="row">
              <span>
                {result.action.reservation.guest_name} · party of {result.action.reservation.party_size}
              </span>
              <span className="badge gold">
                {result.action.reservation.date} at {result.action.reservation.time}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
