import { rateLimit } from "../../../lib/rateLimit";
import { lookupEcgMeter } from "../../../lib/techlink";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 20, windowMs: 60_000, keySuffix: "techlink-ecg-lookup" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please try again shortly." });

  const { meter } = req.query;
  if (!meter) return res.status(400).json({ error: "meter is required" });
  try {
    const data = await lookupEcgMeter(meter);
    res.status(200).json(data);
  } catch (err) {
    console.error("Techlink lookup error", err);
    res.status(502).json({ error: "The provider could not be reached right now. Please try again shortly." });
  }
}
