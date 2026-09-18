// Reference catalogue for INSTANT display only — this mirrors Techlink's
// own "Agent Data Products" (their words: "sold from our own catalogue").
// The actual price and exact product name used for any real order is
// always re-fetched live from GET /products at the moment of purchase
// (see listProducts() in lib/techlink.js and the order-creation logic in
// pages/api/orders/create.js) — this file only makes the tier pickers feel
// instant instead of every tab switch waiting on a network call. If
// Techlink changes these prices, update this file to match (or drop it and
// call listProducts() directly — the security/correctness doesn't depend
// on this file being current, only the UI snappiness does).

// Confirmed identically across the MTN Master and AT iShare "Delivery &
// rules" screenshots, so treated as platform-wide rather than tier-specific.
const UNIVERSAL_NOTES = [
  "Verify the number before buying — a wrong number can't be refunded.",
  "A line with an outstanding balance won't receive the bundle, and the order isn't refunded.",
  "No duplicate orders — duplicates are not refunded.",
];

export const TIERS = {
  mtnMaster: {
    network: "mtn",
    category: "Master", // GET /products?category=Master
    label: "MTN Master",
    blurb: "Cheapest option — but not instant. Typically 30 minutes to a few hours, sometimes longer when the queue is busy.",
    sellingNotes: [
      ...UNIVERSAL_NOTES,
      "Turbonet and Broadband SIMs are not eligible for this bundle.",
      "For urgent data, dial *138# directly instead.",
    ],
    bundles: [
      { size: 1, price: 4.4 }, { size: 2, price: 8.65 }, { size: 3, price: 13 },
      { size: 4, price: 17.2 }, { size: 5, price: 21.5 }, { size: 6, price: 25.9 },
      { size: 8, price: 35 }, { size: 10, price: 41.7 }, { size: 15, price: 62.5 },
      { size: 20, price: 82 }, { size: 25, price: 102.5 }, { size: 30, price: 122.5 },
      { size: 40, price: 161.5 }, { size: 50, price: 198.5 }, { size: 100, price: 370 },
    ],
  },
  mtnExpress: {
    network: "mtn",
    category: "MasterExpress",
    label: "MTN Express",
    blurb: "Costs more than Master, but is usually delivered much sooner.",
    sellingNotes: [...UNIVERSAL_NOTES],
    bundles: [
      { size: 1, price: 4.7 }, { size: 2, price: 9.2 }, { size: 3, price: 13.8 },
      { size: 4, price: 18.7 }, { size: 5, price: 23 }, { size: 6, price: 27 },
      { size: 8, price: 36 }, { size: 10, price: 45 }, { size: 15, price: 67 },
      { size: 20, price: 88 }, { size: 25, price: 110 }, { size: 30, price: 132 },
      { size: 40, price: 175 }, { size: 50, price: 220 },
    ],
  },
  atIShare: {
    network: "airteltigo",
    category: "iShare",
    label: "AT iShare",
    blurb: "Instant delivery for AirtelTigo lines.",
    sellingNotes: [
      "AirtelTigo numbers only — prefixes 026, 056, 027, 057, 023, 053.",
      ...UNIVERSAL_NOTES,
    ],
    bundles: [
      { size: 1, price: 4.2 }, { size: 2, price: 8.5 }, { size: 3, price: 12.5 },
      { size: 4, price: 16.7 }, { size: 5, price: 21.6 }, { size: 6, price: 25 },
      { size: 7, price: 28.5 }, { size: 8, price: 33 }, { size: 9, price: 37 },
      { size: 10, price: 41 }, { size: 15, price: 60 }, { size: 20, price: 81 },
    ],
  },
  atBigTime: {
    network: "airteltigo",
    category: "BigTime",
    label: "AT BigTime",
    blurb: "Larger AirtelTigo bundles. Same delivery-rules as AT iShare.",
    sellingNotes: [
      "AirtelTigo numbers only — prefixes 026, 056, 027, 057, 023, 053.",
      ...UNIVERSAL_NOTES,
    ],
    bundles: [
      { size: 15, price: 47 }, { size: 20, price: 57 }, { size: 25, price: 62 },
      { size: 30, price: 67 }, { size: 40, price: 82.4 }, { size: 50, price: 93 },
      { size: 60, price: 107.5 }, { size: 70, price: 123 }, { size: 80, price: 137.5 },
      { size: 100, price: 168 }, { size: 130, price: 224 }, { size: 170, price: 275 },
      { size: 200, price: 316 },
    ],
  },
  telecelGroupShare: {
    network: "telecel",
    category: "Group Share",
    label: "Telecel Group Share",
    blurb: "Instant delivery for Telecel lines. Same delivery-rules pattern as MTN Master and AT iShare.",
    sellingNotes: [...UNIVERSAL_NOTES],
    bundles: [
      { size: 5, price: 21.5 }, { size: 10, price: 41 }, { size: 15, price: 60 },
      { size: 20, price: 78 }, { size: 25, price: 97 }, { size: 30, price: 112.5 },
      { size: 35, price: 134 }, { size: 40, price: 150 }, { size: 45, price: 171 },
      { size: 50, price: 181.5 }, { size: 100, price: 360.5 },
    ],
  },
};

// Each network's page shows its bundle tier(s) plus a plain "EVD/Airtime"
// option, which reuses the simple airtime flow (no catalogue — the
// customer just types an amount) rather than duplicating it.
export const NETWORK_PAGES = {
  mtn: { label: "MTN", networkId: "mtn", tierKeys: ["mtnMaster", "mtnExpress"] },
  at: { label: "AT", networkId: "airteltigo", tierKeys: ["atIShare", "atBigTime"] },
  telecel: { label: "Telecel", networkId: "telecel", tierKeys: ["telecelGroupShare"] },
};
