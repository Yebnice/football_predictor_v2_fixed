import { isAdminAuthed } from "../../../lib/adminAuth";
import { updateFeedbackStatus } from "../../../lib/feedback";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  if (!isAdminAuthed(req)) return res.status(401).json({ error: "Unauthorized" });
  try {
    const { id, status } = req.body || {};
    if (!id || !status) return res.status(400).json({ error: "id and status are required" });
    return res.status(200).json({ feedback: await updateFeedbackStatus(id, status) });
  } catch (err) {
    console.error("Feedback status update error", err);
    return res.status(400).json({ error: err.message });
  }
}
