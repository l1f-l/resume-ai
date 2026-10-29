"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Empty, Spinner } from "@/components/ui";
import {
  applicationEvents,
  applyResumeUrl,
  listApplications,
  updateApplication,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/stage";
import type { Application, ApplicationStatus, ApplicationSummary } from "@/lib/types";

type Col = { key: string; label: string; tone: string; statuses: ApplicationStatus[] };

const COLUMNS: Col[] = [
  { key: "applied", label: "已投递", tone: "bg-sky-500", statuses: ["applied"] },
  { key: "interviewing", label: "已邀面", tone: "bg-amber-500", statuses: ["interviewing"] },
  {
    key: "closed",
    label: "已结束",
    tone: "bg-slate-400",
    statuses: ["offer", "rejected", "withdrawn"],
  },
];

const MAIL_BADGE: Record<string, { label: string; cls: string }> = {
  sent: { label: "邮件已发送", cls: "bg-emerald-50 text-emerald-700" },
  simulated: { label: "演示存档", cls: "bg-amber-50 text-amber-700" },
  failed: { label: "发送失败", cls: "bg-rose-50 text-rose-700" },
  pending: { label: "待发送", cls: "bg-slate-100 text-slate-500" },
};

const NEXT_ACTIONS: Record<string, { to: ApplicationStatus; label: string; cls: string }[]> = {
  applied: [
    { to: "interviewing", label: "标记已邀面", cls: "bg-amber-500 text-white hover:bg-amber-600" },
    { to: "rejected", label: "未通过", cls: "bg-slate-100 text-slate-600 hover:bg-slate-200" },
    { to: "withdrawn", label: "撤回", cls: "bg-slate-100 text-slate-500 hover:bg-slate-200" },
  ],
  interviewing: [
    { to: "offer", label: "拿到 Offer", cls: "bg-brand-600 text-white hover:bg-brand-700" },
    { to: "rejected", label: "未通过", cls: "bg-slate-100 text-slate-600 hover:bg-slate-200" },
  ],
  offer: [],
  rejected: [],
  withdrawn: [],
};

export default function ApplicationsPage() {
  const [items, setItems] = useState<Application[]>([]);
  const [summary, setSummary] = useState<ApplicationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [events, setEvents] = useState<Record<string, { label: string; note: string; created_at: number }[]>>({});

  const load = useCallback(async () => {
    try {
      const res = await listApplications();
      setItems(res.items);
      setSummary(res.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const move = async (app: Application, to: ApplicationStatus) => {
    setBusyId(app.id);
    setError(null);
    try {
      const res = await updateApplication(app.id, to);
      setItems((prev) => prev.map((x) => (x.id === app.id ? res.application : x)));
      const s = await listApplications();
      setSummary(s.summary);
      if (expanded === app.id) {
        const ev = await applicationEvents(app.id);
        setEvents((prev) => ({ ...prev, [app.id]: ev.items }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "状态更新失败");
    } finally {
      setBusyId(null);
    }
  };

  const toggle = async (app: Application) => {
    if (expanded === app.id) {
      setExpanded(null);
      return;
    }
    setExpanded(app.id);
    if (!events[app.id]) {
      try {
        const ev = await applicationEvents(app.id);
        setEvents((prev) => ({ ...prev, [app.id]: ev.items }));
      } catch {
        /* 忽略 */
      }
    }
  };

  return (
    <AppShell wide>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">投递看板</h1>
          <p className="mt-1 text-[12.5px] text-slate-500">
            投递状态按「已投递 → 已邀面 → 已结束」流转，每次变更都会留下时间轴记录。
          </p>
        </div>
        <div className="flex items-center gap-2">
          {summary && (
            <>
              <Stat label="投递" value={summary.total} />
              <Stat label="邀面" value={summary.interviewing} tone="amber" />
              <Stat label="Offer" value={summary.offer} tone="brand" />
              <Stat label="邀面率" value={`${summary.interview_rate}%`} />
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-[12px] text-rose-700 ring-1 ring-rose-100">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-20 text-[12px] text-slate-400">
          <Spinner /> 加载投递记录…
        </div>
      ) : items.length === 0 ? (
        <div className="card mt-4 !rounded-xl">
          <Empty
            title="还没有投递记录"
            hint="完成简历优化后，在工作台右上角点「投递」，系统会用优化版简历生成 PDF 并发送求职邮件。"
          />
          <div className="pb-8 text-center">
            <Link href="/jobs" className="btn-primary !py-1.5 text-[12px]">
              去岗位广场挑一个
            </Link>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 lg:grid-cols-3">
          {COLUMNS.map((col) => {
            const list = items.filter((a) => col.statuses.includes(a.status));
            return (
              <div key={col.key} className="flex min-h-[200px] flex-col rounded-2xl bg-slate-100/60 p-2.5">
                <div className="mb-2 flex items-center gap-1.5 px-1">
                  <span className={cn("h-2 w-2 rounded-full", col.tone)} />
                  <span className="text-[12.5px] font-semibold text-slate-700">{col.label}</span>
                  <span className="rounded-full bg-white px-1.5 text-[10.5px] font-medium text-slate-500">
                    {list.length}
                  </span>
                </div>

                <div className="space-y-2">
                  {list.map((app) => {
                    const mail = MAIL_BADGE[app.mail_status] ?? MAIL_BADGE.pending;
                    const actions = NEXT_ACTIONS[app.status] ?? [];
                    const isOpen = expanded === app.id;
                    return (
                      <div key={app.id} className="rounded-xl bg-white p-3 shadow-sm ring-1 ring-slate-200/60">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-[12.5px] font-semibold text-ink">
                              {app.job_title}
                            </div>
                            <div className="mt-0.5 truncate text-[11px] text-slate-500">
                              {app.company} · {app.city}
                            </div>
                          </div>
                          {app.match_score > 0 && (
                            <span
                              className={cn(
                                "shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold",
                                app.match_score >= 75
                                  ? "bg-emerald-50 text-emerald-700"
                                  : "bg-slate-100 text-slate-500",
                              )}
                            >
                              {app.match_score}
                            </span>
                          )}
                        </div>

                        <div className="mt-1.5 flex flex-wrap items-center gap-1">
                          <span className={cn("chip", mail.cls)}>{mail.label}</span>
                          <span className="chip bg-slate-50 text-slate-500">{app.salary}</span>
                          <span className="ml-auto text-[10px] text-slate-400">
                            {relativeTime(app.updated_at)}
                          </span>
                        </div>

                        {app.note && (
                          <p className="mt-1.5 rounded-md bg-slate-50 px-2 py-1 text-[10.5px] leading-relaxed text-slate-500">
                            {app.note}
                          </p>
                        )}

                        {isOpen && (
                          <div className="mt-2 rounded-lg border border-slate-100 bg-slate-50/70 p-2">
                            <div className="mb-1 text-[10px] font-medium text-slate-500">状态时间轴</div>
                            <ul className="space-y-1">
                              {(events[app.id] ?? []).map((ev, i) => (
                                <li key={i} className="flex items-start gap-1.5 text-[10.5px] text-slate-500">
                                  <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                                  <span>
                                    <span className="font-medium text-slate-700">{ev.label}</span>
                                    {ev.note ? ` · ${ev.note}` : ""}
                                    <span className="ml-1 text-slate-400">{relativeTime(ev.created_at)}</span>
                                  </span>
                                </li>
                              ))}
                            </ul>
                            <a
                              href={applyResumeUrl(app.id)}
                              download
                              className="mt-1.5 inline-block text-[10.5px] text-brand-700 underline-offset-2 hover:underline"
                            >
                              下载投递用 PDF ↓
                            </a>
                          </div>
                        )}

                        <div className="mt-2 flex flex-wrap items-center gap-1">
                          {actions.map((act) => (
                            <button
                              key={act.to}
                              className={cn("rounded-md px-2 py-1 text-[10.5px] font-medium transition", act.cls)}
                              onClick={() => move(app, act.to)}
                              disabled={busyId === app.id}
                            >
                              {act.label}
                            </button>
                          ))}
                          <button
                            className="ml-auto text-[10.5px] text-slate-400 hover:text-slate-600"
                            onClick={() => toggle(app)}
                          >
                            {isOpen ? "收起" : "详情"}
                          </button>
                        </div>
                      </div>
                    );
                  })}

                  {list.length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-200 py-6 text-center text-[11px] text-slate-400">
                      暂无
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "amber" | "brand" }) {
  return (
    <div className="rounded-xl bg-white px-3 py-1.5 text-center ring-1 ring-slate-200/70">
      <div
        className={cn(
          "text-[16px] font-semibold leading-tight",
          tone === "amber" ? "text-amber-600" : tone === "brand" ? "text-brand-700" : "text-ink",
        )}
      >
        {value}
      </div>
      <div className="text-[10px] text-slate-400">{label}</div>
    </div>
  );
}
