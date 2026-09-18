import { useEffect, useState } from "react";
import { OrderList } from "../../components/ui";

function PasswordGate({ onUnlock }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function tryUnlock() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: value }),
      });
      let data = {};
      try {
        data = await r.json();
      } catch {
        // Server sent back something that isn't JSON (e.g. a raw 500 error
        // page) — treat it as an unexpected-failure message instead of
        // letting the JSON.parse error itself leak into the UI.
        throw new Error(`Server error (${r.status}). Check the deployment logs.`);
      }
      if (!r.ok) throw new Error(data.error || "Login failed");
      onUnlock(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-wrap" style={{ maxWidth: 360 }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>Admin login</h1>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input className="input" type="password" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && tryUnlock()} placeholder="Admin password" autoComplete="current-password" />
        <button className="primary-btn" onClick={tryUnlock} disabled={loading}>{loading ? "Signing in…" : "Sign in"}</button>
        {error && <p style={{ color: "var(--red)", fontSize: 13, margin: 0 }}>{error}</p>}
      </div>
    </div>
  );
}

export default function AdminPage() {
  const [auth, setAuth] = useState(null);
  const [orders, setOrders] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [manualReview, setManualReview] = useState([]);
  const [tab, setTab] = useState("orders");

  async function load() {
    const [ordersRes, feedbackRes, reviewRes] = await Promise.all([fetch("/api/orders/list"), fetch("/api/feedback/list"), fetch("/api/orders/manual-review")]);
    if (ordersRes.status === 401 || feedbackRes.status === 401 || reviewRes.status === 401) {
      setAuth(false);
      return;
    }
    const ordersData = await ordersRes.json();
    const feedbackData = await feedbackRes.json();
    const reviewData = await reviewRes.json();
    setOrders(ordersData.orders || []);
    setFeedback(feedbackData.feedback || []);
    setManualReview(reviewData.orders || []);
    setAuth(true);
  }

  useEffect(() => { fetch("/api/admin/me").then((r) => r.json()).then((d) => setAuth(d.authenticated)); }, []);
  useEffect(() => { if (auth) load(); }, [auth]);

  async function manualAction(reference, action) {
    const note = window.prompt(action === "confirm_fulfilled" ? "Confirm provider delivery and enter a brief note:" : "Confirm provider did not deliver and enter a brief note before retrying:");
    if (!note || note.trim().length < 5) return;
    const r = await fetch("/api/orders/manual-review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reference, action, note }) });
    const d = await r.json();
    if (!r.ok) return window.alert(d.error || "Could not update the order");
    await load();
  }

  async function logout() {
    await fetch("/api/admin/logout", { method: "POST" });
    setAuth(false);
  }

  if (auth === null) return null;
  if (!auth) return <PasswordGate onUnlock={() => setAuth(true)} />;

  const totalSales = orders.filter((o) => o.status === "success").reduce((s, o) => s + Number(o.amount), 0);

  return (
    <div className="page-wrap">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: "0 0 4px" }}>Admin</h1>
          <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 0, marginBottom: 24 }}>Secure admin session expires after 8 hours.</p>
        </div>
        <button className="nav-item" onClick={logout} style={{ width: "auto", padding: "6px 12px" }}>Sign out</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <div className="stat-card"><div style={{ fontSize: 14, color: "var(--muted)" }}>Total sales</div><div className="heading-font" style={{ fontSize: 24, fontWeight: 600 }}>GHS {totalSales.toFixed(2)}</div></div>
        <div className="stat-card"><div style={{ fontSize: 14, color: "var(--muted)" }}>Orders</div><div className="heading-font" style={{ fontSize: 24, fontWeight: 600 }}>{orders.length}</div></div>
        <div className="stat-card"><div style={{ fontSize: 14, color: "var(--muted)" }}>Open feedback</div><div className="heading-font" style={{ fontSize: 24, fontWeight: 600 }}>{feedback.filter((f) => f.status === "open").length}</div></div><div className="stat-card"><div style={{ fontSize: 14, color: "var(--muted)" }}>Manual review</div><div className="heading-font" style={{ fontSize: 24, fontWeight: 600 }}>{manualReview.length}</div></div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button className="nav-item" style={{ width: "auto", padding: "6px 12px", background: tab === "orders" ? "var(--surface-raised)" : "transparent", borderColor: "var(--line)" }} onClick={() => setTab("orders")}>Orders</button>
        <button className="nav-item" style={{ width: "auto", padding: "6px 12px", background: tab === "feedback" ? "var(--surface-raised)" : "transparent", borderColor: "var(--line)" }} onClick={() => setTab("feedback")}>Feedback</button><button className="nav-item" style={{ width: "auto", padding: "6px 12px", background: tab === "review" ? "var(--surface-raised)" : "transparent", borderColor: "var(--line)" }} onClick={() => setTab("review")}>Manual Review ({manualReview.length})</button>
      </div>

      {tab === "orders" && <OrderList items={orders} />}
      {tab === "review" && <div className="card" style={{ overflow: "hidden" }}>
        {manualReview.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 14 }}>No orders currently require manual review.</div>}
        {manualReview.map((o) => (
          <div key={o.reference} className="tx-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 5 }}>
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}><strong>{o.reference}</strong><span style={{ fontSize: 12, color: "var(--muted-dim)" }}>{new Date(o.createdAt).toLocaleString()}</span></div>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>GHS {Number(o.amount).toFixed(2)} · {o.orderType} · {o.network || "service"}</div>
            <div style={{ fontSize: 12, color: "var(--muted-dim)" }}>{o.lastFulfillmentError || "Provider outcome requires confirmation before any retry."}</div>
            <div style={{ fontSize: 12, color: "var(--price)" }}>Confirm the provider outcome before taking action. The buttons below create an admin audit note.</div><div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}><button className="nav-item" style={{ width: "auto", padding: "6px 10px" }} onClick={() => manualAction(o.reference, "confirm_fulfilled")}>Mark fulfilled</button><button className="nav-item" style={{ width: "auto", padding: "6px 10px" }} onClick={() => manualAction(o.reference, "retry")}>Authorize retry</button></div>
          </div>
        ))}
      </div>}
      {tab === "feedback" && <div className="card" style={{ overflow: "hidden" }}>
        {feedback.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 14 }}>No feedback yet.</div>}
        {feedback.map((f) => (
          <div key={f.id} className="tx-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%", gap: 12 }}><span style={{ fontSize: 14, fontWeight: 600 }}>{f.name} · <span style={{ color: "var(--muted)", fontWeight: 400 }}>{f.category}</span></span><div style={{ display: "flex", alignItems: "center", gap: 8 }}><select className="input" style={{ width: "auto", padding: "4px 8px", fontSize: 12 }} value={f.status || "open"} onChange={async (e) => { const r = await fetch("/api/feedback/status", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: f.id, status: e.target.value }) }); if (r.ok) { const d = await r.json(); setFeedback((prev) => prev.map((x) => x.id === f.id ? d.feedback : x)); } }}><option value="open">Open</option><option value="in_progress">In progress</option><option value="resolved">Resolved</option></select><span style={{ fontSize: 12, color: "var(--muted-dim)" }}>{new Date(f.createdAt).toLocaleString()}</span></div></div>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>{f.message}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5, marginTop: 2 }}>
              <div><strong>Case:</strong> {f.caseReference || "—"} {f.orderReference ? <>· <strong>Order:</strong> {f.orderReference}</> : null}</div>
              <div><strong>Service:</strong> {f.serviceType || "—"} · <strong>Transaction ID:</strong> {f.transactionId || "—"} · <strong>Amount:</strong> {f.transactionAmount != null ? `GHS ${Number(f.transactionAmount).toFixed(2)}` : "—"}</div>
              {f.requestedData ? <div><strong>Requested:</strong> {f.requestedData}</div> : null}
              {f.beneficiary ? <div><strong>Beneficiary:</strong> {f.beneficiary}</div> : null}
              {f.transactionAt ? <div><strong>Transaction time:</strong> {new Date(f.transactionAt).toLocaleString()}</div> : null}
              <div><strong>Transaction details:</strong> {f.transactionDetails || "—"}</div>
            </div>
            {(f.email || f.phone) && <div style={{ fontSize: 12, color: "var(--muted-dim)" }}>{[f.email, f.phone].filter(Boolean).join(" · ")}</div>}
          </div>
        ))}
      </div>}
    </div>
  );
}
