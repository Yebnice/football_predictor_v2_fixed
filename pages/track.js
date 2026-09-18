import { useEffect, useState } from "react";
import { Field, PrimaryButton, OrderList } from "../components/ui";

export default function TrackPage() {
  const [reference, setReference] = useState("");
  const [email, setEmail] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      setReference(window.localStorage.getItem("pj_last_reference") || "");
      setEmail(window.localStorage.getItem("pj_email") || "");
    } catch {}
  }, []);

  async function search() {
    setError(""); setLoading(true);
    try {
      const r = await fetch(`/api/orders/track?reference=${encodeURIComponent(reference)}&email=${encodeURIComponent(email)}`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "Could not find the order");
      setResults(d.orders);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  return (
    <div className="page-wrap" style={{ maxWidth: 560 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Track your order</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>For privacy, enter the order reference and the email you used when paying.</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Field label="Order reference"><input className="input" value={reference} onChange={(e) => setReference(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="TL..." /></Field>
        <Field label="Checkout email"><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="you@example.com" /></Field>
        <PrimaryButton onClick={search} disabled={!reference.trim() || !email.includes("@")} loading={loading}>Check order</PrimaryButton>
        {error && <p style={{ color: "var(--red)", fontSize: 13 }}>{error}</p>}
        {results && <div style={{ marginTop: 8 }}><div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>Order status</div>{results.some((o) => ["ready", "processing", "manual_review", "failed"].includes(o.fulfillmentStatus)) && <div className="card" style={{ padding: 12, marginBottom: 12, fontSize: 13, borderColor: "var(--gold)" }}>Your order is still being processed. We are sorry for the delay. Please do not place a duplicate order while we complete the request.</div>}<OrderList items={results} /></div>}
      </div>
    </div>
  );
}
