"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { previewUrl } from "@/lib/api";
import { Empty } from "./ui";

export function ResumePreview({
  sid,
  version,
  hasResume,
}: {
  sid: string | null;
  version: number;
  hasResume: boolean;
}) {
  const [variant, setVariant] = useState<"optimized" | "original">("optimized");

  if (!sid || !hasResume) {
    return (
      <div className="h-full p-6">
        <Empty title="简历预览将出现在这里" hint="解析完成后可查看结构化排版，改写后会自动刷新为 STAR 优化版。" />
      </div>
    );
  }

  const src = previewUrl(sid, variant, version);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-slate-100 px-3 py-2">
        <div className="flex rounded-lg bg-slate-100 p-0.5">
          {(["optimized", "original"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVariant(v)}
              className={cn(
                "rounded-md px-2.5 py-1 text-[11.5px] font-medium transition",
                variant === v ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700",
              )}
            >
              {v === "optimized" ? "优化版" : "原始版"}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-slate-500 hover:text-brand-700"
          >
            新窗口打开 ↗
          </a>
        </div>
      </div>
      <div className="min-h-0 flex-1 bg-slate-100/70 p-3">
        <iframe
          key={src}
          src={src}
          title="简历预览"
          className="h-full w-full rounded-lg border border-slate-200 bg-white shadow-sm"
        />
      </div>
    </div>
  );
}
