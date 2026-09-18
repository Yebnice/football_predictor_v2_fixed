import { useEffect, useState } from "react";
import { NetworkPicker, Field, EmailField, PrimaryButton, Toast, NoRefundNotice, isLikelyAirtelTigoNumber } from "../components/ui";
import { payAndFulfil } from "../lib/payment";
import { useRouter } from "next/router";

export default function AirtimePage() {
  const router = useRouter();
  const [network, setNetwork] = useState("mtn");
  const [phone, setPhone] = useState("");
  const [amount, setAmount] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    setEmail(window.localStorage.getItem("pj_email") || "");
    setPhone(window.localStorage.getItem("pj_phone") || "");
  }, []);

  const valid = phone.length >= 10 && Number(amount) > 0 && email.includes("@");

  function submit() {
    setLoading(true);
    payAndFulfil({
      orderType: "airtime",
      network,
      phone,
      email,
      airtimeAmount: Number(amount),
      onDone: () => {
        setLoading(false);
        window.localStorage.setItem("pj_email", email);
        window.localStorage.setItem("pj_phone", phone);
        setToast({ type: "success", message: `GHS ${amount} airtime sent to ${phone}` });
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
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Buy airtime</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>Pay by card, mobile money or bank — instant delivery, all networks.</p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Field label="Network"><NetworkPicker value={network} onChange={setNetwork} /></Field>
        <Field label="Recipient phone number">
          <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
        </Field>
        {network === "airteltigo" && phone.length >= 3 && !isLikelyAirtelTigoNumber(phone) && (
          <p style={{ fontSize: 12, color: "var(--red)", margin: 0 }}>
            That doesn't look like an AirtelTigo number (026, 056, 027, 057, 023, 053) — wrong numbers aren't refunded.
          </p>
        )}
        <NoRefundNotice />
        <Field label="Amount (GHS)">
          <input className="input" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="10.00" type="number" />
        </Field>
        <EmailField email={email} setEmail={setEmail} />
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          Pay GHS {amount || "0.00"} with Paystack
        </PrimaryButton>
      </div>
      <Toast toast={toast} />
    </div>
  );
}
