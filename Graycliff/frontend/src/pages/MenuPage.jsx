import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "../api";

const CATEGORY_ORDER = ["Starter", "Main", "Tasting", "Dessert", "Wine", "Beverage", "Cigar"];

export default function MenuPage() {
  const [params] = useSearchParams();
  const table = Number(params.get("table") ?? 12);
  const guestId = params.get("guest") ? Number(params.get("guest")) : null;

  const [menu, setMenu] = useState([]);
  const [guest, setGuest] = useState(null);
  const [forYou, setForYou] = useState([]);       // personalized picks (returning guests)
  const [category, setCategory] = useState("All");
  const [cart, setCart] = useState({});           // item_id -> qty
  const [upsell, setUpsell] = useState(null);     // instant pairing prompt on add
  const [cartUpsells, setCartUpsells] = useState([]); // recommender-driven, follows the cart
  const [reviewing, setReviewing] = useState(false);
  const [placed, setPlaced] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.menu().then(setMenu).catch((e) => setError(e.message));
    if (guestId) {
      api.guest(guestId).then(setGuest).catch(() => {});
      api.recommendations(guestId).then((r) => setForYou(r.recommendations)).catch(() => {});
    }
  }, [guestId]);

  // Refresh upsell suggestions as the cart changes (debounced).
  useEffect(() => {
    const ids = Object.keys(cart);
    if (ids.length === 0) { setCartUpsells([]); return; }
    const t = setTimeout(() => {
      api.recommendations(guestId, ids).then((r) => setCartUpsells(r.recommendations)).catch(() => {});
    }, 350);
    return () => clearTimeout(t);
  }, [cart, guestId]);

  const byId = useMemo(() => Object.fromEntries(menu.map((m) => [m.id, m])), [menu]);
  const cats = ["All", ...CATEGORY_ORDER.filter((c) => menu.some((m) => m.category === c))];
  const visible = menu.filter((m) => category === "All" || m.category === category);

  const cartLines = Object.entries(cart).map(([id, qty]) => ({ item: byId[id], qty }));
  const total = cartLines.reduce((s, l) => s + (l.item?.price ?? 0) * l.qty, 0);
  const count = cartLines.reduce((s, l) => s + l.qty, 0);

  function add(item) {
    setCart((c) => ({ ...c, [item.id]: (c[item.id] ?? 0) + 1 }));
    // Wine-pairing upsell straight from the menu graph (recommender API refines this)
    if (item.pairing_item_id && !cart[item.pairing_item_id]) {
      const wine = byId[item.pairing_item_id];
      if (wine) setUpsell({ forItem: item, suggest: wine });
    } else {
      setUpsell(null);
    }
  }

  function changeQty(id, d) {
    setCart((c) => {
      const next = { ...c, [id]: (c[id] ?? 0) + d };
      if (next[id] <= 0) delete next[id];
      return next;
    });
  }

  async function placeOrder() {
    try {
      const payload = {
        items: cartLines.map((l) => ({ item_id: l.item.id, qty: l.qty })),
        guest_id: guestId, table_no: table, covers: Math.max(1, Math.min(count, 6)),
        channel: "qr-menu",
      };
      const order = await api.createOrder(payload);
      setPlaced(order);
      setCart({}); setReviewing(false); setUpsell(null);
    } catch (e) {
      setError(e.message);
    }
  }

  if (placed) {
    return (
      <div className="page" style={{ maxWidth: 560 }}>
        <h1 className="page-title">Merci — order received</h1>
        <p className="page-sub">Order #{placed.id} · Table {placed.table_no}</p>
        <div className="card">
          {placed.items.map((it) => (
            <div className="row" key={it.item_id}>
              <span>{it.qty} × {it.name}</span>
              <span className="price">${(it.unit_price * it.qty).toFixed(0)}</span>
            </div>
          ))}
          <div className="row" style={{ fontWeight: 600 }}>
            <span>Total</span><span style={{ color: "var(--gold)" }}>${placed.total.toFixed(0)}</span>
          </div>
        </div>
        <p className="page-sub" style={{ marginTop: 16 }}>
          The kitchen has your order. Your server will confirm shortly.
        </p>
        <button className="btn" onClick={() => setPlaced(null)}>Back to menu</button>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 760 }}>
      <h1 className="page-title">Graycliff Restaurant</h1>
      <p className="page-sub">
        West Hill Street, Nassau · Table {table}
        {guest && <> · Welcome back, <span style={{ color: "var(--gold)" }}>{guest.name.split(" ")[0]}</span>{guest.tier === "VIP" && " ✦"}</>}
      </p>

      {error && <p style={{ color: "var(--status-critical)" }}>⚠ {error}</p>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
        {cats.map((c) => (
          <button key={c} className={`chip ${c === category ? "active" : ""}`} onClick={() => setCategory(c)}>
            {c}
          </button>
        ))}
      </div>

      {forYou.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 19, color: "var(--gold)", borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
            For you{guest ? `, ${guest.name.split(" ")[0]}` : ""}
          </h2>
          {forYou.slice(0, 4).map(({ item, reason }) => (
            <div className="menu-item" key={`fy-${item.id}`}>
              <div>
                <div className="name">{item.name}</div>
                <div className="desc">
                  <span style={{ color: "var(--gold)" }}>✦ {reason}</span> · {item.description}
                </div>
              </div>
              <div style={{ textAlign: "right", minWidth: 92 }}>
                <div className="price">${item.price.toFixed(0)}</div>
                <button className="btn ghost" style={{ marginTop: 6, padding: "4px 12px" }}
                        onClick={() => add(byId[item.id] ?? item)}>
                  {cart[item.id] ? `Added ×${cart[item.id]}` : "Add"}
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {upsell && (
        <div className="upsell">
          <div style={{ fontSize: 13.5 }}>
            <span style={{ color: "var(--gold)" }}>Sommelier's pairing</span> — with your{" "}
            <em>{upsell.forItem.name}</em>, may we suggest the <strong>{upsell.suggest.name}</strong>
            {" "}(${upsell.suggest.price.toFixed(0)})?
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn primary" onClick={() => { add(upsell.suggest); setUpsell(null); }}>
              Add pairing
            </button>
            <button className="btn ghost" onClick={() => setUpsell(null)}>No, thank you</button>
          </div>
        </div>
      )}

      {CATEGORY_ORDER.filter((c) => visible.some((m) => m.category === c)).map((c) => (
        <section key={c} style={{ marginBottom: 26 }}>
          <h2 style={{ fontSize: 19, color: "var(--gold)", borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>{c}s</h2>
          {visible.filter((m) => m.category === c).map((m) => (
            <div className="menu-item" key={m.id}>
              <div>
                <div className="name">{m.name}</div>
                <div className="desc">{m.description}</div>
              </div>
              <div style={{ textAlign: "right", minWidth: 92 }}>
                <div className="price">${m.price.toFixed(0)}</div>
                <button className="btn ghost" style={{ marginTop: 6, padding: "4px 12px" }} onClick={() => add(m)}>
                  {cart[m.id] ? `Added ×${cart[m.id]}` : "Add"}
                </button>
              </div>
            </div>
          ))}
        </section>
      ))}

      {count > 0 && !reviewing && (
        <div className="cart-bar">
          <span>{count} item{count > 1 ? "s" : ""} · <strong style={{ color: "var(--gold)" }}>${total.toFixed(0)}</strong></span>
          <button className="btn primary" onClick={() => setReviewing(true)}>Review order</button>
        </div>
      )}

      {reviewing && (
        <div className="cart-bar" style={{ flexDirection: "column", alignItems: "stretch", gap: 10, maxHeight: "60vh", overflowY: "auto" }}>
          {cartLines.map((l) => (
            <div className="row" key={l.item.id}>
              <span>{l.item.name}</span>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="btn ghost" onClick={() => changeQty(l.item.id, -1)}>−</button>
                {l.qty}
                <button className="btn ghost" onClick={() => changeQty(l.item.id, +1)}>+</button>
                <span className="price" style={{ minWidth: 56, textAlign: "right" }}>${(l.item.price * l.qty).toFixed(0)}</span>
              </span>
            </div>
          ))}
          {cartUpsells.length > 0 && (
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <div style={{ fontSize: 12, color: "var(--gold)", marginBottom: 4 }}>May we also suggest</div>
              {cartUpsells.map(({ item, reason }) => (
                <div className="row" key={`up-${item.id}`}>
                  <span style={{ fontSize: 13 }}>
                    {item.name} <span style={{ color: "var(--muted)" }}>· ${item.price.toFixed(0)}</span>
                    <span style={{ color: "var(--muted)", display: "block", fontSize: 11.5 }}>{reason}</span>
                  </span>
                  <button className="btn ghost" onClick={() => add(byId[item.id] ?? item)}>Add</button>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Total ${total.toFixed(0)}</strong>
            <span style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={() => setReviewing(false)}>Back</button>
              <button className="btn primary" onClick={placeOrder}>Send to kitchen</button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
