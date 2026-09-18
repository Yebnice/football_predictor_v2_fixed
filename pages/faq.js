import { useState } from "react";

// Content adapted from Techlink's own real FAQ pages (screenshots reviewed
// and fact-checked), reworded for PjDigitalServices: their FAQ talks about
// a "wallet" since agents fund Techlink directly — we removed the wallet
// concept and pay per order via Paystack, so those answers are rewritten
// accordingly rather than copied verbatim. This is a first draft — please
// review and edit the wording to match how you actually want to sound.
const FAQS = [
  {
    category: "Getting started",
    items: [
      { q: "Do I need an account to buy?", a: "No — pick a service, pay with Paystack, and you're done. Registering just saves your details for faster checkout and lets your order dashboard load automatically." },
      { q: "What networks and services do you support?", a: "MTN, Telecel and AirtelTigo for airtime and data; ECG electricity and Ghana Water bills; DSTV, GOtv and StarTimes; BECE/WASSCE result checkers; and AFA farmer registration." },
      { q: "Is my payment secure?", a: "Yes — every payment is processed by Paystack. We never see or store your card details." },
    ],
  },
  {
    category: "Data bundles",
    items: [
      { q: "How do I buy a data bundle?", a: "Choose your network, pick a bundle, enter the recipient's number, and pay. Delivery starts as soon as payment is confirmed." },
      { q: "Can I buy data for someone else's number?", a: "Yes — any valid Ghana number on the network you're buying for." },
      { q: "How quickly is data delivered?", a: "Bundles from the standard live catalogue (the \"Quick data top-up\" page) are usually delivered in 10–30 seconds, up to 2 minutes at busy times. If nothing arrives after 5 minutes, check your dashboard." },
      { q: "Why does MTN Master take so long?", a: "MTN Master is the cheapest MTN data tier, but it is genuinely not instant — typically 30 minutes to a few hours, and it can run longer when the queue is busy. MTN Express costs more but is usually delivered much sooner. Both options are shown clearly on the MTN Data page so you can choose." },
      { q: "What happens if a data purchase fails?", a: "If a delivery fails, the order is investigated. Where it is safe to retry, an authorised retry may be performed. If the provider outcome is uncertain, the order is placed under manual review to help prevent duplicate delivery. Contact us through the Feedback page with your order reference if you need assistance." },
      { q: "Is there a minimum or maximum bundle size?", a: "Sizes are set by the networks — whatever's listed on the relevant page is what's available. There's no extra limit on our side." },
    ],
  },
  {
    category: "AFA registration",
    items: [
      { q: "What is AFA registration?", a: "AFA (Agriculture for Food and Jobs) is a government programme supporting Ghanaian farmers. Registering through us enrols eligible people into the programme." },
      { q: "Who's eligible?", a: "Ghanaian farmers and people engaged in agricultural activities — your occupation must reflect farming-related work." },
      { q: "What do I need to register?", a: "Full name, phone number, Ghana Card number (format GHA-XXXXXXXXX-X), date of birth, region, specific location, and occupation." },
      { q: "How much does it cost?", a: "The fee is set by the platform and shown on the AFA Registration page before you pay." },
      { q: "How long does it take?", a: "Your registration is submitted instantly once payment is confirmed. Processing by the programme administrators can vary — you'll see the status update on your dashboard." },
    ],
  },
  {
    category: "Payments & orders",
    items: [
      { q: "What payment methods can I use?", a: "Card, mobile money, or bank transfer — all through Paystack's secure checkout." },
      { q: "Can I get a refund for a wrong number?", a: "No — please double-check the number before paying. Wrong numbers, duplicate orders, and lines with an outstanding balance can't be refunded, in line with the networks' own rules." },
      { q: "How do I check my order status?", a: "Use the My Orders or Track Order page with the order reference and the checkout email — no account is required." },
      { q: "Something went wrong with my order — what do I do?", a: "Go to the Feedback page and include your order reference. We'll look into it." },
    ],
  },
];

function FaqSection({ category, items }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: 0.4 }}>
        {category}
      </h2>
      <div className="card" style={{ overflow: "hidden" }}>
        {items.map((item, i) => (
          <details key={item.q} style={{ borderTop: i === 0 ? "none" : "1px solid var(--line)" }}>
            <summary style={{ padding: "14px 16px", cursor: "pointer", fontSize: 14, fontWeight: 500, listStyle: "none" }}>
              {item.q}
            </summary>
            <p style={{ padding: "0 16px 16px", margin: 0, fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>{item.a}</p>
          </details>
        ))}
      </div>
    </div>
  );
}

export default function FaqPage() {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const filtered = FAQS.map((section) => ({
    ...section,
    items: q ? section.items.filter((i) => i.q.toLowerCase().includes(q) || i.a.toLowerCase().includes(q)) : section.items,
  })).filter((section) => section.items.length > 0);

  return (
    <div className="page-wrap" style={{ maxWidth: 680 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Frequently asked questions</h1>
        <p style={{ color: "var(--muted)", fontSize: 14, marginTop: 4 }}>
          Can't find what you're looking for? Use the <a href="/feedback" style={{ color: "var(--price)" }}>Feedback</a> page.
        </p>
      </div>
      <input
        className="input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search questions..."
        style={{ marginBottom: 24 }}
      />
      {filtered.length === 0 && <p style={{ color: "var(--muted)", fontSize: 14 }}>No matches — try a different word.</p>}
      {filtered.map((section) => (
        <FaqSection key={section.category} category={section.category} items={section.items} />
      ))}
    </div>
  );
}
