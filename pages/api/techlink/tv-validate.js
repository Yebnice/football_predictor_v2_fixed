import { rateLimit } from "../../../lib/rateLimit";
import { validateTvSmartcard } from "../../../lib/techlink";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 20, windowMs: 60_000, keySuffix: "techlink-tv-validate" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many requests. Please try again shortly." });

  const { billType, account } = req.body;
  if (!billType || !account) return res.status(400).json({ error: "billType and account are required" });
  try {
    const data = await validateTvSmartcard({ billType, account });
    res.status(200).json(data);
  } catch (err) {
    console.error("Techlink lookup error", err);
    res.status(502).json({ error: "The provider could not be reached right now. Please try again shortly." });
  }
}
