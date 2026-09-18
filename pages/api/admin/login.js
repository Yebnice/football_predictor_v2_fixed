import { constantTimePasswordMatch, createAdminSession } from "../../../lib/adminAuth";

const attempts = new Map();
const WINDOW_MS = 10 * 60 * 1000;
const MAX_ATTEMPTS = 10;

function getKey(req) {
  const forwarded = req.headers["x-forwarded-for"];
  return (Array.isArray(forwarded) ? forwarded[0] : String(forwarded || "").split(",")[0]).trim() || "unknown";
}

export default function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });
  const key = getKey(req);
  const now = Date.now();
  const current = attempts.get(key);
  if (!current || now - current.startedAt > WINDOW_MS) attempts.set(key, { startedAt: now, count: 0 });
  const state = attempts.get(key);
  if (state.count >= MAX_ATTEMPTS) return res.status(429).json({ error: "Too many login attempts. Try again later." });
  state.count += 1;
  if (!constantTimePasswordMatch(req.body?.password)) return res.status(401).json({ error: "Wrong password." });
  attempts.delete(key);
  try {
    createAdminSession(res);
  } catch (err) {
    // Fails closed by design when ADMIN_SESSION_SECRET is missing/too short —
    // but report it as a clean JSON error instead of crashing the request,
    // so the login form can show something actionable instead of a raw
    // "Internal Server Error" the client can't parse.
    console.error("Admin login: could not create session —", err.message);
    return res.status(500).json({ error: "Server misconfigured: ADMIN_SESSION_SECRET is missing or invalid. Set a random string of 32+ characters in your environment variables and redeploy." });
  }
  return res.status(200).json({ ok: true });
}
