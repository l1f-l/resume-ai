import type { Stage } from "./types";

export const STAGE_LABEL: Record<Stage, string> = {
  NEW: "待上传",
  PARSED: "已解析",
  DIAGNOSED: "已诊断",
  CLARIFYING: "追问中",
  READY_TO_REWRITE: "待重写",
  OPTIMIZED: "已优化",
  INTERVIEWING: "面试中",
  REVIEWED: "已复盘",
};

export const STAGE_TONE: Record<Stage, string> = {
  NEW: "bg-slate-100 text-slate-500",
  PARSED: "bg-sky-50 text-sky-700",
  DIAGNOSED: "bg-brand-50 text-brand-700",
  CLARIFYING: "bg-amber-50 text-amber-700",
  READY_TO_REWRITE: "bg-amber-50 text-amber-700",
  OPTIMIZED: "bg-emerald-50 text-emerald-700",
  INTERVIEWING: "bg-violet-50 text-violet-700",
  REVIEWED: "bg-emerald-50 text-emerald-700",
};

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage as Stage] ?? stage;
}

export function relativeTime(ts?: number | null): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
  return new Date(ts * 1000).toLocaleDateString("zh-CN");
}
