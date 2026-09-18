import { listOrders } from "../../../lib/store";
import { isAdminAuthed } from "../../../lib/adminAuth";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  if (!isAdminAuthed(req)) return res.status(401).json({ error: "Unauthorized" });
  try {
    res.status(200).json({ orders: await listOrders() });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
