import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResumePilot Pro · 智能求职全链路平台",
  description:
    "多用户求职平台：上传简历做结构化诊断与 STAR 重写，从 50 条岗位池中做语义匹配、生成雷达图匹配报告，并模拟投递追踪进度。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
