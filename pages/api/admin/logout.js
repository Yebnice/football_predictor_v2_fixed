import { clearAdminSession } from "../../../lib/adminAuth";
export default function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  clearAdminSession(res);
  return res.status(200).json({ ok: true });
}
