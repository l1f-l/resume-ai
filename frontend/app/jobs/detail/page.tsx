"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui";
import { jobDetail, listSessions, uploadResume } from "@/lib/api";
import { cn } from "@/lib/cn";
import { stageLabel } from "@/lib/stage";
import type { Job } from "@/lib/types";

interface SessionRow {
  id: string;
  stage: string;
  file_name: string;
  updated_at: number;
}

/** 静态导出不支持动态路由段，岗位详情改为 /jobs/detail?id=job_017 */
export default function JobDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <JobDetailInner />
    </Suspense>
  );
}

function JobDetailInner() {
  const params = useSearchParams();
  const router = useRouter();
  const jobId = params.get("id") ?? "";

  const [job, setJob] = useState<Job | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!jobId) return;
    Promise.all([jobDetail(jobId), listSessions(5).catch(() => ({ items: [] }))])
      .then(([j, s]) => {
        setJob(j);
        setSessions(s.items as SessionRow[]);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [jobId]);

  const onFile = async (file?: File | null) => {
    if (!file || !job) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("仅支持 PDF 格式");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await uploadResume(file, "", job.id);
      router.push(`/workspace/?sid=${res.session_id}&autorun=1`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <AppShell>
        <div className="flex items-center gap-2 py-20 text-[12px] text-slate-400">
          <Spinner /> 加载岗位…
        </div>
      </AppShell>
    );
  }

  if (!job) {
    return (
      <AppShell>
        <div className="card !rounded-xl p-8 text-center">
          <p className="text-[13px] font-medium text-slate-600">岗位不存在</p>
          <Link href="/jobs/" className="mt-3 inline-block text-[12px] text-brand-700 hover:underline">
            返回岗位广场
          </Link>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <Link href="/jobs/" className="text-[11.5px] text-slate-400 hover:text-slate-600">
        ← 返回岗位广场
      </Link>

      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* 左：JD */}
        <div className="space-y-3">
          <div className="card !rounded-xl p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h1 className="text-[20px] font-semibold tracking-tight text-ink">{job.title}</h1>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-slate-500">
                  <span>{job.company}</span>
                  <span className="text-slate-300">·</span>
                  <span>{job.city}</span>
                  <span className="text-slate-300">·</span>
                  <span>{job.industry}</span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-[18px] font-semibold text-rose-600">{job.salary}</div>
                <div className="mt-0.5 text-[10.5px] text-slate-400">15 薪 · 模拟数据</div>
              </div>
            </div>

            <div className="mt-2.5 flex flex-wrap gap-1">
              <span className="chip bg-slate-100 text-slate-600">{job.seniority}</span>
              {job.tags.map((t) => (
                <span key={t} className="chip bg-slate-50 text-slate-500">
                  {t}
                </span>
              ))}
            </div>

            <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50/60 p-3">
              <div className="mb-1.5 text-[11.5px] font-medium text-slate-600">技能要求</div>
              <div className="flex flex-wrap gap-1">
                {job.skills.map((s) => (
                  <span key={s} className="chip bg-white text-brand-700 ring-1 ring-brand-100">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="card !rounded-xl p-4">
            <h2 className="mb-2 text-[13px] font-semibold text-slate-700">岗位描述</h2>
            <div className="whitespace-pre-wrap text-[12.5px] leading-[1.85] text-slate-600">
              {job.jd_text}
            </div>
          </div>
        </div>

        {/* 右：CTA */}
        <div className="space-y-3">
          <div className="card !rounded-xl p-4">
            <h2 className="text-[13px] font-semibold text-slate-700">测测你的匹配度</h2>
            <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
              上传简历后，我会对比这份 JD 给出 6 维雷达图和技能缺口清单，并接续原有的追问与 STAR 重写流程。
            </p>

            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => onFile(e.target.files?.[0])}
            />
            <button
              className="btn-primary mt-3 w-full !py-2 text-[12.5px]"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              {busy && <Spinner className="!border-white/40 !border-t-white" />}
              {busy ? "解析中…" : "上传简历并生成报告"}
            </button>

            {error && (
              <div className="mt-2 rounded-lg bg-rose-50 px-2.5 py-1.5 text-[11.5px] text-rose-700">
                {error}
              </div>
            )}
          </div>

          {sessions.length > 0 && (
            <div className="card !rounded-xl p-3.5">
              <h2 className="mb-2 text-[12.5px] font-semibold text-slate-700">用已有简历测</h2>
              <div className="space-y-1.5">
                {sessions.map((s) => (
                  <Link
                    key={s.id}
                    href={`/workspace/?sid=${s.id}&job=${job.id}&autorun=1`}
                    className="flex items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-2 transition hover:border-brand-200 hover:bg-brand-50/40"
                  >
                    <span className="text-[12px]">📄</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[11.5px] text-slate-700">{s.file_name}</div>
                      <div className="text-[10px] text-slate-400">{stageLabel(s.stage)}</div>
                    </div>
                    <span className="text-[10.5px] text-brand-600">测 →</span>
                  </Link>
                ))}
              </div>
            </div>
          )}

          <div className={cn("rounded-xl border border-amber-100 bg-amber-50/70 px-3 py-2.5")}>
            <p className="text-[11px] leading-relaxed text-amber-800">
              岗位信息为「ResumePilot Pro」内置的模拟招聘数据，公司与薪资仅用于演示语义匹配，
              不代表任何真实在招岗位。
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
