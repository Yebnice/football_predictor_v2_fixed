import { useEffect, useState } from "react";
import { Field, PrimaryButton } from "../components/ui";

const CATEGORIES = ["general", "delivery issue", "wrong amount", "payment issue", "other"];
const SERVICES = ["data", "airtime", "ECG", "water", "TV", "AFA", "result checker", "other"];

export default function FeedbackPage() {
  const [name, setName] = useState(""); const [email, setEmail] = useState(""); const [phone, setPhone] = useState("");
  const [orderReference, setOrderReference] = useState(""); const [serviceType, setServiceType] = useState("data");
  const [category, setCategory] = useState("delivery issue"); const [message, setMessage] = useState("");
  const [transactionId, setTransactionId] = useState(""); const [transactionAmount, setTransactionAmount] = useState("");
  const [requestedData, setRequestedData] = useState(""); const [beneficiary, setBeneficiary] = useState("");
  const [transactionAt, setTransactionAt] = useState(""); const [transactionDetails, setTransactionDetails] = useState("");
  const [loading, setLoading] = useState(false); const [status, setStatus] = useState(null); const [caseReference, setCaseReference] = useState(""); const [caseLookup, setCaseLookup] = useState(null);
  const isDataOrAirtime = serviceType === "data" || serviceType === "airtime";

  useEffect(() => { try { setEmail(window.localStorage.getItem("pj_email") || ""); setPhone(window.localStorage.getItem("pj_phone") || ""); setOrderReference(window.localStorage.getItem("pj_last_reference") || ""); } catch {} }, []);

  const valid = Boolean(name.trim() && (email.trim() || phone.trim()) && serviceType && message.trim().length >= 5 && transactionId.trim() && transactionAmount !== "" && transactionAt && transactionDetails.trim() && (!isDataOrAirtime || (requestedData.trim() && beneficiary.trim())));

  async function submit() {
    setLoading(true); setStatus(null);
    try {
      const r = await fetch("/api/feedback/create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, email, phone, orderReference, serviceType, category, message, transactionId, transactionAmount, requestedData, beneficiary, transactionAt, transactionDetails }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "Could not submit complaint");
      setStatus({ type: "success", text: `Thanks — we've received your complaint. Your support case is ${d.feedback?.caseReference}. Please keep the reference for follow-up.` });
      setMessage(""); setTransactionDetails("");
    } catch (err) { setStatus({ type: "error", text: err.message }); } finally { setLoading(false); }
  }

  return <div className="page-wrap" style={{ maxWidth: 560 }}>
    <div style={{ marginBottom: 20 }}><h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Feedback &amp; complaints</h1><p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>For transaction complaints, provide the transaction details below so support can investigate accurately.</p></div>
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Field label="Your name"><input className="input" value={name} onChange={e=>setName(e.target.value)} placeholder="Your name" /></Field>
      <Field label="Email (or provide phone)"><input className="input" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" type="email" /></Field>
      <Field label="Phone (or provide email)"><input className="input" value={phone} onChange={e=>setPhone(e.target.value)} placeholder="024 000 0000" /></Field>
      <Field label="Service / product"><select className="input" value={serviceType} onChange={e=>setServiceType(e.target.value)}>{SERVICES.map(s=><option key={s} value={s}>{s}</option>)}</select></Field>
      <Field label="Transaction ID"><input className="input" value={transactionId} onChange={e=>setTransactionId(e.target.value)} placeholder="Transaction / provider ID" /></Field>
      <Field label="Amount"><input className="input" value={transactionAmount} onChange={e=>setTransactionAmount(e.target.value)} placeholder="GHS 0.00" type="number" min="0" step="0.01" /></Field>
      {isDataOrAirtime && <Field label={serviceType === "data" ? "Data requested" : "Data / airtime requested"}><input className="input" value={requestedData} onChange={e=>setRequestedData(e.target.value)} placeholder={serviceType === "data" ? "e.g. 5GB MTN" : "e.g. GHS 20 MTN airtime"} /></Field>}
      {isDataOrAirtime && <Field label="Recipient / beneficiary"><input className="input" value={beneficiary} onChange={e=>setBeneficiary(e.target.value)} placeholder="Recipient phone number" /></Field>}
      {!isDataOrAirtime && <Field label="Recipient / beneficiary (if applicable)"><input className="input" value={beneficiary} onChange={e=>setBeneficiary(e.target.value)} placeholder="Meter, smartcard, account, phone or beneficiary" /></Field>}
      <Field label="Transaction date & time"><input className="input" value={transactionAt} onChange={e=>setTransactionAt(e.target.value)} type="datetime-local" /></Field>
      <Field label="Order reference (if available)"><input className="input" value={orderReference} onChange={e=>setOrderReference(e.target.value)} placeholder="TL..." /></Field>
      <Field label="Complaint category"><select className="input" value={category} onChange={e=>setCategory(e.target.value)}>{CATEGORIES.map(c=><option key={c}>{c}</option>)}</select></Field>
      <Field label="Transaction details"><textarea className="input" value={transactionDetails} onChange={e=>setTransactionDetails(e.target.value)} placeholder="What happened? Include any relevant transaction detail." rows={3} /></Field>
      <Field label="Your complaint"><textarea className="input" value={message} onChange={e=>setMessage(e.target.value)} placeholder="Tell us what you expected and what happened." rows={4} style={{ resize: "vertical", fontFamily: "inherit" }} /></Field>
      <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>Submit complaint</PrimaryButton>
      {status && <p style={{ fontSize: 13, color: status.type === "success" ? "var(--green)" : "var(--red)" }}>{status.text}</p>}
      <div className="card" style={{ padding: 14, marginTop: 8 }}><div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Required evidence for data &amp; airtime complaints</div><div style={{ fontSize: 12, color: "var(--muted)" }}>Transaction ID, amount, data/airtime requested, recipient or beneficiary, transaction date and time, transaction details, and your complaint. For other products, complete the form with the transaction details relevant to that service.</div></div>
      <div className="card" style={{ padding: 14, marginTop: 8 }}><div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Check an existing support case</div><div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>Use the case reference and the same email or phone used for the complaint.</div><input className="input" value={caseReference} onChange={e=>setCaseReference(e.target.value)} placeholder="SUP-20260915-XXXXX" style={{ marginBottom: 8 }} /><div style={{ display: "flex", gap: 8 }}><input className="input" value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" type="email" /><input className="input" value={phone} onChange={e=>setPhone(e.target.value)} placeholder="or phone" /></div><button className="nav-item" style={{ width: "auto", padding: "7px 10px", marginTop: 8 }} onClick={async ()=>{const r=await fetch(`/api/feedback/track?caseReference=${encodeURIComponent(caseReference)}&email=${encodeURIComponent(email)}&phone=${encodeURIComponent(phone)}`); const d=await r.json(); setCaseLookup(r.ok?d.case:{error:d.error||"Not found"});}}>Check case</button>{caseLookup && <div style={{fontSize:13,marginTop:10}}>{caseLookup.error?<span style={{color:"var(--red)"}}>{caseLookup.error}</span>:<span>Case <strong>{caseLookup.caseReference}</strong> is <strong>{String(caseLookup.status).replace("_"," ")}</strong>{caseLookup.orderReference?` · Order ${caseLookup.orderReference}`:""}.</span>}</div>}</div>
    </div>
  </div>;
}
