"use client";

import { useMemo } from "react";
import { cn } from "@/lib/cn";
import { diffChars } from "@/lib/diff";
import type { Bullet, ResumeDoc } from "@/lib/types";
import { Empty } from "./ui";

export function DiffView({ resume }: { resume: ResumeDoc | null }) {
  const stats = useMemo(() => {
    if (!resume) return { changed: 0, added: 0, removed: 0, total: 0 };
    let changed = 0;
    let added = 0;
    let removed = 0;
    const all: Bullet[] = [resume.summary, resume.skills, ...resume.experiences.flatMap((e) => e.bullets), ...resume.projects.flatMap((p) => p.bullets)];
    for (const b of all) {
      if (!b.original.trim()) continue;
      if (!b.optimized.trim() || b.optimized.trim() === b.original.trim()) continue;
      changed += 1;
      const parts = diffChars(b.original, b.optimized);
      for (const p of parts) {
        if (p.type === "add") added += [...p.text].length;
        if (p.type === "del") removed += [...p.text].length;
      }
    }
    return { changed, added, removed, total: all.filter((b) => b.original.trim()).length };
  }, [resume]);

  if (!resume) return <Empty title="还没有可对比的内容" hint="完成 STAR 重写后，这里会逐条标出改前（红）与改后（绿）。" />;

  const nothingYet = !resume.summary.optimized && !resume.skills.optimized && !resume.experiences.some((e) => e.bullets.some((b) => b.optimized));

  if (nothingYet) {
    return <Empty title="还没有改写结果" hint="回答完追问（或点「跳过」）后，AI 会用 STAR 法则逐条重写，这里就能看到红绿对比。" />;
  }

  return (
    <div className="scroll-thin h-full overflow-y-auto px-4 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-baseline gap-1">
          <span className="text-xl font-semibold text-slate-800">{stats.changed}</span>
          <span className="text-[11px] text-slate-400">处改写</span>
        </div>
        <span className="h-6 w-px bg-slate-200" />
        <div className="flex items-baseline gap-1 text-emerald-600">
          <span className="text-sm font-semibold">+{stats.added}</span>
          <span className="text-[11px] opacity-70">字</span>
        </div>
        <div className="flex items-baseline gap-1 text-rose-500">
          <span className="text-sm font-semibold">−{stats.removed}</span>
          <span className="text-[11px] opacity-70">字</span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[10.5px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-4 rounded-sm bg-rose-100" /> 删除
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-4 rounded-sm bg-emerald-100" /> 新增
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {(resume.summary.optimized || resume.skills.optimized) && (
          <Section label="个人简介与技能">
            {resume.summary.optimized && <DiffLine before={resume.summary.original} after={resume.summary.optimized} />}
            {resume.skills.optimized && <DiffLine before={resume.skills.original} after={resume.skills.optimized} />}
          </Section>
        )}

        {resume.experiences.map((exp) => (
          <Section key={exp.id} label={`${exp.company}${exp.role ? " · " + exp.role : ""}`} period={exp.period}>
            {exp.bullets.map((b) => (
              <DiffLine key={b.id} before={b.original} after={b.optimized} />
            ))}
          </Section>
        ))}

        {resume.projects.map((p) => (
          <Section key={p.id} label={p.name} period={p.period}>
            {p.bullets.map((b) => (
              <DiffLine key={b.id} before={b.original} after={b.optimized} />
            ))}
          </Section>
        ))}
      </div>
    </div>
  );
}

function Section({ label, period, children }: { label: string; period?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-3.5 py-2">
        <span className="text-[12.5px] font-semibold text-slate-700">{label}</span>
        {period && <span className="text-[10.5px] text-slate-400">{period}</span>}
      </div>
      <div className="space-y-2.5 px-3.5 py-3">{children}</div>
    </div>
  );
}

function DiffLine({ before, after }: { before: string; after: string }) {
  const unchanged = !after?.trim() || after.trim() === before.trim();

  if (unchanged) {
    return (
      <div className="flex gap-2 text-[12px] leading-[1.8] text-slate-400">
        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-300" />
        <span>{before}</span>
      </div>
    );
  }

  const parts = diffChars(before, after);
  // 只改了分隔符（逗号、·、空格）时不制造红绿噪音
  const removed = parts.filter((p) => p.type === "del").map((p) => p.text).join("");
  if (removed && /^[\s,，、·|/]+$/.test(removed)) {
    return (
      <div className="flex gap-2 text-[12px] leading-[1.8] text-slate-500">
        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-300" />
        <span>{after}</span>
      </div>
    );
  }

  // 改动过半（例如技能行重排）时，字符级 diff 会变成红绿噪点，改用上下两行更清楚
  const changedChars = parts
    .filter((p) => p.type !== "same")
    .reduce((n, p) => n + [...p.text].length, 0);
  if (changedChars > Math.max(before.length, after.length) * 0.55) {
    return (
      <div className="flex gap-2">
        <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-brand-400" />
        <div className="min-w-0 space-y-1">
          <p className="text-[12px] leading-[1.8] text-rose-500/80 line-through decoration-rose-300 decoration-1">
            {before}
          </p>
          <p className="text-[12.5px] leading-[1.85] font-medium text-emerald-700">{after}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-brand-400" />
      <p className="text-[12.5px] leading-[1.85] text-slate-700">
        {parts.map((p, i) =>
          p.type === "same" ? (
            <span key={i}>{p.text}</span>
          ) : p.type === "del" ? (
            <span key={i} className="text-rose-500/90 line-through decoration-rose-300 decoration-1">
              {p.text}
            </span>
          ) : (
            <span
              key={i}
              className={cn(
                "rounded-[2px] bg-emerald-50 px-0.5 font-medium text-emerald-700",
                /\d/.test(p.text) && "bg-emerald-100",
              )}
            >
              {p.text}
            </span>
          ),
        )}
      </p>
    </div>
  );
}
