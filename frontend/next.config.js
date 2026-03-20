/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5050";
const SIGNALS_URL = process.env.SIGNALS_URL || "http://localhost:5060";

const nextConfig = {
  webpack: (config) => {
    config.resolve.fallback = {
      ...config.resolve.fallback,
      "@farcaster/mini-app-solana": false,
      "@react-native-async-storage/async-storage": false,
    };
    return config;
  },
  async rewrites() {
    return [
      { source: "/dashboard-proxy", destination: `${BACKEND_URL}/` },
      { source: "/api/status", destination: `${BACKEND_URL}/api/status` },
      { source: "/api/account", destination: `${BACKEND_URL}/api/account` },
      { source: "/api/positions", destination: `${BACKEND_URL}/api/positions` },
      { source: "/api/trades/:path*", destination: `${BACKEND_URL}/api/trades/:path*` },
      { source: "/api/performance", destination: `${BACKEND_URL}/api/performance` },
      { source: "/api/daily-history", destination: `${BACKEND_URL}/api/daily-history` },
      { source: "/api/instruments", destination: `${BACKEND_URL}/api/instruments` },
      { source: "/api/predictions", destination: `${BACKEND_URL}/api/predictions` },
      { source: "/api/broker-performance", destination: `${BACKEND_URL}/api/broker-performance` },
      { source: "/api/backtest-results", destination: `${BACKEND_URL}/api/backtest-results` },
      { source: "/api/system-config", destination: `${BACKEND_URL}/api/system-config` },
      { source: "/api/reports/:path*", destination: `${BACKEND_URL}/api/reports/:path*` },
      { source: "/api/reconciliation", destination: `${BACKEND_URL}/api/reconciliation` },
      // Web3-gated signal API
      { source: "/api/signals/:path*", destination: `${SIGNALS_URL}/api/:path*` },
    ];
  },
};

module.exports = nextConfig;
