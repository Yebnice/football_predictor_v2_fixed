const buckets = new Map();

function clientKey(req) {
  const forwarded = req.headers["x-forwarded-for"];
  const ip = (Array.isArray(forwarded) ? forwarded[0] : String(forwarded || "").split(",")[0]).trim();
  return ip || req.socket?.remoteAddress || "unknown";
}

export function rateLimit(req, { limit = 20, windowMs = 60_000, keySuffix = "" } = {}) {
  const key = `${keySuffix}:${clientKey(req)}`;
  const now = Date.now();
  const current = buckets.get(key);
  if (!current || now >= current.resetAt) {
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return { allowed: true, retryAfter: 0 };
  }
  current.count += 1;
  if (current.count <= limit) return { allowed: true, retryAfter: 0 };
  return { allowed: false, retryAfter: Math.max(1, Math.ceil((current.resetAt - now) / 1000)) };
}
