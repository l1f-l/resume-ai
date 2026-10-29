"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ApplyDialog } from "@/components/ApplyDialog";
import { ChatPanel } from "@/components/ChatPanel";
import { DiagnosisPanel } from "@/components/DiagnosisPanel";
import { DiffView } from "@/components/DiffView";
import { Header } from "@/components/Header";
import { InterviewPanel } from "@/components/InterviewPanel";
import { MatchPanel } from "@/components/MatchPanel";
import { RecommendedJobs } from "@/components/RecommendedJobs";
import { ResumePreview } from "@/components/ResumePreview";
import { Spinner } from "@/components/ui";
import {
  API_BASE,
  exportUrl,
  getSession,
  health,
  jobDetail,
  recommendJobs,
  resetLlm,
  streamSSE,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { STAGE_LABEL } from "@/lib/stage";
import type {
  AnswerFeedback,
  ChatMessage,
  Diagnosis,
  InterviewQuestion,
  InterviewReport,
  Job,
  MatchItem,
  MatchReport,
  ResumeDoc,
  SessionSummary,
  Stage,
} from "@/lib/types";

type Tab = "preview" | "diff" | "match" | "jobs" | "interview";

const TABS: { key: Tab; label: string }[] = [
  { key: "preview", label: "简历预览" },
  { key: "diff", label: "改前改后" },
  { key: "match", label: "匹配报告" },
  { key: "jobs", label: "推荐岗位" },
  { key: "interview", label: "模拟面试" },
];

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

/** 静态导出不支持动态路由段，工作台改为 /workspace/?sid=xxx */
export default function WorkspacePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <WorkspaceInner />
    </Suspense>
  );
}

function WorkspaceInner() {
  const params = useSearchParams();
  const router = useRouter();
  const sid = params.get("sid") ?? "";

  const [stage, setStage] = useState<Stage>("NEW");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [resume, setResume] = useState<ResumeDoc | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [report, setReport] = useState<MatchReport | null>(null);
  const [jobInfo, setJobInfo] = useState<Job | null>(null);
  const [jobId, setJobId] = useState("");
  const [questions, setQuestions] = useState<InterviewQuestion[]>([]);
  const [feedbacks, setFeedbacks] = useState<AnswerFeedback[]>([]);
  const [interviewReport, setInterviewReport] = useState<InterviewReport | null>(null);
  const [matchItems, setMatchItems] = useState<MatchItem[]>([]);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>("preview");
  const [version, setVersion] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [phase, setPhase] = useState("");
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [llm, setLlm] = useState({ isMock: true, label: "内置演示引擎", degraded: false, reason: "" });
  const [scanned, setScanned] = useState(false);
  const [ocrEngine, setOcrEngine] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [jd, setJd] = useState("");
  const [fileName, setFileName] = useState("");
  const [currentQ, setCurrentQ] = useState(0);
  const [applyOpen, setApplyOpen] = useState(false);

  const msgRef = useRef<string | null>(null);
  const autoranRef = useRef(false);

  const syncHealth = useCallback(async () => {
    try {
      const h = await health();
      setOnline(true);
      setLlm({
        isMock: h.llm_mode === "mock",
        label: h.llm_label,
        degraded: !!h.llm?.degraded,
        reason: h.llm?.reason || "",
      });
    } catch {
      setOnline(false);
    }
  }, []);

  const syncSession = useCallback((s: SessionSummary) => {
    setStage(s.stage);
    if (s.resume) setResume(s.resume);
    setDiagnosis(s.diagnosis);
    if (s.match_report) setReport(s.match_report);
    setQuestions(s.questions ?? []);
    setFeedbacks(s.feedbacks ?? []);
    setInterviewReport(s.report ?? null);
    if (s.job_id) setJobId(s.job_id);
    if (s.questions?.length) {
      const answered = s.feedbacks?.length ?? 0;
      setCurrentQ(Math.min(answered, s.questions.length - 1));
    }
  }, []);

  // ------------------------------------------------------------------ //
  const pushMessage = useCallback((m: Omit<ChatMessage, "id"> & { id?: string }) => {
    const id = m.id ?? uid();
    setMessages((prev) => [...prev, { ...m, id }]);
    return id;
  }, []);

  const appendToken = useCallback((id: string, text: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, content: m.content + text, pending: true } : m)),
    );
  }, []);

  const finalize = useCallback(() => {
    setMessages((prev) => prev.filter((m) => m.content.trim() || m.kind === "feedback"));
    setMessages((prev) => prev.map((m) => (m.pending ? { ...m, pending: false } : m)));
  }, []);

  /** 统一的 SSE 消费循环：把事件映射到 UI 状态 */
  const consume = useCallback(
    async (url: string, body?: unknown) => {
      setStreaming(true);
      setPhase("");
      let msgId = msgRef.current;
      try {
        for await (const { event, data } of streamSSE(url, body)) {
          switch (event) {
            case "phase":
              setPhase(data.label ?? "");
              break;
            case "token": {
              if (!msgId) {
                msgId = pushMessage({ role: "assistant", content: "", pending: true });
                msgRef.current = msgId;
              }
              appendToken(msgId, data.text ?? "");
              break;
            }
            case "diagnosis":
              setDiagnosis(data as Diagnosis);
              break;
            case "match_report": {
              const rep = data as MatchReport;
              setReport(rep);
              if (rep.job) setJobInfo(rep.job);
              setTab("match");
              break;
            }
            case "gaps":
              setDiagnosis((prev) =>
                prev ? { ...prev, gap_questions: data.gaps as Diagnosis["gap_questions"] } : prev,
              );
              break;
            case "gap":
              setCurrentQ(0);
              break;
            case "rewrite":
              setVersion((v) => v + 1);
              setTab("diff");
              break;
            case "resume":
              setResume(data.resume as ResumeDoc);
              setVersion((v) => v + 1);
              break;
            case "questions":
              setQuestions(data.questions as InterviewQuestion[]);
              setCurrentQ(0);
              setTab("interview");
              setInterviewReport(null);
              break;
            case "question":
              if (data.question?.index) setCurrentQ(data.question.index - 1);
              setTab("interview");
              break;
            case "feedback": {
              const fb = data as AnswerFeedback;
              if (msgId) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === msgId ? { ...m, kind: "feedback", meta: fb, pending: false } : m,
                  ),
                );
              }
              setFeedbacks((prev) => [...prev, fb]);
              msgId = null;
              msgRef.current = null;
              break;
            }
            case "report":
              setInterviewReport(data as InterviewReport);
              setTab("interview");
              break;
            case "state":
              setStage(data.stage as Stage);
              break;
            case "session":
              syncSession(data as SessionSummary);
              break;
            case "warning":
              pushMessage({ role: "system", content: data.message });
              break;
            case "error":
              throw new Error(data.message || "服务端处理失败");
            default:
              break;
          }
        }
      } catch (err) {
        pushMessage({
          role: "system",
          content: err instanceof Error ? err.message : "网络异常，请重试",
        });
      } finally {
        finalize();
        msgRef.current = null;
        setStreaming(false);
        setPhase("");
      }
    },
    [appendToken, finalize, pushMessage, syncSession],
  );

  // ------------------------------------------------------------------ //
  const loadMatches = useCallback(
    async (silent = false) => {
      if (!sid) return;
      if (!silent) setMatchLoading(true);
      setMatchError(null);
      try {
        const res = await recommendJobs(sid);
        setMatchItems(res.items);
        if (res.note) setMatchError(res.note);
      } catch (err) {
        setMatchError(err instanceof Error ? err.message : "推荐失败");
      } finally {
        setMatchLoading(false);
      }
    },
    [sid],
  );

  const runMatch = useCallback(
    async (targetJobId: string) => {
      setJobId(targetJobId);
      setTab("match");
      await consume(`/api/sessions/${sid}/match/${targetJobId}`);
    },
    [consume, sid],
  );

  // 初始加载
  useEffect(() => {
    if (!sid) return;
    void syncHealth();
    getSession(sid)
      .then(async (s) => {
        setFileName(s.file_name);
        setJd(s.jd);
        setStage(s.stage);
        setResume(s.resume);
        setDiagnosis(s.diagnosis);
        if (s.match_report) setReport(s.match_report);
        if (s.job_id) setJobId(s.job_id);
        setQuestions(s.questions ?? []);
        setFeedbacks(s.feedbacks ?? []);
        setInterviewReport(s.report ?? null);
        setScanned(!!s.parse_meta?.scanned);
        setOcrEngine(s.parse_meta?.ocr_engine ?? "");
        setMessages(
          (s.messages ?? []).map((m, i) => ({
            id: `restored-${i}`,
            role: m.role as ChatMessage["role"],
            content: m.content,
          })),
        );
        setVersion((v) => v + 1);

        if (s.stage === "INTERVIEWING" || s.stage === "REVIEWED") setTab("interview");
        else if (s.stage === "OPTIMIZED") setTab("diff");
        else if (s.match_report) setTab("match");
        else if (s.diagnosis) setTab("match");

        if (s.job_id || s.stage === "PARSED") {
          // 推荐结果不落 matched/missing 明细，直接重算一次最稳（本地检索为主，成本低）
          void loadMatches();
        }
        if (s.job_id) {
          void jobDetail(s.job_id).then(setJobInfo).catch(() => undefined);
        }

        // 从岗位详情页带 ?job= 进来：直接生成该岗位的匹配报告
        const qs = new URLSearchParams(window.location.search);
        const target = qs.get("job") || (qs.get("autorun") === "1" ? s.job_id : "");
        if (target && s.stage === "PARSED" && !autoranRef.current) {
          autoranRef.current = true;
          void runMatch(target);
        } else if (!s.job_id && s.stage === "PARSED" && !autoranRef.current) {
          // 手填 JD 模式：沿用原有流程，上传后自动做一次匹配诊断
          autoranRef.current = true;
          void consume(`/api/sessions/${sid}/analyze`);
        }
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [sid, runMatch, syncHealth]);

  // ------------------------------------------------------------------ //
  const handleSend = async (text: string) => {
    if (!sid || streaming) return;
    pushMessage({ role: "user", content: text });
    msgRef.current = null;
    await consume(`/api/sessions/${sid}/chat`, { message: text });
  };

  const startInterview = async () => {
    if (!sid || streaming) return;
    const id = uid();
    pushMessage({ id, role: "assistant", content: "", pending: true });
    msgRef.current = id;
    await consume(`/api/sessions/${sid}/interview/start`);
  };

  const reconnect = async () => {
    try {
      await resetLlm();
      await syncHealth();
    } catch {
      /* 忽略：下一次请求会再次尝试 */
    }
  };

  const canChat =
    !!sid &&
    !streaming &&
    ["DIAGNOSED", "CLARIFYING", "OPTIMIZED", "REVIEWED", "INTERVIEWING"].includes(stage);

  const canApply = ["OPTIMIZED", "INTERVIEWING", "REVIEWED"].includes(stage);

  const footerHint = (() => {
    if (stage === "CLARIFYING" || stage === "DIAGNOSED") {
      return (
        <button
          className="chip bg-slate-100 text-slate-600 hover:bg-slate-200"
          onClick={() => handleSend("跳过")}
          disabled={streaming}
        >
          跳过这条，先按现有信息改写 →
        </button>
      );
    }
    if (stage === "OPTIMIZED") {
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            className="chip bg-brand-600 text-white hover:bg-brand-700"
            onClick={startInterview}
            disabled={streaming}
          >
            🎙️ 开始模拟面试
          </button>
          {["再精简一点", "加强量化表达"].map((t) => (
            <button
              key={t}
              className="chip bg-slate-100 text-slate-600 hover:bg-slate-200"
              onClick={() => handleSend(t)}
              disabled={streaming}
            >
              {t}
            </button>
          ))}
        </div>
      );
    }
    if (stage === "REVIEWED") {
      return (
        <button
          className="chip bg-slate-100 text-slate-600 hover:bg-slate-200"
          onClick={startInterview}
          disabled={streaming}
        >
          重新来一轮面试 →
        </button>
      );
    }
    return null;
  })();

  // ------------------------------------------------------------------ //
  if (loading) {
    return (
      <div className="grid h-screen place-items-center">
        <div className="flex items-center gap-2 text-[12.5px] text-slate-400">
          <Spinner /> 正在恢复会话…
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="grid h-screen place-items-center px-6">
        <div className="text-center">
          <div className="text-[15px] font-medium text-slate-700">会话不存在或无权访问</div>
          <p className="mt-1 text-[12px] text-slate-400">
            可能已被删除，或它属于其他账号。
          </p>
          <button className="btn-primary mt-4 !py-1.5 text-[12px]" onClick={() => router.push("/")}>
            回到总览
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen min-h-0 flex-col">
      <Header
        stage={stage}
        llmLabel={llm.label}
        isMock={llm.isMock}
        onReset={() => router.push("/")}
        hasSession
        extra={
          <button
            className={cn(
              "btn !px-3 !py-1.5 text-[12px]",
              canApply && jobInfo
                ? "bg-brand-600 text-white hover:bg-brand-700"
                : "cursor-not-allowed bg-slate-100 text-slate-400",
            )}
            disabled={!canApply || !jobInfo || streaming}
            onClick={() => setApplyOpen(true)}
            title={
              !jobInfo
                ? "请先在「推荐岗位」里选一个岗位"
                : canApply
                  ? "用优化后的简历投递该岗位"
                  : "完成简历优化后才能投递"
            }
          >
            ✉️ 投递{jobInfo ? ` · ${jobInfo.company}` : ""}
          </button>
        }
      />

      {online === false && (
        <div className="border-b border-amber-100 bg-amber-50 px-5 py-2 text-center text-[12px] text-amber-800">
          后端未连接（{API_BASE}）。请先启动
          <code className="mx-1 rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[11px]">
            uvicorn app.main:app --port 8001
          </code>
          再刷新页面。
        </div>
      )}

      {llm.degraded && (
        <div className="border-b border-amber-100 bg-amber-50 px-5 py-2 text-center text-[12px] text-amber-800">
          DeepSeek 调用失败，已自动降级到本地演练引擎
          {llm.reason ? `（${llm.reason}）` : ""}，流程不受影响。
          <button
            className="ml-2 font-medium underline underline-offset-2 hover:text-amber-900"
            onClick={reconnect}
          >
            重试连接
          </button>
        </div>
      )}

      <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(340px,38%)_1fr]">
        {/* 左：聊天 */}
        <section className="card flex min-h-0 flex-col overflow-hidden">
          <div className="shrink-0 border-b border-slate-100 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13px] font-medium text-slate-800">{fileName}</span>
              <span
                className={cn(
                  "chip",
                  stage === "OPTIMIZED" || stage === "REVIEWED"
                    ? "bg-emerald-50 text-emerald-700"
                    : stage === "INTERVIEWING"
                      ? "bg-violet-50 text-violet-700"
                      : "bg-brand-50 text-brand-700",
                )}
              >
                {STAGE_LABEL[stage]}
              </span>
              {scanned && (
                <span
                  className="chip bg-violet-50 text-violet-700 ring-1 ring-violet-100"
                  title="扫描件已通过 OCR 识别"
                >
                  OCR{ocrEngine ? ` · ${ocrEngine}` : ""}
                </span>
              )}
              {jobInfo && (
                <span className="chip bg-slate-100 text-slate-600" title="当前目标岗位">
                  {jobInfo.title}
                </span>
              )}
              {streaming && <Spinner className="ml-auto !h-3 !w-3" />}
            </div>
            <details className="group mt-0.5">
              <summary className="cursor-pointer list-none text-[10.5px] text-slate-400 hover:text-slate-600">
                目标 JD · 点击展开 ▾
              </summary>
              <p className="scroll-thin mt-1 max-h-28 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] leading-relaxed text-slate-500">
                {jd}
              </p>
            </details>
          </div>
          <ChatPanel
            messages={messages}
            streaming={streaming}
            phase={phase}
            stage={stage}
            disabled={!canChat}
            onSend={handleSend}
            footerHint={footerHint}
          />
        </section>

        {/* 右：多视图 */}
        <section className="card flex min-h-0 flex-col overflow-hidden">
          <div className="flex shrink-0 items-center gap-1 border-b border-slate-100 px-2">
            {TABS.map((t) => {
              const badge =
                t.key === "match"
                  ? diagnosis?.gap_questions.filter((g) => !g.answered).length
                  : t.key === "interview"
                    ? questions.length - feedbacks.length
                    : t.key === "jobs"
                      ? matchItems.length
                      : 0;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={cn("tab", tab === t.key && "tab-active")}
                >
                  {t.label}
                  {!!badge && badge > 0 && (
                    <span className="rounded-full bg-rose-100 px-1.5 text-[10px] font-semibold text-rose-600">
                      {badge}
                    </span>
                  )}
                  {tab === t.key && (
                    <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-600" />
                  )}
                </button>
              );
            })}

            <div className="ml-auto flex items-center gap-1.5 pr-1">
              <ExportButton sid={sid} stage={stage} format="html" label="HTML" />
              <ExportButton sid={sid} stage={stage} format="pdf" label="PDF" />
              <ExportButton sid={sid} stage={stage} format="html" variant="diff" label="对比版" subtle />
            </div>
          </div>

          <div className="min-h-0 flex-1">
            {tab === "preview" && (
              <ResumePreview sid={sid} version={version} hasResume={!!resume} />
            )}
            {tab === "diff" && <DiffView resume={resume} />}
            {tab === "match" &&
              (report ? (
                <MatchPanel
                  report={report}
                  onPickJob={() => {
                    setTab("jobs");
                    if (!matchItems.length) void loadMatches();
                  }}
                />
              ) : diagnosis ? (
                <DiagnosisPanel diagnosis={diagnosis} />
              ) : (
                <MatchPanel
                  report={null}
                  onPickJob={() => {
                    setTab("jobs");
                    if (!matchItems.length) void loadMatches();
                  }}
                />
              ))}
            {tab === "jobs" && (
              <RecommendedJobs
                items={matchItems}
                loading={matchLoading || streaming}
                error={matchError}
                activeJobId={jobId}
                onPick={(id) => void runMatch(id)}
                onRefresh={() => void loadMatches()}
              />
            )}
            {tab === "interview" && (
              <InterviewPanel
                questions={questions}
                feedbacks={feedbacks}
                report={interviewReport}
                currentIndex={currentQ}
                onStart={startInterview}
                busy={streaming}
                canStart={stage === "OPTIMIZED" || stage === "REVIEWED" || stage === "INTERVIEWING"}
              />
            )}
          </div>
        </section>
      </main>

      <ApplyDialog
        open={applyOpen}
        job={jobInfo}
        sessionId={sid}
        matchScore={report?.match_score}
        onClose={() => setApplyOpen(false)}
      />
    </div>
  );
}

function ExportButton({
  sid,
  stage,
  format,
  label,
  variant = "optimized",
  subtle,
}: {
  sid: string | null;
  stage: Stage;
  format: "html" | "pdf";
  label: string;
  variant?: string;
  subtle?: boolean;
}) {
  const ready =
    !!sid &&
    ["OPTIMIZED", "INTERVIEWING", "REVIEWED"].includes(stage) &&
    !(format === "pdf" && variant === "diff");
  return (
    <a
      href={ready && sid ? exportUrl(sid, format, variant) : undefined}
      download
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition",
        ready
          ? subtle
            ? "border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700"
            : "border-brand-200 bg-brand-50 text-brand-700 hover:bg-brand-100"
          : "pointer-events-none border-slate-100 text-slate-300",
      )}
      title={ready ? `导出 ${label}` : "完成简历优化后可导出"}
    >
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
        <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </a>
  );
}
