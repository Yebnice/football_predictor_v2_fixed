import { rateLimit } from "../../../lib/rateLimit";
import { listDataBundles } from "../../../lib/techlink";

// Proxies the LIVE provider catalogue so the frontend never needs its own
// copy of bundle prices — whatever Techlink returns right now is what the
// customer sees and pays. Requires a phone number because some bundles are
// only offered to numbers that qualify for them (per the docs).
export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 30, windowMs: 60_000, keySuffix: "techlink-data-bundles" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please try again shortly." });

  const { network, phone } = req.query;
  if (!network || !phone) return res.status(400).json({ error: "network and phone are required" });
  try {
    const data = await listDataBundles({ network, phone });
    res.status(200).json(data);
  } catch (err) {
    console.error("Techlink lookup error", err);
    res.status(502).json({ error: "The provider could not be reached right now. Please try again shortly." });
  }
}
