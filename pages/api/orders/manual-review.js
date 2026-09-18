import { isAdminAuthed } from "../../../lib/adminAuth";
import { listManualReviewOrders, manuallyResolveOrder } from "../../../lib/store";

export default async function handler(req, res) {
  if (!isAdminAuthed(req)) return res.status(401).json({ error: "Unauthorized" });
  if (req.method === "GET") {
    try {
      return res.status(200).json({ orders: await listManualReviewOrders() });
    } catch (err) {
      console.error("Manual review list error", err);
      return res.status(500).json({ error: "Could not load manual review orders" });
    }
  }
  if (req.method === "POST") {
    try {
      const { reference, action, note } = req.body || {};
      if (!reference || !action || !note) return res.status(400).json({ error: "reference, action and confirmation note are required" });
      const order = await manuallyResolveOrder(String(reference).trim(), action, note);
      if (!order) return res.status(404).json({ error: "Manual-review order not found or already resolved" });
      return res.status(200).json({ order });
    } catch (err) {
      console.error("Manual review action error", err);
      return res.status(400).json({ error: err.message });
    }
  }
  return res.status(405).json({ error: "Method not allowed" });
}
