import { verifyWebhookSignature } from "../../../lib/paystack";
import { verifyAndPrepareOrder } from "../../../lib/orderProcessing";

export const config = { api: { bodyParser: false } };

function readRawBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => { data += chunk; });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();
  try {
    const rawBody = await readRawBody(req);
    const signature = req.headers["x-paystack-signature"];
    if (!verifyWebhookSignature(rawBody, signature)) return res.status(401).json({ error: "Invalid signature" });

    const event = JSON.parse(rawBody);
    if (event.event === "charge.success" && event.data?.reference) {
      // A webhook must acknowledge quickly. We verify the payment and put the
      // order into the retryable `ready` state; the browser callback or the
      // scheduled worker performs the actual Techlink fulfillment.
      await verifyAndPrepareOrder(event.data.reference);
    }
    return res.status(200).json({ received: true });
  } catch (err) {
    console.error("Paystack webhook error", err);
    return res.status(500).json({ error: "Webhook processing failed" });
  }
}
