/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        // Applies to every route, including API routes.
        source: "/:path*",
        headers: [
          // Prevents the site (including /admin) from being framed by
          // another origin — a basic clickjacking defense.
          { key: "X-Frame-Options", value: "DENY" },
          // Stops browsers from MIME-sniffing responses into an
          // executable content type.
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Don't leak the full referring URL (which can contain order
          // references or session-adjacent query params) to third-party
          // destinations.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Disable powerful browser features this app never uses.
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(self)" },
          // Force HTTPS for a year, including subdomains, once you've
          // confirmed the whole site (and any subdomains you use) is
          // served over HTTPS. Remove/shorten this if you're not yet
          // fully committed to HTTPS-only.
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
