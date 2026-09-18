// Client-side only. Talks to our own API routes — never touches the
// Paystack secret key (that stays in lib/paystack.js on the server).
export async function payAndFulfil({
  orderType,
  network,
  phone,
  email,
  bundleId,
  afaDetails,
  airtimeAmount,
  meterNumber,
  billAmount,
  tvDetails,
  checkerDetails,
  tierKey,
  size,
  rows,
  onDone,
  onError,
}) {
  try {
    const createRes = await fetch("/api/orders/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        orderType,
        network,
        phone,
        email,
        bundleId,
        afaDetails,
        airtimeAmount,
        meterNumber,
        billAmount,
        tvDetails,
        checkerDetails,
        tierKey,
        size,
        rows,
      }),
    });
    const created = await createRes.json();
    if (!createRes.ok) throw new Error(created.error || "Could not start order");

    if (!window.PaystackPop) {
      throw new Error("Payment library is still loading — try again in a moment.");
    }

    try {
      window.localStorage.setItem("pj_email", email);
      window.localStorage.setItem("pj_last_reference", created.reference);
    } catch {}

    const handler = window.PaystackPop.setup({
      key: process.env.NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY,
      email,
      amount: Math.round(created.amount * 100), // pesewas
      currency: "GHS",
      ref: created.reference,
      metadata: { orderType, network, phone },
      callback: function (response) {
        fetch("/api/orders/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reference: response.reference }),
        })
          .then((r) => r.json())
          .then((result) => {
            if (result.status === "success") onDone(result.order, created.amount);
            else onError(`Payment ${result.status || "was not completed"}.`);
          })
          .catch((err) => onError(err.message));
      },
      onClose: function () {
        onError("Payment window closed before completing.");
      },
    });
    handler.openIframe();
  } catch (err) {
    onError(err.message);
  }
}
