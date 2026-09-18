import { useEffect, useState } from "react";
import Link from "next/link";
import { OrderList } from "../components/ui";

export default function DashboardPage() {
  const [reference, setReference] = useState("");
  const [email, setEmail] = useState("");
  const [orders, setOrders] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      setReference(window.localStorage.getItem("pj_last_reference") || "");
      setEmail(window.localStorage.getItem("pj_email") || "");
    } catch {}
  }, []);

  useEffect(() => { if (reference && email) load(); }, [reference, email]);

  async function load() {
    setLoading(true); setError("");
    try {
      const r = await fetch(`/api/orders/track?reference=${encodeURIComponent(reference)}&email=${encodeURIComponent(email)}`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "Could not load your order");
      setOrders(d.orders);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  const processing = (orders || []).filter((o) => ["pending", "payment_verified"].includes(o.status) || ["ready", "processing", "failed", "manual_review"].includes(o.fulfillmentStatus));

  return (
    <div className="page-wrap" style={{ maxWidth: 640 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>My order</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>Use the reference and checkout email to view one order securely.</p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 20 }}>
        <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Order reference" />
        <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Checkout email" />
      </div>
      <button className="primary-btn" onClick={load} disabled={!reference || !email.includes("@") || loading}>{loading ? "Checking…" : "Check order"}</button>
      {error && <p style={{ color: "var(--red)", fontSize: 13 }}>{error}</p>}
      {orders && <>
        {processing.length > 0 && <div className="card" style={{ padding: 12, margin: "16px 0", fontSize: 13, borderColor: "var(--gold)" }}>Your order is still being processed. We are sorry for the delay. Please do not place a duplicate order; refresh this page later to see the latest status.</div>}
        <OrderList items={orders} />
      </>}
      {!reference && <p style={{ fontSize: 13, color: "var(--muted-dim)", marginTop: 16 }}>After checkout, your last order reference is saved on this device. You can also find the reference in your payment confirmation. <Link href="/track" style={{ color: "var(--price)" }}>Track an order</Link>.</p>}
    </div>
  );
}
