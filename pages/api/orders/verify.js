import { verifyAndFulfillOrder } from "../../../lib/orderProcessing";
import { toPublicOrder } from "../../../lib/store";
import { rateLimit } from "../../../lib/rateLimit";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const rl = rateLimit(req, { limit: 6, windowMs: 60_000, keySuffix: "order-verify" });
  if (!rl.allowed) return res.status(429).setHeader("Retry-After", rl.retryAfter).json({ error: "Too many verification attempts. Please wait a moment." });
  try {
    const { reference } = req.body || {};
    if (!reference) return res.status(400).json({ error: "reference is required" });

    const result = await verifyAndFulfillOrder(String(reference).trim());
    if (result.kind === "not_found") return res.status(404).json({ error: "Unknown order" });
    if (result.kind === "failed") return res.status(400).json({ status: result.status });
    if (result.kind === "processing" || result.kind === "retryable_failure" || result.kind === "not_ready") {
      return res.status(202).json({ status: "processing", order: toPublicOrder(result.order) });
    }
    return res.status(200).json({ status: "success", order: toPublicOrder(result.order) });
  } catch (err) {
    console.error("Order verification failed", err);
    return res.status(500).json({ error: "Could not verify payment right now. Please check your order status shortly." });
  }
}
