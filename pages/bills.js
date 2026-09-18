import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { Field, EmailField, PrimaryButton, Toast, BILL_PROVIDERS, NoRefundNotice, NetworkBadge } from "../components/ui";
import { payAndFulfil } from "../lib/payment";

export default function BillsPage() {
  const router = useRouter();
  const [provider, setProvider] = useState("ecg");
  const [meterNumber, setMeterNumber] = useState("");
  const [phone, setPhone] = useState("");
  const [amount, setAmount] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  // ECG: fraud-prevention lookup before topping up
  const [ecgLookup, setEcgLookup] = useState(null); // { customerName, district } | "error" | null
  const [lookingUp, setLookingUp] = useState(false);

  // Water: fixed bill amount, resolved from Techlink, not typed by the customer
  const [waterBill, setWaterBill] = useState(null); // { accountName, amountDue } | "error" | null
  const [checkingBill, setCheckingBill] = useState(false);

  useEffect(() => {
    setEmail(window.localStorage.getItem("pj_email") || "");
    setPhone(window.localStorage.getItem("pj_phone") || "");
  }, []);

  useEffect(() => {
    setEcgLookup(null);
    setWaterBill(null);
    setMeterNumber("");
    setAmount("");
  }, [provider]);

  function lookupEcg() {
    setLookingUp(true);
    setEcgLookup(null);
    fetch(`/api/techlink/ecg-lookup?meter=${encodeURIComponent(meterNumber)}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.error) setEcgLookup("error");
        else setEcgLookup(d);
      })
      .catch(() => setEcgLookup("error"))
      .finally(() => setLookingUp(false));
  }

  function checkWaterBill() {
    setCheckingBill(true);
    setWaterBill(null);
    fetch("/api/techlink/water-validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account: meterNumber }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.error) setWaterBill("error");
        else setWaterBill(d);
      })
      .catch(() => setWaterBill("error"))
      .finally(() => setCheckingBill(false));
  }

  const ecgValid = meterNumber.length >= 4 && phone.length >= 10 && Number(amount) > 0 && email.includes("@");
  const waterValid = waterBill && waterBill !== "error" && phone.length >= 10 && email.includes("@");

  function submit() {
    setLoading(true);
    payAndFulfil({
      orderType: provider,
      phone,
      email,
      meterNumber,
      billAmount: provider === "ecg" ? Number(amount) : undefined,
      onDone: () => {
        setLoading(false);
        window.localStorage.setItem("pj_email", email);
        window.localStorage.setItem("pj_phone", phone);
        setToast({ type: "success", message: `${BILL_PROVIDERS[provider].label} payment submitted` });
        setTimeout(() => router.push("/dashboard"), 1200);
      },
      onError: (msg) => {
        setLoading(false);
        setToast({ type: "error", message: msg });
      },
    });
  }

  return (
    <div className="page-wrap" style={{ maxWidth: 460 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Pay a bill</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>ECG electricity and Ghana Water, paid in one place.</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Field label="Provider">
          <div className="network-picker">
            {Object.entries(BILL_PROVIDERS).map(([id, p]) => (
              <button
                key={id}
                className={`network-btn ${provider === id ? "active" : ""}`}
                onClick={() => setProvider(id)}
                style={provider === id ? { borderColor: p.color } : undefined}
              >
                <NetworkBadge id={id} palette={BILL_PROVIDERS} size={18} />
                {p.label}
              </button>
            ))}
          </div>
        </Field>

        {provider === "ecg" && (
          <>
            <Field label="Meter number">
              <div style={{ display: "flex", gap: 8 }}>
                <input className="input" style={{ flex: 1 }} value={meterNumber} onChange={(e) => setMeterNumber(e.target.value)} placeholder="e.g. 0210444711" />
                <button className="primary-btn" style={{ width: "auto", padding: "0 16px" }} onClick={lookupEcg} disabled={meterNumber.length < 4 || lookingUp}>
                  {lookingUp ? "..." : "Look up"}
                </button>
              </div>
            </Field>
            {ecgLookup === "error" && <p style={{ color: "var(--red)", fontSize: 13, margin: 0 }}>Could not find that meter — double-check the number.</p>}
            {ecgLookup && ecgLookup !== "error" && (
              <div className="card" style={{ padding: 12, fontSize: 13 }}>
                Meter belongs to <strong>{ecgLookup.customerName}</strong>{ecgLookup.district ? ` · ${ecgLookup.district}` : ""}
              </div>
            )}
            <Field label="Phone number">
              <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
            </Field>
            <Field label="Amount to top up (GHS)">
              <input className="input" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="50.00" type="number" />
            </Field>
            <EmailField email={email} setEmail={setEmail} />
            <PrimaryButton disabled={!ecgValid} loading={loading} onClick={submit}>
              Pay GHS {amount || "0.00"} with Paystack
            </PrimaryButton>
            <p style={{ fontSize: 12, color: "var(--muted-dim)", margin: 0 }}>
              Look up the meter first to confirm whose account you're topping up.
            </p>
            <NoRefundNotice />
          </>
        )}

        {provider === "water" && (
          <>
            <Field label="Ghana Water account / meter number">
              <div style={{ display: "flex", gap: 8 }}>
                <input className="input" style={{ flex: 1 }} value={meterNumber} onChange={(e) => setMeterNumber(e.target.value)} placeholder="e.g. 0500123456" />
                <button className="primary-btn" style={{ width: "auto", padding: "0 16px" }} onClick={checkWaterBill} disabled={meterNumber.length < 4 || checkingBill}>
                  {checkingBill ? "..." : "Check bill"}
                </button>
              </div>
            </Field>
            {waterBill === "error" && <p style={{ color: "var(--red)", fontSize: 13, margin: 0 }}>Could not find a bill for that account — double-check the number.</p>}
            {waterBill && waterBill !== "error" && (
              <div className="card" style={{ padding: 12, fontSize: 13 }}>
                <div><strong>{waterBill.accountName || waterBill.customerName}</strong></div>
                <div style={{ marginTop: 4 }}>Amount due: <strong>GHS {Number(waterBill.amountDue ?? waterBill.amount).toFixed(2)}</strong></div>
              </div>
            )}
            <Field label="Phone number">
              <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
            </Field>
            <EmailField email={email} setEmail={setEmail} />
            <PrimaryButton disabled={!waterValid} loading={loading} onClick={submit}>
              {waterBill && waterBill !== "error"
                ? `Pay GHS ${Number(waterBill.amountDue ?? waterBill.amount).toFixed(2)} with Paystack`
                : "Check your bill first"}
            </PrimaryButton>
            <NoRefundNotice />
          </>
        )}
      </div>
      <Toast toast={toast} />
    </div>
  );
}
