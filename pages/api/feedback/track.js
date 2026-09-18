import { rateLimit } from "../../../lib/rateLimit";
import { findCustomerCase } from "../../../lib/feedback";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 10, windowMs: 60_000, keySuffix: "feedback-track" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please wait a moment." });
  try {
    const caseReference = String(req.query.caseReference || "").trim();
    const email = String(req.query.email || "").trim().toLowerCase();
    const phone = String(req.query.phone || "").trim();
    if (!caseReference || (!email && !phone)) return res.status(400).json({ error: "Enter the case reference and the email or phone used for the complaint" });
    const result = await findCustomerCase(caseReference, email, phone);
    if (!result) return res.status(404).json({ error: "No matching support case found" });
    return res.status(200).json({ case: result });
  } catch (err) {
    console.error("Support case lookup error", err);
    return res.status(500).json({ error: "Could not load the support case right now." });
  }
}
