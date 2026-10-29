"use client";

import { useState } from "react";
import { applyResumeUrl, applyToJob } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Spinner } from "./ui";
import type { Application, Job } from "@/lib/types";

type Result = {
  application: Application;
  mail: { status: string; to: string; subject: string; error: string; preview: string; smtp_ready: boolean };
};

export function ApplyDialog({
  open,
  job,
  sessionId,
  matchScore,
  onClose,
  onApplied,
}: {
  open: boolean;
  job: Job | null;
  sessionId: string;
  matchScore?: number;
  onClose: () => void;
  onApplied?: (app: Application) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  if (!open || !job) return null;

  const close = () => {
    if (busy) return;
    setResult(null);
    setError(null);
    setNote("");
    onClose();
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await applyToJob(sessionId, job.id, note);
      setResult(res);
      onApplied?.(res.application);
    } catch (err) {
      setError(err instanceof Error ? err.message : "投递失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={close} />

      <div className="relative flex max-h-[86vh] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        {/* header */}
        <div className="flex shrink-0 items-center gap-2 border-b border-slate-100 px-5 py-3">
          <div className="text-[14px] font-semibold text-ink">
            {result ? "投递完成" : "确认投递"}
          </div>
          <span className="chip bg-slate-100 text-slate-500">
            {job.company} · {job.title}
          </span>
          <button
            onClick={close}
            className="ml-auto rounded-lg px-2 py-1 text-[16px] leading-none text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">
          {!result ? (
            <>
              <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[13px] font-semibold text-ink">{job.title}</span>
                  <span className="text-[12px] text-slate-500">{job.company}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5 text-[10.5px]">
                  <span className="chip bg-white text-slate-600 ring-1 ring-slate-200">{job.city}</span>
                  <span className="chip bg-rose-50 text-rose-600">{job.salary}</span>
                  <span className="chip bg-white text-slate-600 ring-1 ring-slate-200">{job.seniority}</span>
                  {typeof matchScore === "number" && matchScore > 0 && (
                    <span className="chip bg-brand-50 text-brand-700">匹配度 {matchScore}</span>
                  )}
                </div>
              </div>

              <ul className="mt-3.5 space-y-1.5 text-[12px] leading-relaxed text-slate-600">
                <li>· 系统会用你<strong>已优化</strong>的简历生成 PDF 附件，并自动写一封求职邮件</li>
                <li>· 收件人固定为你的注册邮箱（模拟真实投递，不会发给第三方）</li>
                <li>· 投递后可在「投递看板」把状态推进到已邀面 / 未通过</li>
              </ul>

              <label className="mt-4 block">
                <span className="mb-1 block text-[11.5px] font-medium text-slate-600">备注（可选）</span>
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  maxLength={200}
                  placeholder="例如：内推码、可到岗时间"
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-[12.5px] outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                />
              </label>

              {error && (
                <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-[12px] text-rose-700 ring-1 ring-rose-100">
                  {error}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {result.mail.status === "sent" && (
                  <span className="chip bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
                    ✓ 邮件已发送
                  </span>
                )}
                {result.mail.status === "simulated" && (
                  <span className="chip bg-amber-50 text-amber-700 ring-1 ring-amber-100">
                    演示模式 · 已生成本地邮件存档
                  </span>
                )}
                {result.mail.status === "failed" && (
                  <span className="chip bg-rose-50 text-rose-700 ring-1 ring-rose-100">发送失败</span>
                )}
                <span className="text-[11.5px] text-slate-500">收件人：{result.mail.to}</span>
                <a
                  href={applyResumeUrl(result.application.id)}
                  download
                  className="ml-auto text-[11.5px] font-medium text-brand-700 underline-offset-2 hover:underline"
                >
                  下载投递用 PDF ↓
                </a>
              </div>

              {result.mail.error && result.mail.status !== "sent" && (
                <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{result.mail.error}</p>
              )}

              <div className="mt-3 overflow-hidden rounded-xl border border-slate-200">
                <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2">
                  <span className="text-[11px] font-medium text-slate-500">邮件主题</span>
                  <span className="truncate text-[12px] font-medium text-ink">{result.mail.subject}</span>
                </div>
                <div
                  className="max-h-[320px] overflow-y-auto px-4 py-3 text-[12.5px] leading-relaxed text-slate-700 scroll-thin"
                  dangerouslySetInnerHTML={{ __html: result.mail.preview }}
                />
              </div>
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-100 px-5 py-3">
          {!result ? (
            <>
              <button className="btn-ghost !py-1.5 text-[12px]" onClick={close} disabled={busy}>
                取消
              </button>
              <button className="btn-primary !py-1.5 text-[12px]" onClick={submit} disabled={busy}>
                {busy && <Spinner className="!border-white/40 !border-t-white" />}
                {busy ? "正在生成邮件并发送…" : "确认投递"}
              </button>
            </>
          ) : (
            <>
              <a href="/applications" className="btn-ghost !py-1.5 text-[12px]">
                去投递看板
              </a>
              <button className="btn-primary !py-1.5 text-[12px]" onClick={close}>
                完成
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
