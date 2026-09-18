export const FAQ_RULES = [
  { keys: ["track", "order", "status", "where is", "dashboard"], reply: "To check an order, use its order reference together with the checkout email on the Track Order page. For security, we no longer search every order by phone/email alone." },
  { keys: ["airtime"], reply: "We deliver MTN, Telecel and AirtelTigo airtime after payment. Open Buy Airtime, enter the recipient and amount, then pay with Paystack." },
  { keys: ["data", "bundle"], reply: "Data bundle prices are loaded live from the available provider catalogue when you order, so the checkout price is resolved server-side. Most bundles (the Quick data top-up page) deliver in 10–30 seconds. MTN Master is the cheapest MTN tier but can take 30 minutes to a few hours — MTN Express costs a bit more and is usually much faster; both are shown on the MTN Data page." },
  { keys: ["mtn master", "mtn express", "how long", "delivery time", "delivery speed"], reply: "MTN Master is the cheapest MTN data tier but is genuinely not instant — typically 30 minutes to a few hours. MTN Express costs more but is usually delivered much sooner. Other bundles from the Quick data top-up page are usually 10–30 seconds. If nothing arrives after 5 minutes for a quick top-up, check My Orders." },
  { keys: ["ecg", "electricity", "light"], reply: "You can pay an ECG electricity bill from the Bills page. Enter the meter details, confirm the account information and then pay through Paystack." },
  { keys: ["water"], reply: "Ghana Water bill payments are on the Bills page. We validate the account first and show the amount due before payment." },
  { keys: ["afa", "sim", "register sim", "farmer"], reply: "AFA registration is available on the AFA page. It requires the registration details requested there, including Ghana Card information." },
  { keys: ["tv", "dstv", "gotv", "startimes"], reply: "TV subscriptions for DSTV, GOtv and StarTimes are handled from the TV page. We validate the smartcard first so you can confirm the subscription details before paying." },
  { keys: ["checker", "bece", "wassce", "result"], reply: "The Result Checker page offers voucher purchase and a separate service where we process a result-check request. The latter is not guaranteed to be instant." },
  { keys: ["complain", "complaint", "problem", "issue", "refund", "didn't receive", "not received"], reply: "Sorry to hear that — let's get it sorted. For a data or airtime complaint, the support form must include the transaction ID, amount, data/airtime requested, recipient or beneficiary, transaction date and time, and transaction details. For other products, complete the support form with the transaction details relevant to that service. Keep your order reference handy if you have it, and please hold off on placing a duplicate order while this is being checked." },
  { keys: ["pay", "payment", "paystack", "card", "momo", "mobile money"], reply: "Payments are handled through Paystack. Never send your card PIN or mobile-money PIN in chat. The website verifies successful payments on the server before fulfillment." },
  { keys: ["faq", "question", "help"], reply: "I can answer questions about data, airtime, bills, TV, AFA, result checkers, payments and order tracking." },
  { keys: ["contact", "human", "agent", "support", "call"], reply: "For an issue that needs a person, use the Feedback & complaints page. Data and airtime complaints require Transaction ID, Amount, Data/Airtime Requested, Recipient/Beneficiary, Transaction Date & Time, and Transaction Details. Other products use the normal support form with the relevant transaction details." },
];

export const FALLBACK = "I’m not fully sure about that. I can help with data, airtime, ECG, water, TV, AFA, result checkers, payments and order tracking. For a specific payment problem, send your order reference and use the Feedback page.";

export function faqReply(text) {
  const t = String(text || "").toLowerCase();
  const hit = FAQ_RULES.find((rule) => rule.keys.some((key) => t.includes(key)));
  return hit?.reply || FALLBACK;
}
