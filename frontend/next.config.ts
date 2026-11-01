import type { NextConfig } from "next";

// Server-side target for the same-origin `/api/v1` proxy. In Docker this is
// the Compose service name (http://backend:8000); locally it defaults to the
// uvicorn dev server.
const backendUrl = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Emit .next/standalone so the production Docker image can run without the
  // full node_modules tree.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
