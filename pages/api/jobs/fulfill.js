import { isAdminAuthed } from "../../../lib/adminAuth";
import { fulfillClaimedOrder, recoverAndListReadyOrders } from "../../../lib/orderProcessing";

function authorized(req) {
  const secret = process.env.CRON_SECRET;
  if (secret && req.headers.authorization === `Bearer ${secret}`) return true;
  return isAdminAuthed(req);
}

export default async function handler(req, res) {
  if (req.method !== "POST" && req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });
  if (!authorized(req)) return res.status(401).json({ error: "Unauthorized" });
  try {
    const recoveredReady = await recoverAndListReadyOrders();
    const orders = recoveredReady.slice(0, Number(process.env.FULFILLMENT_BATCH_SIZE || 10));
    const results = [];
    for (const order of orders) {
      results.push({ reference: order.reference, ...(await fulfillClaimedOrder(order.reference)) });
    }
    return res.status(200).json({ processed: results.length, results });
  } catch (err) {
    console.error("Fulfillment worker error", err);
    return res.status(500).json({ error: "Fulfillment worker failed" });
  }
}
