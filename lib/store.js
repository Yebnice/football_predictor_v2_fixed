import { getSupabase } from "./supabaseClient";

function fromRow(row) {
  return {
    reference: row.reference,
    orderType: row.order_type,
    network: row.network,
    phone: row.phone,
    email: row.email,
    amount: Number(row.amount),
    bundleId: row.bundle_id,
    afaDetails: row.afa_details,
    meterNumber: row.meter_number,
    tvDetails: row.tv_details,
    checkerDetails: row.checker_details,
    tierDetails: row.tier_details,
    status: row.status,
    fulfilled: row.fulfilled,
    fulfillmentStatus: row.fulfillment_status || (row.fulfilled ? "fulfilled" : "pending"),
    fulfillmentAttempts: Number(row.fulfillment_attempts || 0),
    processingStartedAt: row.processing_started_at,
    lastFulfillmentError: row.last_fulfillment_error,
    paymentVerifiedAt: row.payment_verified_at,
    paymentAmount: row.payment_amount == null ? null : Number(row.payment_amount),
    result: row.result,
    failReason: row.fail_reason,
    createdAt: row.created_at,
    fulfilledAt: row.fulfilled_at,
    manualReviewNotifiedAt: row.manual_review_notified_at,
    customerDelayNotifiedAt: row.customer_delay_notified_at,
    manualReviewResolution: row.manual_review_resolution,
    manualReviewResolvedAt: row.manual_review_resolved_at,
    manualReviewAt: row.manual_review_at,
    urgentReviewNotifiedAt: row.urgent_review_notified_at,
  };
}


function sanitizePublicResult(result) {
  if (result == null) return null;
  if (typeof result !== "object") return String(result).slice(0, 500);
  const allowed = ["token", "units", "reference", "transactionId", "message", "status", "customerName", "package", "amount", "amountDue"];
  const out = {};
  for (const key of allowed) {
    if (result[key] != null) out[key] = result[key];
  }
  return out;
}

function publicFailure(order) {
  if (order.fulfillmentStatus === "failed") return "We could not complete this order. Please contact support with your order reference.";
  return null;
}

export function toPublicOrder(order) {
  if (!order) return null;
  return {
    reference: order.reference,
    orderType: order.orderType,
    network: order.network,
    amount: order.amount,
    status: order.status,
    fulfilled: order.fulfilled,
    fulfillmentStatus: order.fulfillmentStatus,
    result: sanitizePublicResult(order.result),
    failReason: publicFailure(order),
    createdAt: order.createdAt,
    fulfilledAt: order.fulfilledAt,
  };
}

export async function createOrder(order) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").insert({
    reference: order.reference,
    order_type: order.orderType,
    network: order.network,
    phone: order.phone,
    email: order.email,
    amount: order.amount,
    bundle_id: order.bundleId || null,
    afa_details: order.afaDetails || null,
    meter_number: order.meterNumber || null,
    tv_details: order.tvDetails || null,
    checker_details: order.checkerDetails || null,
    tier_details: order.tierDetails || null,
    status: order.status || "pending",
    fulfillment_status: "pending",
  }).select().single();
  if (error) throw new Error(error.message);
  return fromRow(data);
}

export async function getOrder(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").select("*").eq("reference", reference).maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function findCustomerOrder(reference, email) {
  const supabase = getSupabase();
  // NOTE: intentionally .eq(), not .ilike() — ilike() treats `email` as a SQL
  // LIKE pattern, so a value like "%@%" (which passes an `email.includes("@")`
  // check) would match every order's email and bypass ownership verification
  // entirely. Emails are normalized to lowercase at write time and by every
  // caller of this function, so an exact match is both correct and safe.
  const { data, error } = await supabase.from("orders").select("*").eq("reference", reference).eq("email", email).maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function markPaymentVerified(reference, paymentAmount) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({
    status: "payment_verified",
    payment_amount: paymentAmount,
    payment_verified_at: new Date().toISOString(),
    fulfillment_status: "ready",
    fail_reason: null,
  }).eq("reference", reference).eq("fulfilled", false).in("fulfillment_status", ["pending", "failed", "ready"]).select().maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : getOrder(reference);
}

export async function claimFulfillment(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({
    fulfillment_status: "processing",
    processing_started_at: new Date().toISOString(),
  }).eq("reference", reference).eq("fulfilled", false).in("fulfillment_status", ["ready", "failed"]).select().maybeSingle();
  if (error) throw new Error(error.message);
  if (!data) return null;

  const { data: incremented, error: incrementError } = await supabase.from("orders").update({
    fulfillment_attempts: Number(data.fulfillment_attempts || 0) + 1,
  }).eq("reference", reference).eq("fulfillment_status", "processing").select().single();
  if (incrementError) throw new Error(incrementError.message);
  return fromRow(incremented);
}

export async function markFulfilled(reference, result) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({
    fulfilled: true,
    status: "success",
    fulfillment_status: "fulfilled",
    result,
    last_fulfillment_error: null,
    processing_started_at: null,
    fulfilled_at: new Date().toISOString(),
  }).eq("reference", reference).eq("fulfilled", false).eq("fulfillment_status", "processing").select().single();
  if (error) throw new Error(error.message);
  return fromRow(data);
}

export async function markFulfillmentFailed(reference, reason) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({
    status: "payment_verified",
    fulfillment_status: "failed",
    processing_started_at: null,
    last_fulfillment_error: String(reason || "Fulfillment failed").slice(0, 2000),
    fail_reason: "fulfillment_failed",
  }).eq("reference", reference).eq("fulfilled", false).eq("fulfillment_status", "processing").select().maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : getOrder(reference);
}

export async function markFailed(reference, reason) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({
    status: "failed",
    fail_reason: reason,
    fulfillment_status: "failed",
  }).eq("reference", reference).eq("fulfilled", false).select().single();
  if (error) throw new Error(error.message);
  return fromRow(data);
}

export async function listOrders() {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").select("*").order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return (data || []).map(fromRow);
}

export async function recoverStaleProcessingOrders(staleMinutes = 10, limit = 20) {
  const supabase = getSupabase();
  const cutoff = new Date(Date.now() - staleMinutes * 60_000).toISOString();
  const { data: staleRows, error: findError } = await supabase.from("orders")
    .select("reference")
    .eq("fulfilled", false)
    .eq("fulfillment_status", "processing")
    .lt("processing_started_at", cutoff)
    .order("processing_started_at", { ascending: true })
    .limit(limit);
  if (findError) throw new Error(findError.message);
  const references = (staleRows || []).map((row) => row.reference);
  if (!references.length) return [];
  const reviewAt = new Date().toISOString();
  const { data, error } = await supabase.from("orders").update({
    fulfillment_status: "manual_review",
    status: "payment_verified",
    fail_reason: "stale_fulfillment_recovered",
    last_fulfillment_error: "Fulfillment worker stopped after a stale claim. Confirm provider outcome before retrying to avoid duplicate delivery.",
    processing_started_at: null,
    manual_review_at: reviewAt,
    urgent_review_notified_at: null,
  }).in("reference", references).eq("fulfilled", false).eq("fulfillment_status", "processing").select();
  if (error) throw new Error(error.message);
  return (data || []).map(fromRow);
}

export async function markManualReviewNotified(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").select("*").eq("reference", reference).is("manual_review_notified_at", null).eq("fulfillment_status", "manual_review").maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function recordManualReviewNotified(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({ manual_review_notified_at: new Date().toISOString() }).eq("reference", reference).is("manual_review_notified_at", null).eq("fulfillment_status", "manual_review").select().maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function markCustomerDelayNotified(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").select("*").eq("reference", reference).is("customer_delay_notified_at", null).eq("fulfillment_status", "manual_review").maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function recordCustomerDelayNotified(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({ customer_delay_notified_at: new Date().toISOString() }).eq("reference", reference).is("customer_delay_notified_at", null).eq("fulfillment_status", "manual_review").select().maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function manuallyResolveOrder(reference, action, note) {
  const supabase = getSupabase();
  const cleanNote = String(note || '').trim().slice(0, 2000);
  if (cleanNote.length < 5) throw new Error('A resolution note of at least 5 characters is required');

  if (action === 'confirm_fulfilled') {
    const { data, error } = await supabase.from("orders").update({
      fulfilled: true,
      status: "success",
      fulfillment_status: "fulfilled",
      result: { manualConfirmation: true, note: cleanNote, confirmedAt: new Date().toISOString() },
      last_fulfillment_error: null,
      processing_started_at: null,
      fulfilled_at: new Date().toISOString(),
      manual_review_resolution: cleanNote,
      manual_review_resolved_at: new Date().toISOString(),
    }).eq("reference", reference).eq("fulfilled", false).eq("fulfillment_status", "manual_review").select().maybeSingle();
    if (error) throw new Error(error.message);
    return data ? fromRow(data) : null;
  }

  if (action === 'retry') {
    const { data, error } = await supabase.from("orders").update({
      status: "payment_verified",
      fulfillment_status: "ready",
      fail_reason: null,
      last_fulfillment_error: `Admin-authorized retry: ${cleanNote}`,
      processing_started_at: null,
      manual_review_resolution: `Retry authorized: ${cleanNote}`,
      manual_review_resolved_at: new Date().toISOString(),
      manual_review_notified_at: null,
      customer_delay_notified_at: null,
    }).eq("reference", reference).eq("fulfilled", false).eq("fulfillment_status", "manual_review").select().maybeSingle();
    if (error) throw new Error(error.message);
    return data ? fromRow(data) : null;
  }

  throw new Error('Unsupported manual review action');
}

export async function recordUrgentReviewNotified(reference) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").update({ urgent_review_notified_at: new Date().toISOString() }).eq("reference", reference).eq("fulfillment_status", "manual_review").is("urgent_review_notified_at", null).select().maybeSingle();
  if (error) throw new Error(error.message);
  return data ? fromRow(data) : null;
}

export async function listManualReviewOrders(limit = 50) {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("orders").select("*").eq("fulfillment_status", "manual_review").order("created_at", { ascending: true }).limit(limit);
  if (error) throw new Error(error.message);
  return (data || []).map(fromRow);
}

export async function listReadyOrders(limit = 20) {
  const supabase = getSupabase();
  const maxAttempts = Number(process.env.MAX_FULFILLMENT_ATTEMPTS || 5);
  const { data, error } = await supabase.from("orders").select("*").eq("fulfilled", false).in("fulfillment_status", ["ready", "failed"]).lt("fulfillment_attempts", maxAttempts).order("created_at", { ascending: true }).limit(limit);
  if (error) throw new Error(error.message);
  return (data || []).map(fromRow);
}
