import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Rewrites include cold model startup and synchronous classification.
  experimental: { proxyTimeout: Number(process.env.API_PROXY_TIMEOUT_MS || "900000") },
  async rewrites() {
    const backend = (process.env.API_PROXY_TARGET || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
};
export default nextConfig;
