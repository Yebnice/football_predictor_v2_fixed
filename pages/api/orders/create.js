import crypto from "crypto";
import { createOrder } from "../../../lib/store";
import {
  listDataBundles,
  getAfaPrice,
  validateWaterMeter,
  validateTvSmartcard,
  getCheckerPrices,
  getResultCheckServicePrices,
  listProducts,
} from "../../../lib/techlink";
import { TIERS } from "../../../lib/agentProducts";
import { rateLimit } from "../../../lib/rateLimit";

// Every price here is resolved from Techlink itself at order time — never
// from anything the browser sends — so a customer can never pay less (or
// more) than what Techlink will actually charge your wallet.
export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 12, windowMs: 60_000, keySuffix: "orders-create" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many order attempts. Please wait a moment and try again." });

  try {
    const {
      orderType, network, phone, email,
      bundleId,
      afaDetails,
      airtimeAmount,
      meterNumber, billAmount,
      tvDetails,
      checkerDetails,
      tierKey, size, rows,
    } = req.body;

    if (!orderType || !email) {
      return res.status(400).json({ error: "Missing required fields" });
    }
    const isBulk = orderType === "tierBulkData" || orderType === "tierBulkAirtime";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email))) return res.status(400).json({ error: "Enter a valid email address" });
    if (!isBulk && !phone) {
      return res.status(400).json({ error: "Phone number is required" });
    }
    if (!isBulk && !/^[+0-9][0-9\s-]{7,20}$/.test(String(phone))) return res.status(400).json({ error: "Enter a valid phone number" });
    let resolvedNetwork = network; // may be overridden below for tier orders — see note there

    const normalizedEmail = String(email).trim().toLowerCase();
    let amount;
    let extra = {};

    if (orderType === "airtime") {
      if (!network) return res.status(400).json({ error: "Network is required" });
      amount = Number(airtimeAmount);
      if (!amount || amount <= 0) return res.status(400).json({ error: "Invalid amount" });

    } else if (orderType === "data") {
      if (!network) return res.status(400).json({ error: "Network is required" });
      if (!bundleId) return res.status(400).json({ error: "Select a bundle" });
      // Re-fetch the live catalogue to find the authoritative price for
      // this bundleId — the price shown to the customer must have come
      // from here in the first place, so this should always find a match.
      const catalogue = await listDataBundles({ network, phone });
      const bundles = catalogue.bundles || catalogue.data || [];
      const bundle = bundles.find((b) => (b.id || b.bundleId) === bundleId);
      if (!bundle) return res.status(400).json({ error: "That bundle is no longer available — refresh and pick again" });
      amount = Number(bundle.price ?? bundle.amount);

    } else if (orderType === "afa") {
      if (!network) return res.status(400).json({ error: "Network is required" });
      if (!afaDetails?.fullName || !afaDetails?.ghanaCard || !afaDetails?.dob || !afaDetails?.region || !afaDetails?.location || !afaDetails?.occupation) {
        return res.status(400).json({ error: "Missing AFA registration details" });
      }
      const priceData = await getAfaPrice();
      amount = Number(priceData.price ?? priceData.amount);

    } else if (orderType === "ecg") {
      if (!meterNumber) return res.status(400).json({ error: "Meter number is required" });
      amount = Number(billAmount);
      if (!amount || amount <= 0) return res.status(400).json({ error: "Invalid amount" });

    } else if (orderType === "water") {
      if (!meterNumber) return res.status(400).json({ error: "Account number is required" });
      // Water is a fixed bill amount, resolved from Techlink's validation —
      // never from a number the customer typed in themselves.
      const validation = await validateWaterMeter({ account: meterNumber });
      amount = Number(validation.amountDue ?? validation.amount);
      if (!amount || amount <= 0) return res.status(400).json({ error: "Could not resolve a bill amount for that account" });
      extra.billAccountName = validation.accountName || validation.customerName || null;

    } else if (orderType === "tv") {
      if (!meterNumber || !tvDetails?.service) return res.status(400).json({ error: "Smartcard number and provider are required" });
      const validation = await validateTvSmartcard({ billType: tvDetails.service, account: meterNumber });
      amount = Number(validation.amountDue ?? validation.amount);
      if (!amount || amount <= 0) return res.status(400).json({ error: "Could not resolve an amount due for that smartcard" });
      extra.tvDetails = { ...tvDetails, customerName: validation.customerName || null, package: validation.package || null };

    } else if (orderType === "checker") {
      if (!checkerDetails?.type) return res.status(400).json({ error: "Checker type is required" });
      if (checkerDetails.mode === "lookup") {
        if (!checkerDetails.indexNumber || !checkerDetails.examYear) {
          return res.status(400).json({ error: "Index number and exam year are required" });
        }
        const prices = await getResultCheckServicePrices();
        const row = (prices.prices || prices.data || []).find((p) => (p.type || "").toLowerCase() === checkerDetails.type.toLowerCase());
        amount = Number(row?.price ?? prices.price);
      } else {
        const quantity = Number(checkerDetails.quantity) || 1;
        const prices = await getCheckerPrices();
        const row = (prices.prices || prices.data || []).find((p) => (p.type || "").toLowerCase() === checkerDetails.type.toLowerCase());
        amount = Number(row?.price ?? prices.price) * quantity;
      }
      if (!amount || amount <= 0) return res.status(400).json({ error: "Could not resolve a price for that checker" });
      extra.checkerDetails = checkerDetails;

    } else if (orderType === "tierData") {
      const tier = TIERS[tierKey];
      if (!tier) return res.status(400).json({ error: "Unknown product tier" });
      if (!size) return res.status(400).json({ error: "Select a bundle size" });
      resolvedNetwork = tier.network; // never trust a client-sent network for a tier order — the tier decides it
      // Authoritative price + exact product name come from Techlink's own
      // catalogue right now — never from the browser or the local reference file.
      const catalogue = await listProducts(tier.category);
      const products = catalogue.products || catalogue.data || [];
      const product = products.find((p) => Number(p.size) === Number(size));
      if (!product) return res.status(400).json({ error: "That bundle size is no longer available" });
      amount = Number(product.price ?? product.amount);
      extra.tierDetails = { tierKey, category: tier.category, size: Number(size), name: product.name };

    } else if (orderType === "tierBulkData") {
      const tier = TIERS[tierKey];
      if (!tier) return res.status(400).json({ error: "Unknown product tier" });
      resolvedNetwork = tier.network; // same hardening as tierData above
      if (!Array.isArray(rows) || rows.length === 0) return res.status(400).json({ error: "Add at least one order line" });
      const catalogue = await listProducts(tier.category);
      const products = catalogue.products || catalogue.data || [];
      const resolvedRows = [];
      for (const r of rows) {
        const product = products.find((p) => Number(p.size) === Number(r.size));
        if (!product || !r.phone) {
          return res.status(400).json({ error: `Could not price the line for ${r.phone || "an entry"} — check the size matches an available bundle` });
        }
        resolvedRows.push({ phone: r.phone, size: Number(r.size), name: product.name, price: Number(product.price ?? product.amount) });
      }
      amount = resolvedRows.reduce((sum, r) => sum + r.price, 0);
      extra.tierDetails = { tierKey, category: tier.category, rows: resolvedRows };

    } else if (orderType === "tierBulkAirtime") {
      if (!network) return res.status(400).json({ error: "Network is required" });
      if (!Array.isArray(rows) || rows.length === 0) return res.status(400).json({ error: "Add at least one order line" });
      const resolvedRows = [];
      for (const r of rows) {
        const rowAmount = Number(r.amount);
        if (!r.phone || !rowAmount || rowAmount <= 0) {
          return res.status(400).json({ error: `Invalid line for ${r.phone || "an entry"}` });
        }
        resolvedRows.push({ phone: r.phone, amount: rowAmount });
      }
      amount = resolvedRows.reduce((sum, r) => sum + r.amount, 0);
      extra.tierDetails = { rows: resolvedRows };

    } else {
      return res.status(400).json({ error: "Unknown order type" });
    }

    const reference = `TL${Date.now().toString(36).toUpperCase()}${crypto.randomBytes(5).toString("hex").toUpperCase()}`;

    const order = await createOrder({
      reference,
      orderType,
      network: resolvedNetwork || orderType,
      phone: isBulk ? `${rows.length} recipients` : phone,
      email: normalizedEmail,
      amount,
      bundleId: bundleId || null,
      afaDetails: afaDetails || null,
      meterNumber: meterNumber || null,
      tvDetails: extra.tvDetails || tvDetails || null,
      checkerDetails: extra.checkerDetails || null,
      tierDetails: extra.tierDetails || null,
      status: "pending",
    });

    res.status(200).json({ reference: order.reference, amount: order.amount });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
