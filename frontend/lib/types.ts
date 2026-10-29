// 与后端 app/schemas.py 一一对应（字段名保持一致，避免转换层）

export type Stage =
  | "NEW"
  | "PARSED"
  | "DIAGNOSED"
  | "CLARIFYING"
  | "READY_TO_REWRITE"
  | "OPTIMIZED"
  | "INTERVIEWING"
  | "REVIEWED";

export interface Star {
  situation: string;
  task: string;
  action: string;
  result: string;
}

export interface Bullet {
  id: string;
  original: string;
  optimized: string;
  star: Star | null;
  metrics: string[];
  changed: boolean;
}

export interface Experience {
  id: string;
  company: string;
  role: string;
  period: string;
  location: string;
  bullets: Bullet[];
}

export interface ProjectItem {
  id: string;
  name: string;
  role: string;
  period: string;
  bullets: Bullet[];
}

export interface Education {
  id: string;
  school: string;
  degree: string;
  major: string;
  period: string;
  detail: string;
}

export interface Basics {
  name: string;
  headline: string;
  phone: string;
  email: string;
  location: string;
  links: string[];
}

export interface ResumeDoc {
  basics: Basics;
  summary: Bullet;
  skills: Bullet;
  experiences: Experience[];
  projects: ProjectItem[];
  education: Education[];
  extras: string[];
}

export type MatchLevel = "strong" | "partial" | "missing";

export interface DimensionScore {
  name: string;
  score: number;
  comment: string;
}

export interface RequirementMatch {
  requirement: string;
  evidence: string;
  level: MatchLevel;
  suggestion: string;
}

export interface GapQuestion {
  id: string;
  topic: string;
  question: string;
  why: string;
  bullet_id: string;
  answered: boolean;
  answer: string;
}

export interface TemplateHit {
  id: string;
  title: string;
  snippet: string;
  score: number;
  source: string;
}

export interface Diagnosis {
  match_score: number;
  verdict: string;
  dimensions: DimensionScore[];
  requirement_matches: RequirementMatch[];
  missing_keywords: string[];
  strengths: string[];
  risks: string[];
  gap_questions: GapQuestion[];
  retrieved_templates: TemplateHit[];
}

export type QuestionKind = "behavioral" | "technical" | "situational" | "culture" | "pressure";

export interface InterviewQuestion {
  id: string;
  index: number;
  kind: QuestionKind;
  difficulty: "easy" | "medium" | "hard";
  question: string;
  intent: string;
  key_points: string[];
}

export interface AnswerFeedback {
  question_id: string;
  answer: string;
  score: number;
  verdict: string;
  scores: { name: string; score: number }[];
  strengths: string[];
  improvements: string[];
  reference_answer: string;
  missing_key_points: string[];
}

export interface InterviewReport {
  overall: number;
  level: string;
  by_dimension: { name: string; score: number }[];
  summary: string;
  advice: string[];
}

export interface SessionSummary {
  id: string;
  stage: Stage;
  job_id: string;
  file_name: string;
  pages: number;
  chars: number;
  jd: string;
  llm_mode: string;
  parse_meta: { scanned?: boolean; ocr_engine?: string; ocr_renderer?: string; method?: string };
  match_score: number;
  answered_gaps: number;
  total_gaps: number;
  interview_total: number;
  interview_answered: number;
  resume: ResumeDoc | null;
  diagnosis: Diagnosis | null;
  match_report?: MatchReport | null;
  questions: InterviewQuestion[];
  feedbacks: AnswerFeedback[];
  report: InterviewReport | null;
  messages: { role: string; content: string; created_at: string }[];
}

export interface UploadResult {
  session_id: string;
  stage: Stage;
  file_name: string;
  pages: number;
  chars: number;
  parse: {
    method: string;
    structure: string;
    scanned?: boolean;
    ocr_engine?: string;
    ocr_renderer?: string;
    warnings: string[];
  };
  resume: ResumeDoc;
  message: string;
}

export interface ChatMessage {
  id: string;
  role: "assistant" | "user" | "system";
  content: string;
  kind?: "text" | "feedback" | "report" | "warning";
  meta?: unknown;
  pending?: boolean;
}

// --------------------------------------------------------------------------- //
// Pro：用户 / 岗位 / 匹配 / 投递
// --------------------------------------------------------------------------- //
export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: number;
  last_login_at: number | null;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  city: string;
  salary: string;
  salary_min: number;
  salary_max: number;
  seniority: string;
  industry: string;
  tags: string[];
  skills: string[];
  jd_text?: string;
}

export interface MatchItem {
  job: Job;
  rank: number;
  score: number;
  reason: string;
  matched_skills: string[];
  missing_skills: string[];
}

export interface MatchResponse {
  session_id: string;
  items: MatchItem[];
  backend: string;
  pool_size: number;
  note: string;
}

export interface RadarItem {
  dimension: string;
  score: number;
  benchmark: number;
  comment: string;
}

export interface SkillGap {
  skill: string;
  importance: "high" | "medium" | "low";
  have: boolean;
  evidence: string;
  suggestion: string;
}

export interface MatchReport {
  job_id: string;
  match_score: number;
  verdict: string;
  radar: RadarItem[];
  skill_gap: SkillGap[];
  matched_skills: string[];
  missing_skills: string[];
  strengths: string[];
  risks: string[];
  requirement_matches: RequirementMatch[];
  gap_questions: GapQuestion[];
  job?: Job;
}

export type ApplicationStatus = "applied" | "interviewing" | "offer" | "rejected" | "withdrawn";

export interface Application {
  id: string;
  job_id: string;
  job_title: string;
  company: string;
  city: string;
  salary: string;
  status: ApplicationStatus;
  status_label: string;
  match_score: number;
  email_to: string;
  email_subject: string;
  mail_status: "pending" | "sent" | "failed" | "simulated";
  mail_error: string;
  attachment: string;
  note: string;
  created_at: number;
  updated_at: number;
}

export interface ApplicationSummary {
  total: number;
  applied: number;
  interviewing: number;
  offer: number;
  rejected: number;
  withdrawn: number;
  interview_rate: number;
}
