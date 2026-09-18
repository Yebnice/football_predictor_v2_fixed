import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import * as XLSX from "xlsx";
import { Field, EmailField, PrimaryButton, Toast, NoRefundNotice, isLikelyAirtelTigoNumber, NetworkBadge } from "./ui";
import { payAndFulfil } from "../lib/payment";
import { TIERS, NETWORK_PAGES } from "../lib/agentProducts";

/* ---------- shared helpers ---------- */

function parseBulkText(text) {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/[\s,]+/).filter(Boolean);
      return { phone: parts[0], value: Number(parts[1]) };
    })
    .filter((r) => r.phone && r.value > 0);
}

async function parseExcelFile(file) {
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const sheet = wb.Sheets[wb.SheetNames[0]];
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1 });
  const out = [];
  for (const row of rows) {
    if (!row || row.length < 2) continue;
    const phone = String(row[0]).trim();
    const value = Number(row[1]);
    if (/^\d{9,}$/.test(phone.replace(/\D/g, "")) && value > 0) out.push({ phone, value });
  }
  return out;
}

function downloadSampleCsv(kind) {
  const label = kind === "data" ? "size_gb" : "amount_ghs";
  const sample = kind === "data" ? [5, 10] : [10, 20];
  const csv = `phone,${label}\n0240000001,${sample[0]}\n0240000002,${sample[1]}\n`;
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "sample-template.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function estimateBulkTotal(kind, rows, tier) {
  if (kind === "airtime") return rows.reduce((s, r) => s + r.value, 0);
  return rows.reduce((s, r) => {
    const b = tier?.bundles.find((x) => x.size === r.value);
    return s + (b ? b.price : 0);
  }, 0);
}

function mergeBundles(tier, liveSizes) {
  return tier.bundles.map((b) => {
    if (!liveSizes) return { ...b, available: true };
    const live = liveSizes.find((s) => s.size === b.size);
    return live ? { ...b, price: live.price, available: true } : { ...b, available: false };
  });
}

function BundleGrid({ tier, sizeSelected, onSelect, liveSizes }) {
  // liveSizes is null until the live check resolves (or if it fails) — in
  // that window everything shows as available, same as before this check
  // existed, so a slow/failed lookup never blocks anyone from buying.
  const merged = mergeBundles(tier, liveSizes);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 12 }}>
      {merged.map((b) => (
        <button
          key={b.size}
          className={`bundle-card ${sizeSelected === b.size ? "active" : ""}`}
          onClick={() => b.available && onSelect(b.size)}
          disabled={!b.available}
          title={b.available ? undefined : "Currently unavailable — try another size"}
          style={{
            ...(sizeSelected === b.size ? { borderColor: "var(--gold)" } : {}),
            ...(b.available ? {} : { opacity: 0.4, cursor: "not-allowed" }),
          }}
        >
          <span className="heading-font" style={{ fontSize: 18, fontWeight: 600 }}>{b.size}GB</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: "var(--price)", marginTop: 4 }}>
            {b.available ? `GHS ${b.price.toFixed(2)}` : "Unavailable"}
          </span>
        </button>
      ))}
    </div>
  );
}

function ModeTabs({ mode, setMode }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 20 }}>
      {["single", "bulk", "excel"].map((m) => (
        <button
          key={m}
          onClick={() => setMode(m)}
          className="nav-item"
          style={{
            width: "auto",
            padding: "6px 14px",
            textTransform: "capitalize",
            background: mode === m ? "var(--surface-raised)" : "transparent",
            borderColor: mode === m ? "var(--gold)" : "var(--line)",
          }}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

/* ---------- single ---------- */

function TierSingleForm({ tierKey, tier, networkId, email, setEmail, loading, setLoading, onDone, onError, liveSizes }) {
  const [phone, setPhone] = useState("");
  const [size, setSize] = useState(null);
  const merged = mergeBundles(tier, liveSizes);
  const selected = merged.find((b) => b.size === size && b.available);
  const prefixOk = networkId !== "airteltigo" || isLikelyAirtelTigoNumber(phone);
  const valid = phone.length >= 10 && selected && email.includes("@") && prefixOk;

  // If the live check comes back after a size was already picked (a real
  // race: clicking a tile in the moment before the availability check
  // resolves) and it turns out that size isn't actually available, drop the
  // selection instead of letting a stale price sit behind an enabled Pay
  // button — this is exactly the scenario that let the "no longer
  // available" error reach checkout in the first place.
  useEffect(() => {
    if (size != null && liveSizes && !liveSizes.some((s) => s.size === size)) setSize(null);
  }, [liveSizes, size]);

  function submit() {
    if (!selected) return;
    setLoading(true);
    payAndFulfil({
      orderType: "tierData",
      network: networkId,
      phone,
      email,
      tierKey,
      size,
      onDone: () => onDone(`${size}GB sent to ${phone}`),
      onError,
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Field label="Recipient phone number">
        <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" style={{ maxWidth: 260 }} />
      </Field>
      {networkId === "airteltigo" && phone.length >= 3 && !prefixOk && (
        <p style={{ fontSize: 12, color: "var(--red)", margin: 0 }}>
          That doesn't look like an AirtelTigo number (026, 056, 027, 057, 023, 053).
        </p>
      )}
      <BundleGrid tier={tier} sizeSelected={size} onSelect={setSize} liveSizes={liveSizes} />
      <div style={{ maxWidth: 300 }}><EmailField email={email} setEmail={setEmail} /></div>
      <NoRefundNotice />
      <div style={{ maxWidth: 300 }}>
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          {selected ? `Pay GHS ${selected.price.toFixed(2)} with Paystack` : "Select a bundle"}
        </PrimaryButton>
      </div>
    </div>
  );
}

function EvdSingleForm({ networkId, email, setEmail, loading, setLoading, onDone, onError }) {
  const [phone, setPhone] = useState("");
  const [amount, setAmount] = useState("");
  const prefixOk = networkId !== "airteltigo" || isLikelyAirtelTigoNumber(phone);
  const valid = phone.length >= 10 && Number(amount) > 0 && email.includes("@") && prefixOk;

  function submit() {
    setLoading(true);
    payAndFulfil({
      orderType: "airtime",
      network: networkId,
      phone,
      email,
      airtimeAmount: Number(amount),
      onDone: () => onDone(`GHS ${amount} airtime sent to ${phone}`),
      onError,
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 320 }}>
      <Field label="Phone number">
        <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
      </Field>
      {networkId === "airteltigo" && phone.length >= 3 && !prefixOk && (
        <p style={{ fontSize: 12, color: "var(--red)", margin: 0 }}>Doesn't look like an AirtelTigo number.</p>
      )}
      <Field label="Amount (GHS)">
        <input className="input" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="10.00" type="number" />
      </Field>
      <EmailField email={email} setEmail={setEmail} />
      <NoRefundNotice />
      <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
        Pay GHS {amount || "0.00"} with Paystack
      </PrimaryButton>
    </div>
  );
}

/* ---------- bulk ---------- */

function BulkForm({ kind, tierKey, tier, networkId, email, setEmail, loading, setLoading, onDone, onError }) {
  const [text, setText] = useState("");
  const rows = parseBulkText(text);
  const valid = rows.length > 0 && email.includes("@");
  const total = estimateBulkTotal(kind, rows, tier);

  function submit() {
    setLoading(true);
    if (kind === "data") {
      payAndFulfil({
        orderType: "tierBulkData",
        network: networkId,
        email,
        tierKey,
        rows: rows.map((r) => ({ phone: r.phone, size: r.value })),
        onDone: () => onDone(`${rows.length} orders placed`),
        onError,
      });
    } else {
      payAndFulfil({
        orderType: "tierBulkAirtime",
        network: networkId,
        email,
        rows: rows.map((r) => ({ phone: r.phone, amount: r.value })),
        onDone: () => onDone(`${rows.length} airtime orders placed`),
        onError,
      });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Field label={`Orders — one per line: phone ${kind === "data" ? "size_in_GB" : "amount_in_GHS"}`}>
        <textarea
          className="input"
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={kind === "data" ? "024XXXXXXX 5\n024YYYYYYY 10" : "024XXXXXXX 10\n024YYYYYYY 20"}
          style={{ fontFamily: "monospace", resize: "vertical" }}
        />
      </Field>
      <p style={{ fontSize: 12, color: "var(--muted-dim)", margin: 0 }}>
        {rows.length} valid line{rows.length === 1 ? "" : "s"} detected. Estimated total: GHS {total.toFixed(2)} — confirmed exactly at payment.
      </p>
      <div style={{ maxWidth: 300 }}><EmailField email={email} setEmail={setEmail} /></div>
      <NoRefundNotice>Double-check every number on the list — wrong numbers in a bulk order aren't refunded either.</NoRefundNotice>
      <div style={{ maxWidth: 300 }}>
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          Pay for {rows.length} order{rows.length === 1 ? "" : "s"} with Paystack
        </PrimaryButton>
      </div>
    </div>
  );
}

/* ---------- excel ---------- */

function ExcelForm({ kind, tierKey, tier, networkId, email, setEmail, loading, setLoading, onDone, onError }) {
  const [rows, setRows] = useState([]);
  const [fileName, setFileName] = useState("");
  const [parsing, setParsing] = useState(false);
  const valid = rows.length > 0 && email.includes("@");
  const total = estimateBulkTotal(kind, rows, tier);

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setParsing(true);
    try {
      setRows(await parseExcelFile(file));
    } catch {
      setRows([]);
    } finally {
      setParsing(false);
    }
  }

  function submit() {
    setLoading(true);
    if (kind === "data") {
      payAndFulfil({
        orderType: "tierBulkData",
        network: networkId,
        email,
        tierKey,
        rows: rows.map((r) => ({ phone: r.phone, size: r.value })),
        onDone: () => onDone(`${rows.length} orders placed`),
        onError,
      });
    } else {
      payAndFulfil({
        orderType: "tierBulkAirtime",
        network: networkId,
        email,
        rows: rows.map((r) => ({ phone: r.phone, amount: r.value })),
        onDone: () => onDone(`${rows.length} airtime orders placed`),
        onError,
      });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Field label="Upload Excel / CSV file">
        <input type="file" accept=".csv,.xlsx,.xls" onChange={handleFile} />
      </Field>
      <button
        onClick={() => downloadSampleCsv(kind)}
        style={{ background: "none", border: "none", color: "var(--price)", fontSize: 13, textAlign: "left", padding: 0, cursor: "pointer" }}
      >
        Download sample template
      </button>
      {fileName && (
        <p style={{ fontSize: 12, color: "var(--muted-dim)", margin: 0 }}>
          {parsing
            ? "Reading file..."
            : `${fileName}: ${rows.length} valid line${rows.length === 1 ? "" : "s"} detected. Estimated total: GHS ${total.toFixed(2)}.`}
        </p>
      )}
      <div style={{ maxWidth: 300 }}><EmailField email={email} setEmail={setEmail} /></div>
      <NoRefundNotice>Double-check every number in the file — wrong numbers in a bulk order aren't refunded either.</NoRefundNotice>
      <div style={{ maxWidth: 300 }}>
        <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
          Pay for {rows.length} order{rows.length === 1 ? "" : "s"} with Paystack
        </PrimaryButton>
      </div>
    </div>
  );
}

/* ---------- shell ---------- */

export default function TierShop({ networkKey }) {
  const router = useRouter();
  const page = NETWORK_PAGES[networkKey];
  const [activeTierKey, setActiveTierKey] = useState(page.tierKeys[0]);
  const [mode, setMode] = useState("single");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [liveSizes, setLiveSizes] = useState(null);

  useEffect(() => {
    setEmail(window.localStorage.getItem("pj_email") || "");
  }, []);

  useEffect(() => {
    setMode("single");
  }, [activeTierKey]);

  const isEvd = activeTierKey === "evd";

  // Check what Techlink's live catalogue actually has for this tier so the
  // grid can gray out sizes that would otherwise fail at checkout (see the
  // note in lib/agentProducts.js — that reference list can drift out of
  // sync with the real, live catalogue).
  useEffect(() => {
    if (isEvd) return;
    let cancelled = false;
    setLiveSizes(null);
    fetch(`/api/techlink/tier-products?tierKey=${encodeURIComponent(activeTierKey)}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setLiveSizes(d.sizes || null); })
      .catch(() => { if (!cancelled) setLiveSizes(null); });
    return () => { cancelled = true; };
  }, [activeTierKey, isEvd]);

  const tier = !isEvd ? TIERS[activeTierKey] : null;

  function finish(message) {
    setLoading(false);
    if (email) window.localStorage.setItem("pj_email", email);
    setToast({ type: "success", message });
    setTimeout(() => router.push("/dashboard"), 1400);
  }
  function fail(msg) {
    setLoading(false);
    setToast({ type: "error", message: msg });
  }

  const sharedProps = { networkId: page.networkId, email, setEmail, loading, setLoading, onDone: finish, onError: fail, liveSizes };

  return (
    <div className="page-wrap" style={{ maxWidth: 720 }}>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>
        <NetworkBadge id={page.networkId} size={34} />
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{page.label} Data</h1>
          <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>Select a bundle and complete your purchase.</p>
        </div>
      </div>

      <div className="network-picker" style={{ marginBottom: 16, flexWrap: "wrap" }}>
        {page.tierKeys.map((k) => (
          <button key={k} className={`network-btn ${activeTierKey === k ? "active" : ""}`} onClick={() => setActiveTierKey(k)}>
            {TIERS[k].label}
          </button>
        ))}
        <button className={`network-btn ${isEvd ? "active" : ""}`} onClick={() => setActiveTierKey("evd")}>
          {page.label} EVD/Airtime
        </button>
      </div>

      {tier?.blurb && <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>{tier.blurb}</p>}
      {tier?.sellingNotes?.length > 0 && (
        <details className="card" style={{ marginBottom: 16, padding: "10px 14px" }}>
          <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 500, color: "var(--text)", listStyle: "none" }}>
            Delivery &amp; selling rules
          </summary>
          <ul style={{ fontSize: 12, color: "var(--muted-dim)", margin: "10px 0 2px", paddingLeft: 18, lineHeight: 1.6 }}>
            {tier.sellingNotes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </details>
      )}

      <ModeTabs mode={mode} setMode={setMode} />

      {mode === "single" &&
        (isEvd ? <EvdSingleForm {...sharedProps} /> : <TierSingleForm tierKey={activeTierKey} tier={tier} {...sharedProps} />)}

      {mode === "bulk" && (
        <BulkForm kind={isEvd ? "airtime" : "data"} tierKey={activeTierKey} tier={tier} {...sharedProps} />
      )}

      {mode === "excel" && (
        <ExcelForm kind={isEvd ? "airtime" : "data"} tierKey={activeTierKey} tier={tier} {...sharedProps} />
      )}

      <Toast toast={toast} />
    </div>
  );
}
