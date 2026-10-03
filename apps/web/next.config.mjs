const backendUrl = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig = {
  compiler: {},
  async rewrites() {
    // Proxy API calls through the Next.js origin so the browser never has to
    // reach the backend port directly (fixes private-port blocking in Codespaces).
    return [
      { source: "/api/:path*", destination: `${backendUrl}/:path*` },
      { source: "/generated/:path*", destination: `${backendUrl}/generated/:path*` },
    ];
  },
};

export default nextConfig;
