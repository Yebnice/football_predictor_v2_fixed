import { getSupabase } from "./supabaseClient";

export async function upsertCustomer({ name, email, phone }) {
  const supabase = getSupabase();
  const key = email.toLowerCase();
  const { data, error } = await supabase
    .from("customers")
    .upsert({ email: key, name, phone }, { onConflict: "email" })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

export async function findCustomer(email) {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("customers")
    .select("*")
    .eq("email", (email || "").toLowerCase())
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data;
}

export async function listCustomers() {
  const supabase = getSupabase();
  const { data, error } = await supabase.from("customers").select("*").order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return data || [];
}
