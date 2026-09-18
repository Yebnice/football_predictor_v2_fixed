import { createClient } from "@supabase/supabase-js";

// Server-side only. Uses the Supabase secret key (or legacy service_role key),
// which bypasses Row Level Security. Only server code imports this file.
// NEVER put a secret key in a NEXT_PUBLIC_ variable or import this from a component.
let client;

export function getSupabase() {
  if (!client) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!url || !key) {
      throw new Error("SUPABASE_URL and SUPABASE_SECRET_KEY must be set — see .env.example");
    }
    client = createClient(url, key, { auth: { persistSession: false } });
  }
  return client;
}
