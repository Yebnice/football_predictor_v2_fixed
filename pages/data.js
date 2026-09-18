import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { NetworkPicker, Field, EmailField, PrimaryButton, Toast, NETWORKS, NoRefundNotice, isLikelyAirtelTigoNumber } from "../components/ui";
import { payAndFulfil } from "../lib/payment";

// Techlink's bundle catalogue is live and network/phone-specific (see
// lib/techlink.js listDataBundles) — there is deliberately no hardcoded
// price list here. What loads below is whatever Techlink returns right
// now, grouped by category if the response provides one.
function groupBundles(list) {
  const groups = {};
  for (const b of list) {
    const key = b.category || b.validity || b.duration || "Bundles";
    groups[key] = groups[key] || [];
    groups[key].push(b);
  }
  return groups;
}

export default function DataPage() {
  const router = useRouter();
  const [network, setNetwork] = useState("mtn");
  const [phone, setPhone] = useState("");
  const [bundles, setBundles] = useState(null); // null = not loaded, [] = loaded empty
  const [loadingBundles, setLoadingBundles] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [bundleId, setBundleId] = useState(null);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    setEmail(window.localStorage.getItem("pj_email") || "");
    setPhone(window.localStorage.getItem("pj_phone") || "");
  }, []);

  function loadBundles() {
    setLoadingBundles(true);
    setLoadError("");
    setBundles(null);
    setBundleId(null);
    fetch(`/api/techlink/data-bundles?network=${network}&phone=${encodeURIComponent(phone)}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          setLoadError(d.error);
          setBundles([]);
        } else {
          setBundles(d.bundles || d.data || []);
        }
      })
      .catch(() => {
        setLoadError("Could not reach the server.");
        setBundles([]);
      })
      .finally(() => setLoadingBundles(false));
  }

  const selected = (bundles || []).find((b) => (b.id || b.bundleId) === bundleId);
  const valid = phone.length >= 10 && selected && email.includes("@");
  const grouped = bundles ? groupBundles(bundles) : {};

  function submit() {
    setLoading(true);
    payAndFulfil({
      orderType: "data",
      network,
      phone,
      email,
      bundleId: selected.id || selected.bundleId,
      onDone: () => {
        setLoading(false);
        window.localStorage.setItem("pj_email", email);
        window.localStorage.setItem("pj_phone", phone);
        setToast({ type: "success", message: `Bundle sent to ${phone}` });
        setTimeout(() => router.push("/dashboard"), 1200);
      },
      onError: (msg) => {
        setLoading(false);
        setToast({ type: "error", message: msg });
      },
    });
  }

  return (
    <div className="page-wrap" style={{ maxWidth: 680 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Buy data bundle</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>
          Prices load live from the network's own catalogue — always current.
        </p>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Field label="Network">
          <NetworkPicker value={network} onChange={(n) => { setNetwork(n); setBundles(null); setBundleId(null); }} />
        </Field>
        <Field label="Recipient phone number">
          <div style={{ display: "flex", gap: 8, maxWidth: 320 }}>
            <input className="input" style={{ flex: 1 }} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 000 0000" />
            <button className="primary-btn" style={{ width: "auto", padding: "0 16px" }} onClick={loadBundles} disabled={phone.length < 10 || loadingBundles}>
              {loadingBundles ? "..." : "Load bundles"}
            </button>
          </div>
        </Field>
        {network === "airteltigo" && phone.length >= 3 && !isLikelyAirtelTigoNumber(phone) && (
          <p style={{ fontSize: 12, color: "var(--red)", margin: 0 }}>
            That doesn't look like an AirtelTigo number (026, 056, 027, 057, 023, 053) — AirtelTigo bundles can only be delivered to AirtelTigo lines, and wrong numbers aren't refunded.
          </p>
        )}
        <NoRefundNotice />

        {loadError && (
          <p style={{ color: "var(--red)", fontSize: 13, margin: 0 }}>
            {loadError}
          </p>
        )}

        {bundles && bundles.length === 0 && !loadError && (
          <p style={{ color: "var(--muted)", fontSize: 13, margin: 0 }}>No bundles available for this number right now.</p>
        )}

        {bundles && bundles.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {Object.entries(grouped).map(([group, items]) => (
              <div key={group}>
                <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8, textTransform: "uppercase", letterSpacing: 0.4 }}>{group}</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
                  {items.map((b) => {
                    const id = b.id || b.bundleId;
                    const isSelected = bundleId === id;
                    return (
                      <button
                        key={id}
                        onClick={() => setBundleId(id)}
                        className={`bundle-card ${isSelected ? "active" : ""}`}
                        style={isSelected ? { borderColor: NETWORKS[network].color } : undefined}
                      >
                        <span className="heading-font" style={{ fontSize: 18, fontWeight: 600 }}>{b.size || b.name || b.data}</span>
                        {(b.validity || b.duration) && <span style={{ fontSize: 12, color: "var(--muted-dim)" }}>{b.validity || b.duration}</span>}
                        <span style={{ fontSize: 16, fontWeight: 700, color: "var(--price)", marginTop: 4 }}>GHS {Number(b.price ?? b.amount).toFixed(2)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ maxWidth: 300 }}><EmailField email={email} setEmail={setEmail} /></div>
        <div style={{ maxWidth: 300 }}>
          <PrimaryButton disabled={!valid} loading={loading} onClick={submit}>
            {selected ? `Pay GHS ${Number(selected.price ?? selected.amount).toFixed(2)} with Paystack` : "Select a bundle"}
          </PrimaryButton>
        </div>
      </div>
      <Toast toast={toast} />
    </div>
  );
}
