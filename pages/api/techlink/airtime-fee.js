import { rateLimit } from "../../../lib/rateLimit";
import { getAirtimeFee } from "../../../lib/techlink";

// Public info from Techlink: the % fee THEY add when debiting your own
// Techlink wallet for an airtime order. Not charged to the customer —
// see the README note on airtime margin for why this matters to you.
export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 20, windowMs: 60_000, keySuffix: "techlink-airtime-fee" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please try again shortly." });

  try {
    const data = await getAirtimeFee();
    res.status(200).json(data);
  } catch (err) {
    console.error("Techlink lookup error", err);
    res.status(502).json({ error: "The provider could not be reached right now. Please try again shortly." });
  }
}
