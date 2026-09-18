function textEscape(value) {
  return String(value || '').replace(/[<>]/g, '');
}

async function sendResendEmail({ to, subject, text, idempotencyKey }) {
  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.NOTIFICATION_FROM_EMAIL;
  if (!apiKey || !from || !to) return { sent: false, skipped: true };

  const response = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
    },
    body: JSON.stringify({ from, to: [to], subject, text }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Notification email failed: ${response.status} ${body.slice(0, 500)}`);
  }
  return { sent: true };
}

export async function notifyAdminManualReview(order) {
  const adminEmail = process.env.ADMIN_ALERT_EMAIL;
  if (!adminEmail) return { sent: false, skipped: true };
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || '';
  const text = [
    'PjDigitalServices — Manual Review Required',
    '',
    `Order: ${textEscape(order.reference)}`,
    `Amount: GHS ${Number(order.amount || 0).toFixed(2)}`,
    `Payment: ${textEscape(order.status)}`,
    `Fulfillment: ${textEscape(order.fulfillmentStatus)}`,
    `Detected: ${order.processingStartedAt ? new Date(order.processingStartedAt).toLocaleString() : new Date().toLocaleString()}`,
    '',
    'Reason: fulfillment remained unresolved beyond the configured safety threshold.',
    '',
    'Please confirm the provider outcome before any further fulfillment attempt. Do not blindly retry an uncertain digital-value transaction because it may cause duplicate delivery.',
    '',
    `Admin dashboard: ${baseUrl}/admin`,
  ].join('\n');
  return sendResendEmail({ to: adminEmail, subject: `PjDigitalServices alert — ${order.reference} requires manual review`, text, idempotencyKey: `manual-review/${order.reference}` });
}

export async function notifyCustomerProcessingDelay(order) {
  if (!order?.email) return { sent: false, skipped: true };
  const text = [
    'PjDigitalServices — Order Update',
    '',
    `Your order ${textEscape(order.reference)} is still being processed.`,
    '',
    'We are sorry for the delay. Please do not place a duplicate order while we complete the processing of your request.',
    '',
    'You can check the latest status from the My Orders / Track Order page using your order reference and checkout email.',
  ].join('\n');
  return sendResendEmail({ to: order.email, subject: `Your PjDigitalServices order ${order.reference} is still processing`, text, idempotencyKey: `processing-delay/${order.reference}` });
}


function cleanPhone(value) {
  // Brevo's transactionalSMS/send endpoint wants digits (+ country code) with
  // no leading "+" and no whitespace/formatting characters.
  return String(value || '').replace(/\s+/g, '').replace(/^\+/, '');
}

async function sendBrevoSms({ to, sender, content, idempotencyKey }) {
  const apiKey = process.env.BREVO_API_KEY;
  if (!apiKey || !to || !sender) return { sent: false, skipped: true };
  const recipient = cleanPhone(to);
  if (!/^\d{6,15}$/.test(recipient)) {
    // Fail loudly rather than silently mis-sending: a malformed ADMIN_SMS_TO
    // is a config error, not a "channel not configured" situation.
    throw new Error(`Brevo SMS notification failed: ADMIN_SMS_TO is not a valid E.164-style number (${recipient.length} digits)`);
  }
  const response = await fetch('https://api.brevo.com/v3/transactionalSMS/send', {
    method: 'POST',
    headers: {
      'api-key': apiKey,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      sender: String(sender).slice(0, 11),
      recipient,
      content: String(content).slice(0, 918), // ~6 concatenated SMS segments; Brevo splits automatically past 160 chars
      type: 'transactional', // non-promotional alert: no quiet-hours throttling, no STOP-code requirement
      tag: 'urgent-manual-review',
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Brevo SMS notification failed: ${response.status} ${detail.slice(0, 300)}`);
  }
  return { sent: true, idempotencyKey };
}

export async function notifyAdminEscalation(order, channel) {
  const text = [
    'PjDigitalServices — URGENT Manual Review',
    '',
    `Order: ${textEscape(order.reference)}`,
    `Amount: GHS ${Number(order.amount || 0).toFixed(2)}`,
    'Status: Paid / fulfillment requires provider confirmation.',
    '',
    'Do not retry until the provider outcome is confirmed.',
  ].join('\n');

  if (channel === 'email') {
    // Second, independent escalation channel (replaces the old WhatsApp leg).
    // Reuses the existing Resend integration rather than adding a second
    // email provider on top of Brevo.
    const adminEmail = process.env.ADMIN_ALERT_EMAIL;
    if (!adminEmail) return { sent: false, skipped: true };
    return sendResendEmail({
      to: adminEmail,
      subject: `URGENT — order ${order.reference} still needs manual review`,
      text,
      idempotencyKey: `urgent-review-email/${order.reference}`,
    });
  }

  return sendBrevoSms({
    to: process.env.ADMIN_SMS_TO,
    sender: process.env.BREVO_SMS_SENDER || 'PjDigital',
    content: text,
    idempotencyKey: `urgent-review-sms/${order.reference}`,
  });
}
