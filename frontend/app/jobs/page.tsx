"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Empty, Spinner } from "@/components/ui";
import { jobFilters, listJobs } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Job } from "@/lib/types";

const PAGE = 12;

export default function JobsPage() {
  const [items, setItems] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<{ cities: string[]; seniorities: string[] }>({
    cities: [],
    seniorities: [],
  });
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [seniority, setSeniority] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (nextOffset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const res = await listJobs({
          q,
          city,
          seniority,
          limit: PAGE,
          offset: nextOffset,
        });
        setItems((prev) => (append ? [...prev, ...res.items] : res.items));
        setTotal(res.total);
        setOffset(nextOffset);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      } finally {
        setLoading(false);
      }
    },
    [q, city, seniority],
  );

  useEffect(() => {
    jobFilters()
      .then((f) => setFilters({ cities: f.cities, seniorities: f.seniorities }))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    void load(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, city, seniority]);

  return (
    <AppShell>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">岗位广场</h1>
          <p className="mt-1 text-[12.5px] text-slate-500">
            共 <span className="font-medium text-ink">{total}</span> 条模拟大厂岗位，全部为虚构数据，
            仅用于演示语义匹配能力。
          </p>
        </div>
      </div>

      {/* 筛选 */}
      <div className="card mt-4 flex flex-wrap items-center gap-2 !rounded-xl px-3 py-2.5">
        <div className="relative min-w-[180px] flex-1">
          <svg
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-300"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" strokeLinecap="round" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索岗位、公司或技能，如 React / 推荐算法"
            className="w-full rounded-lg border border-slate-200 py-1.5 pl-8 pr-2.5 text-[12.5px] outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
          />
        </div>

        <select
          value={city}
          onChange={(e) => setCity(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12.5px] text-slate-600 outline-none focus:border-brand-400"
        >
          <option value="">全部城市</option>
          {filters.cities.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={seniority}
          onChange={(e) => setSeniority(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12.5px] text-slate-600 outline-none focus:border-brand-400"
        >
          <option value="">全部经验</option>
          {filters.seniorities.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        {(q || city || seniority) && (
          <button
            className="text-[11.5px] text-slate-400 underline-offset-2 hover:text-slate-600 hover:underline"
            onClick={() => {
              setQ("");
              setCity("");
              setSeniority("");
            }}
          >
            清空筛选
          </button>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-[12px] text-rose-700 ring-1 ring-rose-100">
          {error}
        </div>
      )}

      {/* 列表 */}
      <div className="mt-4">
        {loading && !items.length ? (
          <div className="flex items-center gap-2 py-16 text-[12px] text-slate-400">
            <Spinner /> 加载岗位…
          </div>
        ) : items.length === 0 ? (
          <div className="card !rounded-xl">
            <Empty title="没有匹配的岗位" hint="换个关键词或清空筛选条件试试。" />
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((job) => (
              <Link
                key={job.id}
                href={`/jobs/detail/?id=${job.id}`}
                className="card group flex flex-col !rounded-xl p-3.5 transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[13.5px] font-semibold text-ink group-hover:text-brand-700">
                      {job.title}
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-slate-500">
                      {job.company} · {job.city}
                    </div>
                  </div>
                  <span className="shrink-0 text-[12px] font-semibold text-rose-600">{job.salary}</span>
                </div>

                <div className="mt-2 flex flex-wrap gap-1">
                  <span className="chip bg-slate-50 text-slate-500">{job.seniority}</span>
                  <span className="chip bg-slate-50 text-slate-500">{job.industry}</span>
                </div>

                <div className="mt-2 flex flex-wrap gap-1">
                  {job.skills.slice(0, 5).map((s) => (
                    <span key={s} className="chip bg-brand-50/70 text-brand-700">
                      {s}
                    </span>
                  ))}
                  {job.skills.length > 5 && (
                    <span className="chip bg-slate-100 text-slate-400">+{job.skills.length - 5}</span>
                  )}
                </div>

                <div className="mt-auto pt-2.5 text-[11px] text-brand-700 opacity-0 transition group-hover:opacity-100">
                  查看 JD 并测匹配 →
                </div>
              </Link>
            ))}
          </div>
        )}

        {items.length < total && (
          <div className="mt-4 flex justify-center">
            <button
              className={cn("btn-ghost !py-1.5 text-[12px]")}
              onClick={() => load(offset + PAGE, true)}
              disabled={loading}
            >
              {loading ? <Spinner className="!h-3 !w-3" /> : null} 加载更多（{items.length}/{total}）
            </button>
          </div>
        )}
      </div>
    </AppShell>
  );
}
