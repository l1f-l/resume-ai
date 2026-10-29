"use client";

import { cn } from "@/lib/cn";
import type { Stage } from "@/lib/types";

const STEPS: { key: string; label: string; stages: Stage[] }[] = [
  { key: "parse", label: "解析简历", stages: ["PARSED"] },
  { key: "diagnose", label: "匹配诊断", stages: ["DIAGNOSED"] },
  { key: "clarify", label: "追问量化", stages: ["CLARIFYING", "READY_TO_REWRITE"] },
  { key: "optimize", label: "STAR 重写", stages: ["OPTIMIZED"] },
  { key: "interview", label: "模拟面试", stages: ["INTERVIEWING", "REVIEWED"] },
];

const STAGE_STEP: Record<Stage, number> = {
  NEW: -1,
  PARSED: 0,
  DIAGNOSED: 1,
  CLARIFYING: 2,
  READY_TO_REWRITE: 2,
  OPTIMIZED: 3,
  INTERVIEWING: 4,
  REVIEWED: 4,
};

function stepIndex(stage: Stage): number {
  return STAGE_STEP[stage] ?? -1;
}

export function Header({
  stage,
  llmLabel,
  isMock,
  onReset,
  hasSession,
  extra,
}: {
  stage: Stage;
  llmLabel: string;
  isMock: boolean;
  onReset: () => void;
  hasSession: boolean;
  extra?: React.ReactNode;
}) {
  const active = stepIndex(stage);

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-6 px-5">
        <a href="/" className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-[15px] font-bold text-white shadow-sm">
            R
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight">ResumePilot</div>
            <div className="text-[10px] font-medium tracking-wide text-brand-600">PRO · 全链路</div>
          </div>
        </a>

        <nav className="hidden flex-1 items-center gap-1 md:flex">
          {STEPS.map((s, i) => {
            const done = active > i || stage === "REVIEWED";
            const current = active === i;
            return (
              <div key={s.key} className="flex items-center">
                <div
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] transition",
                    current && "bg-brand-50 font-medium text-brand-700",
                    done && "text-slate-500",
                    !current && !done && "text-slate-300",
                  )}
                >
                  <span
                    className={cn(
                      "grid h-4 w-4 place-items-center rounded-full text-[9px] font-semibold",
                      current && "bg-brand-600 text-white",
                      done && "bg-brand-100 text-brand-700",
                      !current && !done && "bg-slate-100 text-slate-400",
                    )}
                  >
                    {done ? "✓" : i + 1}
                  </span>
                  {s.label}
                </div>
                {i < STEPS.length - 1 && (
                  <span className={cn("mx-0.5 h-px w-5", done ? "bg-brand-200" : "bg-slate-200")} />
                )}
              </div>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <span
            className={cn(
              "chip",
              isMock
                ? "bg-amber-50 text-amber-700 ring-1 ring-amber-100"
                : "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100",
            )}
            title={isMock ? "未配置 DEEPSEEK_API_KEY，使用内置演示引擎（同样支持全流程）" : "已连接 DeepSeek"}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", isMock ? "bg-amber-500" : "bg-emerald-500")} />
            {isMock ? "演示引擎" : "DeepSeek"}
          </span>
          {extra}
          <a href="/" className="btn-ghost !px-2.5 !py-1.5 text-[12px]">
            ← 总览
          </a>
          {hasSession && (
            <button className="btn-ghost !px-2.5 !py-1.5 text-[12px]" onClick={onReset}>
              换份简历
            </button>
          )}
        </div>
      </div>
      <div className="mx-auto max-w-[1600px] px-5 pb-1.5 text-[10px] text-slate-400 md:hidden">
        {llmLabel}
      </div>
    </header>
  );
}
