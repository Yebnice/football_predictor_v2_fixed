import Link from "next/link";
import { Zap, ShieldCheck, Headset, Tag, Clock, Smartphone, Wifi, Bolt, Droplet, UserPlus, Tv, GraduationCap } from "lucide-react";
import { NETWORKS, NetworkBadge } from "../components/ui";

const SERVICES = [
  { href: "/mtn-data", icon: Wifi, title: "MTN Data", desc: "Master (cheaper, slower) or Express (faster) — single, bulk, or Excel upload." },
  { href: "/at-data", icon: Wifi, title: "AT Data", desc: "iShare or BigTime bundles for AirtelTigo lines." },
  { href: "/telecel-data", icon: Wifi, title: "Telecel Data", desc: "Telecel Group Share bundles, any size." },
  { href: "/data", icon: Zap, title: "Quick data top-up", desc: "Fastest option — live pricing, any of the three networks, no tiers to pick." },
  { href: "/airtime", icon: Smartphone, title: "Airtime", desc: "MTN, Telecel and AirtelTigo top-ups delivered in seconds." },
  { href: "/bills", icon: Bolt, title: "ECG electricity", desc: "Pay your prepaid electricity bill after a quick meter check." },
  { href: "/bills", icon: Droplet, title: "Water bill", desc: "Settle your Ghana Water bill in one place." },
  { href: "/afa", icon: UserPlus, title: "AFA registration", desc: "Register a farmer under the AFA programme." },
  { href: "/tv", icon: Tv, title: "TV subscription", desc: "DSTV, GOtv and StarTimes, validated before you pay." },
  { href: "/checker", icon: GraduationCap, title: "Result checker", desc: "BECE and WASSCE vouchers, or let us check it for you." },
];

const USPS = [
  { icon: Zap, label: "Fast Processing" },
  { icon: ShieldCheck, label: "Safe & Secure" },
  { icon: Tag, label: "Great Prices" },
  { icon: Headset, label: "Reliable Support" },
  { icon: Clock, label: "24/7 Service" },
];

export default function Home() {
  return (
    <div>
      <div className="hero" style={{ paddingTop: 40 }}>
        <div className="hero-eyebrow">
          <Zap size={13} color="var(--gold-light)" /> Data at an <span className="accent">Affordable Price</span>
        </div>
        <h1>
          Fast, trackable <span className="accent-text">airtime &amp; data</span> delivery across every network.
        </h1>
        <p>
          PjDigitalServices delivers MTN, Telecel and AirtelTigo airtime and data, plus ECG and water
          bill payments, TV subscriptions and BECE/WASSCE result checkers — all paid securely through
          MoMo, Telecel Cash, AT Money or card, with every order tracked from purchase to delivery.
        </p>

        <div className="network-strip">
          {Object.entries(NETWORKS).map(([id, n]) => (
            <div key={id} className="network-chip">
              <NetworkBadge id={id} size={18} />
              {n.label}
            </div>
          ))}
        </div>

        <div className="trust-strip">
          <span><ShieldCheck size={14} color="var(--blue-light)" /> Secure checkout</span>
          <span><Headset size={14} color="var(--blue-light)" /> Real support, real people</span>
        </div>

        <div className="usp-row">
          {USPS.map((u) => (
            <div className="usp-item" key={u.label}>
              <div className="usp-icon"><u.icon size={15} color="var(--blue-light)" /></div>
              <span>{u.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="page-wrap" style={{ paddingTop: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14 }}>
          {SERVICES.map((s) => (
            <Link
              key={s.title}
              href={s.href}
              className="card"
              style={{ display: "flex", flexDirection: "column", gap: 10, padding: 18, textDecoration: "none", color: "inherit" }}
            >
              <div className="service-icon">
                <s.icon size={17} color="var(--blue-light)" />
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 600 }}>{s.title}</div>
              <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>{s.desc}</div>
            </Link>
          ))}
        </div>

        <div className="card" style={{ marginTop: 28, padding: 22 }}>
          <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 6 }}>Why customers stick with us</div>
          <p style={{ fontSize: 13.5, color: "var(--muted)", lineHeight: 1.7, margin: 0 }}>
            Every order is confirmed against your actual payment before anything is sent — so delivery is
            fast without cutting corners on security. Already bought from us? Check your order any
            time from <Link href="/dashboard" style={{ color: "var(--price)" }}>My Orders</Link> using
            your order reference and the email you checked out with.
          </p>
        </div>
      </div>
    </div>
  );
}
