"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { UploadCard } from "@/components/UploadCard";
import { Empty, MeterBar, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { health, listApplications, listSessions, uploadResume } from "@/lib/api";
import type { HealthInfo } from "@/lib/api";
import { cn } from "@/lib/cn";
import { relativeTime, STAGE_TONE, stageLabel } from "@/lib/stage";
import type { ApplicationSummary, Stage } from "@/lib/types";

interface SessionRow {
  id: string;
  stage: Stage;
  file_name: string;
  job_id: string | null;
  updated_at: number;
  created_at: number;
}

export default function DashboardPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [summary, setSummary] = useState<ApplicationSummary | null>(null);
  const [info, setInfo] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, a, h] = await Promise.all([
        listSessions(6),
        listApplications(),
        health().catch(() => null),
      ]);
      setSessions(s.items as SessionRow[]);
      setSummary(a.summary);
      setInfo(h);
    } catch {
      /* 401 已由 api 层跳转处理 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleUpload = async (file: File, jd: string) => {
    setUploadError(null);
    setUploading(true);
    try {
      const res = await uploadResume(file, jd);
      router.push(`/workspace/${res.session_id}`);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "上传失败");
      setUploading(false);
    }
  };

  const stats = [
    { label: "简历会话", value: sessions.length, hint: "累计解析" },
    { label: "已投递", value: summary?.total ?? 0, hint: "投递总数" },
    { label: "已邀面", value: summary?.interviewing ?? 0, hint: "进入面试" },
    { label: "邀面率", value: `${summary?.interview_rate ?? 0}%`, hint: "邀面 / 投递" },
  ];

  return (
    <AppShell>
      {/* 欢迎 */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">
            {user?.display_name ? `${user.display_name}，` : ""}今天想推进哪一步？
          </h1>
          <p className="mt-1 text-[12.5px] text-slate-500">
            上传简历 → 匹配岗位 → 生成报告 → 投递追踪，全流程都在这里。
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {info?.jobs && (
            <span className="chip bg-white text-slate-500 ring-1 ring-slate-200">
              岗位池 {info.jobs.total} 条 · {info.jobs.index}
            </span>
          )}
          <span
            className={cn(
              "chip ring-1",
              info?.llm_mode === "deepseek" && !info.llm?.degraded
                ? "bg-emerald-50 text-emerald-700 ring-emerald-100"
                : "bg-amber-50 text-amber-700 ring-amber-100",
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
            {info?.llm?.degraded ? "演示引擎（已降级）" : info?.llm_mode === "deepseek" ? "DeepSeek 在线" : "演示引擎"}
          </span>
        </div>
      </div>

      {/* 指标 */}
      <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="card !rounded-xl px-3.5 py-3">
            <div className="text-[11px] text-slate-400">{s.label}</div>
            <div className="mt-1 text-[22px] font-semibold leading-none tracking-tight text-ink">
              {s.value}
            </div>
            <div className="mt-1.5 text-[10.5px] text-slate-400">{s.hint}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* 左：上传 + 最近会话 */}
        <div className="space-y-4">
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-[13px] font-semibold text-slate-700">开始一份新简历</h2>
              <Link href="/jobs" className="text-[11.5px] text-brand-700 hover:underline">
                或先去岗位广场挑岗位 →
              </Link>
            </div>
            <UploadCard onSubmit={handleUpload} busy={uploading} error={uploadError} />
          </div>

          <div>
            <h2 className="mb-2 text-[13px] font-semibold text-slate-700">最近的简历</h2>
            {loading ? (
              <div className="flex items-center gap-2 py-8 text-[12px] text-slate-400">
                <Spinner /> 加载中…
              </div>
            ) : sessions.length === 0 ? (
              <div className="card !rounded-xl">
                <Empty title="还没有简历记录" hint="上传一份 PDF 简历，我会先做结构化解析与匹配诊断。" />
              </div>
            ) : (
              <div className="card divide-y divide-slate-100 overflow-hidden !rounded-xl">
                {sessions.map((s) => (
                  <Link
                    key={s.id}
                    href={`/workspace/${s.id}`}
                    className="flex items-center gap-3 px-3.5 py-2.5 transition hover:bg-slate-50"
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-[12px]">
                      📄
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12.5px] font-medium text-ink">{s.file_name}</div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-slate-400">
                        <span className={cn("chip", STAGE_TONE[s.stage] ?? "bg-slate-100 text-slate-500")}>
                          {stageLabel(s.stage)}
                        </span>
                        {s.job_id && <span className="text-slate-400">岗位池 · {s.job_id}</span>}
                        <span>{relativeTime(s.updated_at)}</span>
                      </div>
                    </div>
                    <span className="shrink-0 text-[11px] text-slate-300">→</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右：投递漏斗 */}
        <div className="space-y-4">
          <div className="card !rounded-xl p-3.5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-[13px] font-semibold text-slate-700">投递漏斗</h2>
              <Link href="/applications" className="text-[11px] text-brand-700 hover:underline">
                查看看板 →
              </Link>
            </div>
            <div className="mt-3 space-y-2.5">
              {[
                { label: "已投递", value: summary?.applied ?? 0, tone: "brand" as const },
                { label: "已邀面", value: summary?.interviewing ?? 0, tone: "amber" as const },
                { label: "已 Offer", value: summary?.offer ?? 0, tone: "brand" as const },
                { label: "未通过", value: summary?.rejected ?? 0, tone: "rose" as const },
              ].map((row) => {
                const total = Math.max(1, summary?.total ?? 0);
                return (
                  <div key={row.label}>
                    <div className="mb-1 flex items-baseline justify-between text-[11.5px]">
                      <span className="text-slate-600">{row.label}</span>
                      <span className="font-medium text-ink">{row.value}</span>
                    </div>
                    <MeterBar value={(row.value / total) * 100} tone={row.tone} />
                  </div>
                );
              })}
            </div>
            {!summary?.total && (
              <p className="mt-3 rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] leading-relaxed text-slate-400">
                还没有投递记录。完成简历优化后，在工作台里就能一键投递。
              </p>
            )}
          </div>

          <div className="card !rounded-xl p-3.5">
            <h2 className="text-[13px] font-semibold text-slate-700">平台能力</h2>
            <ul className="mt-2 space-y-1.5 text-[11.5px] leading-relaxed text-slate-500">
              <li>· 岗位池 50 条模拟大厂岗位，Chroma 语义检索</li>
              <li>· Top3 推荐严格来自岗位池，不会编造岗位</li>
              <li>· 匹配报告含 6 维雷达图与技能缺口清单</li>
              <li>· 投递邮件附 PDF，状态可在看板流转</li>
            </ul>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
