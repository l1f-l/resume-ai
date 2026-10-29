"use client";

import { cn } from "@/lib/cn";
import { Empty, MeterBar, Spinner } from "./ui";
import type { MatchItem } from "@/lib/types";

export function RecommendedJobs({
  items,
  loading,
  error,
  activeJobId,
  onPick,
  onRefresh,
  className,
}: {
  items: MatchItem[];
  loading: boolean;
  error?: string | null;
  activeJobId?: string;
  onPick: (jobId: string) => void;
  onRefresh: () => void;
  className?: string;
}) {
  return (
    <div className={cn("scroll-thin h-full overflow-y-auto px-4 py-3.5", className)}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-700">为你推荐的岗位</h3>
          <p className="mt-0.5 text-[11px] text-slate-400">
            基于简历技能与项目特征，从 50 条模拟岗位池中语义召回
          </p>
        </div>
        <button className="btn-ghost !px-2.5 !py-1.5 text-[11.5px]" onClick={onRefresh} disabled={loading}>
          {loading ? <Spinner className="!h-3 !w-3" /> : "↻"} 重新匹配
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-[12px] text-rose-700 ring-1 ring-rose-100">
          {error}
        </div>
      )}

      {loading && !items.length && (
        <div className="flex flex-col items-center gap-2 py-16 text-[12px] text-slate-400">
          <Spinner />
          正在检索岗位池并计算匹配度…
        </div>
      )}

      {!loading && !items.length && !error && (
        <Empty title="还没有推荐结果" hint="点击右上角「重新匹配」，我会从岗位池里挑出最适合你的 3 个岗位。" />
      )}

      <div className="space-y-2.5">
        {items.map((item) => {
          const active = activeJobId === item.job.id;
          return (
            <div
              key={item.job.id}
              className={cn(
                "rounded-xl border bg-white p-3.5 transition",
                active ? "border-brand-300 ring-2 ring-brand-100" : "border-slate-200/80 hover:border-slate-300",
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[12px] font-bold",
                    item.rank === 1
                      ? "bg-brand-600 text-white"
                      : item.rank === 2
                        ? "bg-brand-100 text-brand-700"
                        : "bg-slate-100 text-slate-500",
                  )}
                >
                  {item.rank}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[13.5px] font-semibold text-ink">{item.job.title}</span>
                    <span className="text-[11.5px] text-slate-500">{item.job.company}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px]">
                    {item.job.city && <span className="chip bg-slate-50 text-slate-500">{item.job.city}</span>}
                    {item.job.seniority && <span className="chip bg-slate-50 text-slate-500">{item.job.seniority}</span>}
                    <span className="chip bg-rose-50 text-rose-600">{item.job.salary}</span>
                  </div>
                </div>

                <div className="shrink-0 text-right">
                  <div
                    className={cn(
                      "text-[19px] font-semibold leading-none",
                      item.score >= 80 ? "text-emerald-600" : item.score >= 65 ? "text-amber-600" : "text-slate-500",
                    )}
                  >
                    {item.score}
                  </div>
                  <div className="mt-0.5 text-[9.5px] text-slate-400">匹配分</div>
                </div>
              </div>

              <div className="mt-2">
                <MeterBar value={item.score} />
              </div>

              <p className="mt-2 text-[11.5px] leading-relaxed text-slate-600">{item.reason}</p>

              <div className="mt-2 flex flex-wrap gap-1">
                {item.matched_skills.slice(0, 5).map((s) => (
                  <span key={s} className="chip bg-emerald-50 text-emerald-700">
                    ✓ {s}
                  </span>
                ))}
                {item.missing_skills.slice(0, 3).map((s) => (
                  <span key={s} className="chip bg-rose-50 text-rose-600">
                    ✗ {s}
                  </span>
                ))}
              </div>

              <div className="mt-2.5 flex items-center gap-2">
                <button
                  className={cn("btn !px-2.5 !py-1 text-[11.5px]", active ? "btn-ghost" : "btn-primary")}
                  onClick={() => onPick(item.job.id)}
                  disabled={loading}
                >
                  {active ? "重新生成报告" : "生成匹配报告 →"}
                </button>
                <a
                  href={`/jobs/detail/?id=${item.job.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-slate-400 underline-offset-2 hover:text-slate-600 hover:underline"
                >
                  查看 JD
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
