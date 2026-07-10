export default function VoicePage() {
  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <h1 className="page-title">Voice Ordering & Reservations</h1>
      <p className="page-sub">Coming online in this demo build — speak an order or book a table.</p>
      <div className="card">
        <p className="page-sub" style={{ margin: 0 }}>
          This module is being wired up (browser speech → AI intent extraction → kitchen/reservation
          systems). Check back after the next build step.
        </p>
      </div>
    </div>
  );
}
