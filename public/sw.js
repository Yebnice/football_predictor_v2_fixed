// Minimal service worker — its only job is to exist, which is what lets
// mobile browsers offer "Add to Home Screen" / "Install app". It doesn't
// cache anything, so every visit still hits the network. That's the right
// tradeoff for a storefront where prices and stock can change — add real
// caching later only for genuinely static assets (fonts, icons) if you want
// faster repeat loads.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", () => self.clients.claim());
self.addEventListener("fetch", () => {}); // no-op, network passthrough
