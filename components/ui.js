import { useState } from "react";
import { Loader2, Check, X, Bolt, Droplet, GraduationCap } from "lucide-react";

export const NETWORKS = {
  mtn: { label: "MTN", color: "var(--gold)", initial: "M", logo: "/icons/networks/mtn.png" },
  telecel: { label: "Telecel", color: "var(--red)", initial: "T", logo: "/icons/networks/telecel.png" },
  airteltigo: { label: "AirtelTigo", color: "var(--blue)", initial: "AT", logo: "/icons/networks/airteltigo.png" },
};

export const BILL_PROVIDERS = {
  // ECG's real mark is navy-blue-primary (with a yellow disc and red bolts),
  // not gold — corrected from the previous gold badge.
  ecg: { label: "ECG (Electricity)", color: "#0b1f66", Icon: Bolt, logo: "/icons/providers/ecg.png" },
  water: { label: "Ghana Water", color: "var(--blue)", Icon: Droplet, logo: "/icons/providers/ghana-water.png" },
};

// Same badge treatment as NETWORKS/BILL_PROVIDERS — a color mark, not the
// exam board's actual logo artwork.
export const EXAM_TYPES = {
  bece: { label: "BECE", color: "var(--gold)", initial: "B" },
  wassce: { label: "WASSCE", color: "var(--blue)", initial: "W" },
};

// NOTE: data bundle prices are NOT hardcoded here anymore — they load live
// from Techlink's own catalogue (see pages/data.js + pages/api/techlink/data-bundles.js).
// A static list was removed because bundle prices genuinely change and the
// API itself says "nothing drifts out of sync" when read live.

export function NetworkDot({ id, palette = NETWORKS }) {
  return <span className="dot" style={{ background: palette[id]?.color || "var(--muted-dim)" }} />;
}

// A small brand-colored badge — a network's real color, ECG/Water's real
// color, or an exam board's real color — used wherever a service needs a
// stronger visual mark than plain text. Deliberately not the operator/board's
// actual logo artwork (which is trademarked); this is a same-color icon or
// initial stand-in, the same treatment resale dashboards like Techlink's own
// panel use.
export function NetworkBadge({ id, palette = NETWORKS, size = 22 }) {
  const n = palette[id];
  const [logoFailed, setLogoFailed] = useState(false);
  if (!n) return <NetworkDot id={id} palette={palette} />;

  // Prefer the real provider logo when one has been supplied (drop a file at
  // the path in `logo` — e.g. public/icons/networks/mtn.png) and it loads
  // successfully. Falls back to the color-badge/initial treatment otherwise,
  // so the app never shows a broken image.
  if (n.logo && !logoFailed) {
    return (
      <span
        aria-hidden="true"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: size,
          height: size,
          borderRadius: "50%",
          overflow: "hidden",
          background: "#fff",
          flexShrink: 0,
        }}
      >
        <img
          src={n.logo}
          alt=""
          width={size}
          height={size}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
          onError={() => setLogoFailed(true)}
        />
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: "50%",
        background: n.color,
        color: "#14151a",
        fontSize: size * 0.42,
        fontWeight: 700,
        lineHeight: 1,
        flexShrink: 0,
      }}
    >
      {n.Icon ? <n.Icon size={size * 0.58} color="#14151a" /> : (n.initial || n.label?.[0])}
    </span>
  );
}

export function NetworkPicker({ value, onChange, palette = NETWORKS }) {
  return (
    <div className="network-picker">
      {Object.entries(palette).map(([id, n]) => (
        <button
          key={id}
          className={`network-btn ${value === id ? "active" : ""}`}
          onClick={() => onChange(id)}
          style={value === id ? { borderColor: n.color } : undefined}
        >
          <NetworkBadge id={id} palette={palette} size={18} />
          {n.label}
        </button>
      ))}
    </div>
  );
}

// Confirmed from Techlink's own AT iShare selling-rules panel: only these
// prefixes are AirtelTigo numbers. A wrong number is NOT refundable per
// their rules, so catching an obviously-wrong prefix before checkout
// protects you from an unrecoverable loss.
export const AIRTELTIGO_PREFIXES = ["026", "056", "027", "057", "023", "053"];

export function isLikelyAirtelTigoNumber(phone) {
  const digits = (phone || "").replace(/\D/g, "");
  const local = digits.startsWith("233") ? "0" + digits.slice(3) : digits; // handle +233 entry
  return AIRTELTIGO_PREFIXES.some((p) => local.startsWith(p));
}

// Shown near the phone/account field on every purchase page — Techlink's
// documented rule is that a wrong number is not refunded, so this needs to
// be visible before checkout, not buried in a terms page.
export function NoRefundNotice({ children }) {
  return (
    <p style={{ fontSize: 12, color: "var(--muted-dim)", margin: 0, lineHeight: 1.5 }}>
      {children || "Double-check the number before paying — a wrong number can't be refunded."}
    </p>
  );
}

export function Field({ label, children }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

export function EmailField({ email, setEmail }) {
  return (
    <Field label="Your email (for the payment receipt)">
      <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" type="email" />
    </Field>
  );
}

export function PrimaryButton({ children, onClick, disabled, loading }) {
  return (
    <button className="primary-btn" onClick={onClick} disabled={disabled || loading}>
      {loading && <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />}
      {children}
    </button>
  );
}

export function Toast({ toast }) {
  if (!toast) return null;
  const ok = toast.type === "success";
  return (
    <div className="toast" style={{ border: `1px solid ${ok ? "var(--green)" : "var(--red)"}` }}>
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: "50%",
          background: ok ? "var(--green)" : "var(--red)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {ok ? <Check size={13} color="#0d1117" /> : <X size={13} color="#0d1117" />}
      </div>
      <span style={{ fontSize: 14 }}>{toast.message}</span>
    </div>
  );
}

export function OrderList({ items }) {
  if (!items || items.length === 0) {
    return (
      <div className="card" style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 14 }}>
        No orders yet.
      </div>
    );
  }
  const labelFor = {
    airtime: "Airtime top-up",
    data: "Data bundle",
    afa: "AFA registration",
    ecg: "Electricity bill (ECG)",
    water: "Water bill",
    tv: "TV subscription",
    checker: "Result checker",
  };
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      {items.map((o) => (
        <div className="tx-row" key={o.reference}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{labelFor[o.orderType] || o.orderType}</div>
              <div style={{ fontSize: 12, color: "var(--muted-dim)", marginTop: 2 }}>
                {o.phone} · Ref {o.reference} · {new Date(o.createdAt).toLocaleString()}
              </div>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>GHS {Number(o.amount).toFixed(2)}</div>
            <div
              style={{
                fontSize: 12,
                color: o.status === "success" ? "var(--green)" : o.status === "failed" ? "var(--red)" : "var(--muted)",
              }}
            >
              {o.status === "success" ? "Delivered" : o.status === "failed" ? "Failed" : "Pending"}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
