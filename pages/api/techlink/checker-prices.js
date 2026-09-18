import { rateLimit } from "../../../lib/rateLimit";
import { getCheckerPrices, getResultCheckServicePrices } from "../../../lib/techlink";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 20, windowMs: 60_000, keySuffix: "techlink-checker-prices" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please try again shortly." });

  try {
    const [vouchers, lookupService] = await Promise.all([getCheckerPrices(), getResultCheckServicePrices()]);
    res.status(200).json({ vouchers, lookupService });
  } catch (err) {
    console.error("Techlink lookup error", err);
    res.status(502).json({ error: "The provider could not be reached right now. Please try again shortly." });
  }
}
