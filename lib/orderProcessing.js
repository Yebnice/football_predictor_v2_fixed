import { verifyTransaction } from "./paystack";
import {
  getOrder,
  markFailed,
  markPaymentVerified,
  claimFulfillment,
  recoverStaleProcessingOrders,
  markFulfilled,
  markFulfillmentFailed,
  markManualReviewNotified,
  recordManualReviewNotified,
  markCustomerDelayNotified,
  recordCustomerDelayNotified,
  recordUrgentReviewNotified,
} from "./store";
import { fulfillOrder } from "./techlink";
import { notifyAdminManualReview, notifyCustomerProcessingDelay, notifyAdminEscalation } from "./notifications";

export async function verifyAndPrepareOrder(reference) {
  const order = await getOrder(reference);
  if (!order) return { kind: "not_found" };
  if (order.fulfilled) return { kind: "fulfilled", order };

  const txn = await verifyTransaction(reference);
  if (txn.status !== "success") {
    await markFailed(reference, txn.status);
    return { kind: "failed", status: txn.status };
  }

  if (txn.currency && txn.currency !== "GHS") {
    await markFailed(reference, "currency_mismatch");
    return { kind: "failed", status: "currency_mismatch" };
  }

  const expectedPesewas = Math.round(order.amount * 100);
  if (Number(txn.amount) !== expectedPesewas) {
    await markFailed(reference, "amount_mismatch");
    return { kind: "failed", status: "amount_mismatch" };
  }

  const updated = await markPaymentVerified(reference, txn.amount);
  return { kind: "ready", order: updated };
}

export async function fulfillClaimedOrder(reference) {
  const claim = await claimFulfillment(reference);
  if (!claim) {
    const current = await getOrder(reference);
    if (!current) return { kind: "not_found" };
    if (current.fulfilled) return { kind: "fulfilled", order: current };
    if (current.fulfillmentStatus === "processing") return { kind: "processing", order: current };
    return { kind: "not_ready", order: current };
  }

  try {
    const result = await fulfillOrder(claim);
    const updated = await markFulfilled(reference, result);
    return { kind: "fulfilled", order: updated };
  } catch (err) {
    const updated = await markFulfillmentFailed(reference, err.message);
    return { kind: "retryable_failure", order: updated, error: err.message };
  }
}

export async function recoverAndListReadyOrders() {
  const recovered = await recoverStaleProcessingOrders(Number(process.env.FULFILLMENT_STALE_MINUTES || 10));
  for (const order of recovered) {
    try {
      const pending = await markManualReviewNotified(order.reference);
      if (pending) {
        const sent = await notifyAdminManualReview(pending);
        if (sent?.sent) await recordManualReviewNotified(order.reference);
      }
    } catch (err) {
      console.error("Admin stale-order notification failed", order.reference, err);
    }
    try {
      const pending = await markCustomerDelayNotified(order.reference);
      if (pending) {
        const sent = await notifyCustomerProcessingDelay(pending);
        if (sent?.sent) await recordCustomerDelayNotified(order.reference);
      }
    } catch (err) {
      console.error("Customer delay notification failed", order.reference, err);
    }
    const elapsedMinutes = order.manualReviewAt ? (Date.now() - new Date(order.manualReviewAt).getTime()) / 60000 : 0;
    if (elapsedMinutes >= Number(process.env.URGENT_REVIEW_MINUTES || 30) && !order.urgentReviewNotifiedAt) {
      // Each channel is tried and caught independently: a Brevo SMS failure
      // (e.g. bad number, low balance) must not prevent the email escalation
      // from still going out, and vice versa.
      let sent = false;
      if (process.env.ADMIN_SMS_TO && process.env.BREVO_API_KEY) {
        try {
          const result = await notifyAdminEscalation(order, "sms");
          sent = Boolean(result?.sent) || sent;
        } catch (err) {
          console.error("Admin SMS escalation failed", order.reference, err);
        }
      }
      if (process.env.ADMIN_ALERT_EMAIL && process.env.RESEND_API_KEY) {
        try {
          const result = await notifyAdminEscalation(order, "email");
          sent = Boolean(result?.sent) || sent;
        } catch (err) {
          console.error("Admin email escalation failed", order.reference, err);
        }
      }
      if (sent) {
        try {
          await recordUrgentReviewNotified(order.reference);
        } catch (err) {
          console.error("Failed to record urgent review notification", order.reference, err);
        }
      }
    }
  }
  const { listReadyOrders } = await import("./store");
  return listReadyOrders();
}

export async function verifyAndFulfillOrder(reference) {
  const prepared = await verifyAndPrepareOrder(reference);
  if (prepared.kind !== "ready" && prepared.kind !== "fulfilled") return prepared;
  if (prepared.kind === "fulfilled") return prepared;
  return fulfillClaimedOrder(reference);
}
