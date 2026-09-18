import { upsertCustomer } from "../../../lib/customers";
import { rateLimit } from "../../../lib/rateLimit";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 5, windowMs: 60_000, keySuffix: "customer-register" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many registration attempts. Please wait a moment." });
  try {
    const { name, email, phone } = req.body;
    if (!name || !email || !phone) {
      return res.status(400).json({ error: "Name, email and phone are all required" });
    }
    const customer = await upsertCustomer({ name, email, phone });
    res.status(200).json({ customer });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
