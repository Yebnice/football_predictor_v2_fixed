import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { NetworkPicker, Field, EmailField, PrimaryButton, Toast } from "../components/ui";
import { payAndFulfil } from "../lib/payment";

const REGIONS = [
  "Greater Accra", "Ashanti", "Western", "Western North", "Central", "Eastern",
  "Volta", "Oti", "Northern", "North East", "Savannah", "Upper East", "Upper West", "Bono", "Bono East", "Ahafo",
];
const OCCUPATIONS = ["Farmer", "Trader", "Fisherman", "Artisan", "Student", "Unemployed", "Other"];

export default function AfaPage() {
  const router = useRouter();
  const [network, setNetwork] = useState("mtn");
  const [fullName, setFullName] = useState("");
  const [ghanaCard, setGhanaCard] = useState("");
  const [phone, setPhone] = useState("");
  const [dob, setDob] = useState("");
  const [region, setRegion] = useState("");
  const [location, setLocation] = useState("");
  const [occupation, setOccupation] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [fee, setFee] = useState(null); // null = still loading from Techlink

  useEffect(() => {
    setEmail(window.localStorage.getItem("pj_email") || "");
    fetch("/api/techlink/afa-price")
      .then((r) => r.json())
      .then((d) => setFee(Number(d.price ?? d.amount)))
      .catch(() => setFee(null)); // stays null -> shown as "confirmed at checkout"
  }, []);

  const valid = fullName && ghanaCard && phone.length >= 10 && dob && region && location && occupation && email.includes("@");

  function submit() {
    setLoading(true);
    payAndFulfil({
      orderType: "afa",
      network,
      phone,
      email,
      afaDetails: { fullName, ghanaCard, dob, region, location, occupation },
      onDone: () => {
        setLoading(false);
        window.localStorage.setItem("pj_email", email);
        setToast({ type: "success", message: `${fullName} registered successfully` });
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
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>AFA registration</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>
          Register a farmer under the AFA programme.{" "}
          {fee != null ? `Registration fee: GHS ${fee.toFixed(2)}.` : "Fee is confirmed at checkout."}
        </p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Field label="Network"><NetworkPicker value={network} onChange={setNetwork} /></Field>
        <Field label="Full name">
          <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="e.g. Kwame Asante" />
        </Field>
        <Field label="Phone number">
          <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
        </Field>
        <Field label="Ghana Card number">
          <input className="input" value={ghanaCard} onChange={(e) => setGhanaCard(e.target.value)} placeholder="GHA-000000000-0" />
        </Field>
        <Field label="Date of birth">
          <input className="input" value={dob} onChange={(e) => setDob(e.target.value)} type="date" />
        </Field>
        <Field label="Region">
          <select className="input" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">Select a region</option>
            {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>
        <Field label="Specific location">
          <input className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Kumasi, Adum" />
        </Field>
        <Field label="Occupation">
          <select className="input" value={occupation} onChange={(e) => setOccupation(e.target.value)}>
            <option value="">Select an occupation</option>
            {OCCUPATIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
        <EmailField email={email} setEmail={setEmail} />
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          {fee != null ? `Pay GHS ${fee.toFixed(2)} & submit registration` : "Submit registration"}
        </PrimaryButton>
      </div>
      <Toast toast={toast} />
    </div>
  );
}
