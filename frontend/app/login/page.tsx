"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { Spinner } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const next = params.get("next") || "/";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await signIn(email.trim(), password);
      else await signUp(email.trim(), password, name.trim());
      router.replace(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请重试");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* 左：品牌 */}
      <div className="relative hidden flex-1 flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-700 via-brand-600 to-emerald-700 p-12 text-white lg:flex">
        <div className="absolute -right-20 -top-20 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute -bottom-24 -left-16 h-80 w-80 rounded-full bg-emerald-300/20 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-2.5">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-white/15 text-[16px] font-bold backdrop-blur">
              R
            </div>
            <div className="text-[17px] font-semibold tracking-tight">ResumePilot Pro</div>
          </div>
          <h1 className="mt-14 max-w-md text-[34px] font-semibold leading-[1.25] tracking-tight">
            从「改简历」到
            <br />
            「拿下 offer」的全链路
          </h1>
          <p className="mt-4 max-w-md text-[14px] leading-relaxed text-white/70">
            结构化诊断 · STAR 重写 · 岗位池语义匹配 · 匹配度雷达图 · 投递进度看板
          </p>
        </div>
        <div className="relative grid gap-2.5">
          {[
            ["岗位池语义匹配", "50 条大厂模拟岗位，RAG 召回最匹配的 3 个"],
            ["匹配度雷达图", "技能覆盖 / 经验深度 / 项目复杂度等 6 维对比"],
            ["投递闭环", "一键生成求职邮件并附 PDF 简历，进度可视化"],
          ].map(([t, d]) => (
            <div key={t} className="rounded-xl border border-white/15 bg-white/5 px-3.5 py-2.5 backdrop-blur-sm">
              <div className="text-[12.5px] font-medium">{t}</div>
              <div className="mt-0.5 text-[11.5px] text-white/60">{d}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 右：表单 */}
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-[380px]">
          <div className="mb-7 lg:hidden">
            <div className="flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-[14px] font-bold text-white">
                R
              </div>
              <div className="text-[15px] font-semibold">ResumePilot Pro</div>
            </div>
          </div>

          <h2 className="text-[22px] font-semibold tracking-tight text-ink">
            {mode === "login" ? "登录你的求职工作台" : "创建账号，开始求职"}
          </h2>
          <p className="mt-1.5 text-[12.5px] text-slate-500">
            {mode === "login" ? "简历与投递记录都与账号绑定，换设备也能继续" : "注册后简历解析、优化与投递记录都会归属到你的账号"}
          </p>

          <div className="mt-6 flex rounded-xl bg-slate-100 p-1">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
                className={cn(
                  "flex-1 rounded-lg py-1.5 text-[12.5px] font-medium transition",
                  mode === m ? "bg-white text-ink shadow-sm" : "text-slate-500 hover:text-slate-700",
                )}
              >
                {m === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="mt-5 space-y-3">
            {mode === "register" && (
              <label className="block">
                <span className="mb-1 block text-[11.5px] font-medium text-slate-600">昵称</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="怎么称呼你"
                  maxLength={40}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[13px] outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                />
              </label>
            )}

            <label className="block">
              <span className="mb-1 block text-[11.5px] font-medium text-slate-600">邮箱</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[13px] outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-[11.5px] font-medium text-slate-600">密码</span>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "至少 8 位，含字母和数字" : "请输入密码"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[13px] outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
              />
            </label>

            {error && (
              <div className="rounded-lg bg-rose-50 px-3 py-2 text-[12px] leading-relaxed text-rose-700 ring-1 ring-rose-100">
                {error}
              </div>
            )}

            <button type="submit" disabled={busy} className="btn-primary w-full !py-2.5 !text-[13px]">
              {busy && <Spinner className="!border-white/40 !border-t-white" />}
              {mode === "login" ? "登录" : "创建账号"}
            </button>
          </form>

          <p className="mt-5 text-center text-[11px] leading-relaxed text-slate-400">
            简历解析、优化记录、投递进度均与账号强绑定，
            <br />
            其他账号无法访问你的任何数据。
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="grid min-h-screen place-items-center text-sm text-slate-400">加载中…</div>}>
      <LoginForm />
    </Suspense>
  );
}
