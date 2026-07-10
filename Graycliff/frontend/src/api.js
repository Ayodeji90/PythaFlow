const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),
  menu: (category) => request(`/api/menu${category ? `?category=${category}` : ""}`),
  menuItem: (id) => request(`/api/menu/${id}`),
  dashboard: () => request("/api/dashboard/summary"),
  orders: (params = "") => request(`/api/orders${params}`),
  createOrder: (payload) =>
    request("/api/orders", { method: "POST", body: JSON.stringify(payload) }),
  guest: (id) => request(`/api/guests/${id}`),
  guests: (params = "") => request(`/api/guests${params}`),
  events: () => request("/api/events"),
  reservations: () => request("/api/reservations"),
  createReservation: (payload) =>
    request("/api/reservations", { method: "POST", body: JSON.stringify(payload) }),
  // Phase C+
  forecast: (itemId) => request(`/api/forecast${itemId ? `?item_id=${itemId}` : ""}`),
  suggestions: () => request("/api/pricing/suggestions"),
  decideSuggestion: (id, status) =>
    request(`/api/pricing/suggestions/${id}`, { method: "POST", body: JSON.stringify({ status }) }),
  wasteRisk: () => request("/api/pricing/waste-risk"),
  // Phase D
  recommendations: (guestId, cartIds = []) =>
    request(`/api/recommendations?guest_id=${guestId ?? ""}&cart=${cartIds.join(",")}`),
  // Phase E
  voice: (payload) => request("/api/voice/interpret", { method: "POST", body: JSON.stringify(payload) }),
  generateMarketing: (payload) =>
    request("/api/marketing/generate", { method: "POST", body: JSON.stringify(payload) }),
  drafts: () => request("/api/marketing/drafts"),
  updateDraft: (id, payload) =>
    request(`/api/marketing/drafts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
};

export default api;
