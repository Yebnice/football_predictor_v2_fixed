import crypto from "crypto";
import { getSupabase } from "./supabaseClient";

function fromRow(row) {
  return {
    id: row.id,
    caseReference: row.case_reference,
    name: row.name,
    email: row.email,
    phone: row.phone,
    orderReference: row.order_reference,
    category: row.category,
    message: row.message,
    serviceType: row.service_type,
    transactionId: row.transaction_id,
    transactionAmount: row.transaction_amount,
    requestedData: row.requested_data,
    beneficiary: row.beneficiary,
    transactionAt: row.transaction_at,
    transactionDetails: row.transaction_details,
    status: row.status,
    createdAt: row.created_at,
  };
}

export async function createFeedback(entry) {
  const supabase = getSupabase();
  const now = new Date();
  const stamp = now.toISOString().slice(0,10).replace(/-/g, "");
  // Math.random() is not a CSPRNG and shouldn't back anything used as a
  // lookup credential (the email-match bug above meant this alone used to be
  // guessable *and* sufficient to read a case). crypto.randomBytes is.
  const random = crypto.randomBytes(6).toString("base64url").replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toUpperCase();
  const caseReference = `SUP-${stamp}-${random}`;
  const { data, error } = await supabase
    .from("feedback")
    .insert({
      case_reference: caseReference,
      name: entry.name,
      email: entry.email || null,
      phone: entry.phone || null,
      order_reference: entry.orderReference || null,
      category: entry.category || "general",
      message: entry.message,
      service_type: entry.serviceType || null,
      transaction_id: entry.transactionId || null,
      transaction_amount: entry.transactionAmount ?? null,
      requested_data: entry.requestedData || null,
      beneficiary: entry.beneficiary || null,
      transaction_at: entry.transactionAt || null,
      transaction_details: entry.transactionDetails || null,
    })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return fromRow(data);
}

export async function listFeedback() {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("feedback").select("*").order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return (data || []).map(fromRow);
}

export async function updateFeedbackStatus(id, status) {
  const allowed = ["open", "in_progress", "resolved"];
  if (!allowed.includes(status)) throw new Error("Invalid feedback status");
  const supabase = getSupabase();
  const { data, error } = await supabase.from("feedback").update({ status }).eq("id", id).select().single();
  if (error) throw new Error(error.message);
  return fromRow(data);
}

export async function findCustomerCase(caseReference, email, phone) {
  const supabase = getSupabase();
  let query = supabase.from("feedback").select("id,case_reference,name,email,phone,order_reference,category,message,status,created_at").eq("case_reference", caseReference);
  // Same fix as findCustomerOrder in store.js: ilike() treats `email` as a
  // SQL LIKE pattern (a bare "%" matches everything), which would let anyone
  // who guesses a case reference read the case without knowing its real
  // email. pages/api/feedback/track.js already lowercases this value.
  if (email) query = query.eq("email", email);
  else if (phone) query = query.eq("phone", phone);
  else return null;
  const { data, error } = await query.maybeSingle();
  if (error) throw new Error(error.message);
  if (!data) return null;
  return { caseReference: data.case_reference, category: data.category, status: data.status, orderReference: data.order_reference, createdAt: data.created_at, messagePreview: String(data.message || '').slice(0, 120) };
}
