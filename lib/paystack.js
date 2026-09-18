// Server-side only. Never import this file from a component that runs in
// the browser — PAYSTACK_SECRET_KEY must stay on the server.
import crypto from "crypto";

const PAYSTACK_BASE = "https://api.paystack.co";

function authHeaders() {
  const secret = process.env.PAYSTACK_SECRET_KEY;
  if (!secret) throw new Error("PAYSTACK_SECRET_KEY is not set");
  return { Authorization: `Bearer ${secret}`, "Content-Type": "application/json" };
}

/**
 * Confirms the real status of a transaction with Paystack. Always the
 * source of truth — never trust a "success" reported only by the browser.
 * GET https://api.paystack.co/transaction/verify/:reference
 */
export async function verifyTransaction(reference) {
  const res = await fetch(`${PAYSTACK_BASE}/transaction/verify/${encodeURIComponent(reference)}`, {
    headers: authHeaders(),
  });
  const data = await res.json();
  if (!res.ok || !data.status) {
    throw new Error(data.message || "Failed to verify transaction with Paystack");
  }
  return data.data; // { status: 'success' | 'failed' | 'abandoned' | ..., amount, currency, reference, metadata, ... }
}

/**
 * Optional alternative flow: initialize the transaction from the server
 * and hand the frontend an access_code to resume in Paystack Popup V2.
 * Not used by the default flow in this project (which uses Popup V1 with
 * the public key + a server-created reference), but kept here in case you
 * switch later. POST https://api.paystack.co/transaction/initialize
 */
export async function initializeTransaction({ amount, email, reference, metadata, currency = "GHS" }) {
  const res = await fetch(`${PAYSTACK_BASE}/transaction/initialize`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      amount: Math.round(amount * 100), // Paystack wants the amount in pesewas for GHS
      email,
      currency,
      reference,
      metadata,
    }),
  });
  const data = await res.json();
  if (!res.ok || !data.status) {
    throw new Error(data.message || "Failed to initialize transaction with Paystack");
  }
  return data.data; // { authorization_url, access_code, reference }
}

/**
 * Verifies the x-paystack-signature header on incoming webhooks so you
 * know the event genuinely came from Paystack and wasn't forged.
 */
export function verifyWebhookSignature(rawBody, signatureHeader) {
  if (!signatureHeader) return false;
  const hash = crypto
    .createHmac("sha512", process.env.PAYSTACK_SECRET_KEY)
    .update(rawBody)
    .digest("hex");
  const a = Buffer.from(hash, "hex");
  const b = Buffer.from(String(signatureHeader), "hex");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
