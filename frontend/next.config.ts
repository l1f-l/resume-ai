import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },

  // 静态导出：产物是一堆 HTML/JS/CSS，由 FastAPI 直接托管，线上只需要一个 Python 进程。
  // 代价是必须放弃 middleware 与动态路由段（见 app/workspace、app/jobs/detail 的查询参数写法）。
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
