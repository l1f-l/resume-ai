"use client";

import type { MatchLevel, QuestionKind } from "@/lib/types";
import { cn } from "@/lib/cn";

export function ScoreRing({
  value,
  size = 108,
  label = "匹配度",
  stroke = 9,
}: {
  value: number;
  size?: number;
  label?: string;
  stroke?: number;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, value));
  const color = pct >= 80 ? "#0f9d76" : pct >= 65 ? "#d97706" : "#dc2626";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1f5" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${(pct / 100) * c} ${c}`}
          style={{ transition: "stroke-dasharray .8s ease, stroke .3s" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[26px] font-semibold leading-none tracking-tight" style={{ color }}>
          {pct}
        </span>
        <span className="mt-1 text-[10px] text-slate-400">{label}</span>
      </div>
    </div>
  );
}

export function MeterBar({ value, tone = "brand" }: { value: number; tone?: "brand" | "amber" | "rose" }) {
  const color =
    tone === "rose"
      ? "bg-rose-500"
      : tone === "amber"
        ? "bg-amber-500"
        : value >= 80
          ? "bg-emerald-500"
          : value >= 60
            ? "bg-amber-500"
            : "bg-rose-500";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <div
        className={cn("h-full rounded-full transition-all duration-700", color)}
        style={{ width: `${Math.max(3, Math.min(100, value))}%` }}
      />
    </div>
  );
}

const LEVEL_STYLE: Record<MatchLevel, { text: string; cls: string; label: string }> = {
  strong: { text: "匹配", cls: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100", label: "强匹配" },
  partial: { text: "部分", cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-100", label: "部分匹配" },
  missing: { text: "缺失", cls: "bg-rose-50 text-rose-700 ring-1 ring-rose-100", label: "缺失" },
};

export function LevelChip({ level }: { level: MatchLevel }) {
  const s = LEVEL_STYLE[level] ?? LEVEL_STYLE.partial;
  return <span className={cn("chip", s.cls)}>{s.label}</span>;
}

const KIND_LABEL: Record<QuestionKind, { label: string; cls: string }> = {
  behavioral: { label: "行为面", cls: "bg-sky-50 text-sky-700 ring-1 ring-sky-100" },
  technical: { label: "技术面", cls: "bg-violet-50 text-violet-700 ring-1 ring-violet-100" },
  situational: { label: "情景面", cls: "bg-teal-50 text-teal-700 ring-1 ring-teal-100" },
  culture: { label: "文化面", cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-100" },
  pressure: { label: "压力面", cls: "bg-rose-50 text-rose-700 ring-1 ring-rose-100" },
};

export function KindChip({ kind, difficulty }: { kind: QuestionKind; difficulty?: string }) {
  const k = KIND_LABEL[kind] ?? KIND_LABEL.behavioral;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("chip", k.cls)}>{k.label}</span>
      {difficulty && (
        <span className="chip bg-slate-100 text-slate-500">
          {difficulty === "hard" ? "困难" : difficulty === "easy" ? "简单" : "中等"}
        </span>
      )}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600",
        className,
      )}
    />
  );
}

export function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-2 flex items-baseline justify-between">
      <h3 className="text-[13px] font-semibold text-slate-700">{children}</h3>
      {hint && <span className="text-[11px] text-slate-400">{hint}</span>}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 py-10 text-center">
      <span className="text-2xl">🗂️</span>
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {hint && <p className="max-w-[240px] text-xs leading-relaxed text-slate-400">{hint}</p>}
    </div>
  );
}
