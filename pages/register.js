import { useState } from "react";
import { Field, PrimaryButton } from "../components/ui";

export default function RegisterPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  const valid = name && email.includes("@") && phone.length >= 10;

  function submit() {
    setLoading(true);
    setMessage(null);
    fetch("/api/customers/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, phone }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          setMessage({ type: "error", text: d.error });
        } else {
          window.localStorage.setItem("pj_email", email);
          window.localStorage.setItem("pj_phone", phone);
          setMessage({ type: "success", text: "You're registered — your details will auto-fill next time you order." });
        }
      })
      .catch(() => setMessage({ type: "error", text: "Could not reach the server — try again." }))
      .finally(() => setLoading(false));
  }

  return (
    <div className="page-wrap" style={{ maxWidth: 420 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Create an account</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>
          Save your details so checkout is faster, and so we can reach you about your orders.
        </p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Field label="Full name">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
        </Field>
        <Field label="Email">
          <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" type="email" />
        </Field>
        <Field label="Phone number">
          <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
        </Field>
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          Register
        </PrimaryButton>
        {message && (
          <p style={{ fontSize: 13, color: message.type === "success" ? "var(--green)" : "var(--red)" }}>{message.text}</p>
        )}
      </div>
    </div>
  );
}
