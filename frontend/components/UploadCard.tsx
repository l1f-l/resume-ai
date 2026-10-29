"use client";

import { useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./ui";

const SAMPLE_JD = `用户增长产品经理（高级）

岗位职责：
1. 负责 App 用户增长策略制定与落地，对 DAU、留存率、转化率核心指标负责；
2. 搭建用户分层与生命周期运营体系，设计自动化触达策略；
3. 主导 A/B 实验设计与归因分析，持续优化漏斗转化率；
4. 协同投放团队优化 ROI 与获客成本，控制 CAC；
5. 输出增长方法论与 SOP，赋能业务团队。

任职要求：
1. 本科及以上学历，5 年以上互联网产品经验，其中 3 年以上用户增长方向；
2. 精通 SQL 与数据分析，能独立完成漏斗分析、AB 实验与指标体系建设；
3. 熟悉私域、社群运营与内容运营者优先；
4. 有从 0 到 1 搭建增长体系经验者优先；
5. 优秀的跨部门协作与项目管理能力，能推动多团队按期交付。`;

export function UploadCard({
  onSubmit,
  busy,
  error,
}: {
  onSubmit: (file: File, jd: string) => void;
  busy: boolean;
  error: string | null;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [jd, setJd] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f?: File | null) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setFile(null);
      return;
    }
    setFile(f);
  };

  const ready = !!file && jd.trim().length > 10 && !busy;

  return (
    <div className="card mx-auto w-full max-w-2xl overflow-hidden">
      <div className="border-b border-slate-100 bg-gradient-to-br from-brand-50/70 to-white px-6 py-5">
        <h2 className="text-[17px] font-semibold tracking-tight">上传简历，开始一轮真实的面试准备</h2>
        <p className="mt-1 text-[12.5px] leading-relaxed text-slate-500">
          AI 会先做「简历 × JD」匹配诊断，揪出缺失的量化数据并逐条追问，再用 STAR 法则重写，最后进入模拟面试。
        </p>
      </div>

      <div className="space-y-5 px-6 py-5">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-[13px] font-medium text-slate-700">
              1. 简历 PDF <span className="text-rose-500">*</span>
            </label>
            <span className="text-[11px] text-slate-400">支持可复制文字的 PDF，≤ 10MB</span>
          </div>
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files?.[0]);
            }}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed px-4 py-3.5 transition",
              dragging
                ? "border-brand-400 bg-brand-50/60"
                : file
                  ? "border-brand-200 bg-brand-50/30"
                  : "border-slate-200 bg-slate-50/60 hover:border-slate-300 hover:bg-slate-50",
            )}
          >
            <div
              className={cn(
                "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-sm",
                file ? "bg-brand-600 text-white" : "bg-white text-slate-400 shadow-sm",
              )}
            >
              {file ? "PDF" : "＋"}
            </div>
            <div className="min-w-0 flex-1">
              {file ? (
                <>
                  <div className="truncate text-[13px] font-medium text-slate-800">{file.name}</div>
                  <div className="text-[11px] text-slate-400">{(file.size / 1024).toFixed(0)} KB · 点击可重新选择</div>
                </>
              ) : (
                <>
                  <div className="text-[13px] font-medium text-slate-600">点击选择，或把 PDF 拖到这里</div>
                  <div className="text-[11px] text-slate-400">扫描件/图片型 PDF 无法提取文字</div>
                </>
              )}
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-[13px] font-medium text-slate-700">
              2. 目标岗位 JD <span className="text-rose-500">*</span>
            </label>
            <button
              type="button"
              className="text-[11px] font-medium text-brand-600 hover:text-brand-700"
              onClick={() => setJd(SAMPLE_JD)}
            >
              填入示例 JD
            </button>
          </div>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={8}
            placeholder="把招聘网站上的岗位描述整段粘进来——职责、要求、加分项都保留，诊断会更准。"
            className="w-full resize-none rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-[13px] leading-relaxed
                       text-slate-700 outline-none transition placeholder:text-slate-400
                       focus:border-brand-400 focus:ring-4 focus:ring-brand-50"
          />
          <div className="mt-1 flex justify-between text-[11px] text-slate-400">
            <span>{jd.trim().length} 字</span>
            <span>建议 ≥ 150 字，含具体技能与年限</span>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">{error}</div>
        )}

        <button
          className="btn-primary w-full !py-2.5"
          disabled={!ready}
          onClick={() => file && onSubmit(file, jd.trim())}
        >
          {busy ? (
            <>
              <Spinner className="!border-white/40 !border-t-white" /> 正在解析 PDF…
            </>
          ) : (
            "开始诊断 →"
          )}
        </button>

        <p className="text-center text-[11px] leading-relaxed text-slate-400">
          简历仅用于本次会话的即时分析，不落库；会话数据保存在内存中，重启后端即清空。
        </p>
      </div>
    </div>
  );
}
