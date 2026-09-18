import { rateLimit } from "../../../lib/rateLimit";
import { findCustomerOrder, toPublicOrder } from "../../../lib/store";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 12, windowMs: 60_000, keySuffix: "orders" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please wait a moment and try again." });

  const reference = String(req.query.reference || "").trim();
  const email = String(req.query.email || "").trim().toLowerCase();
  if (!reference || !email || reference.length < 6 || !email.includes("@")) {
    return res.status(400).json({ error: "Enter your order reference and the email used at checkout" });
  }

  try {
    const order = await findCustomerOrder(reference, email);
    if (!order) return res.status(404).json({ error: "No matching order found. Check the reference and email and try again." });
    return res.status(200).json({ orders: [toPublicOrder(order)] });
  } catch (err) {
    console.error("Order tracking error", err);
    return res.status(500).json({ error: "Could not load your order right now." });
  }
}
