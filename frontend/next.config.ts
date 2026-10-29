import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    // 同源代理，避免 iframe 预览与导出链接的跨域麻烦
    const target = process.env.API_PROXY || "http://127.0.0.1:8000";
    return [{ source: "/backend/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;
