# ResumePilot Pro · 智能求职全链路平台

多用户求职平台：**上传简历 → 岗位池语义匹配 → 匹配度雷达报告 → STAR 重写 → 模拟面试 → 投递追踪**。

相比 v1「单机简历工具」，Pro 版补齐了用户体系、岗位数据池、双向匹配与投递闭环。

**[在线体验](https://resumepilot.app.workbuddy.host/?sharecode=QWFZWUI5ET)** · 打开即用，注册即可上传简历（无需配置，LLM 已接入）

---

## 1. 功能全景

| 能力 | 说明 |
|---|---|
| 多用户体系 | JWT（HS256）注册登录，简历/优化记录/投递全部按 `user_id` 强绑定，跨账号访问一律 404 |
| 简历解析 | pdfplumber → PyPDF2 兜底 → 扫描件走 RapidOCR（纯 pip，无需 Tesseract/poppler） |
| 岗位数据池 | 50 条模拟大厂岗位（25 个职位原型 × 中级/高级），SQLite 为准 + Chroma `jobs_hash384` 索引 |
| 简历 → Top3 | 简历特征 → Chroma 召回 12 → 规则预排 6 → DeepSeek 精排 3，**推荐结果 100% 来自岗位池** |
| 岗位 → 匹配报告 | 6 维雷达图（候选人 vs 岗位基准）+ 技能缺口清单 + 优势/风险 + 追问清单 |
| STAR 重写 | 追问缺失的量化数据 → 按 STAR 重写 + 强动词 + 指标抽取 → 红绿 diff 对比 |
| 模拟面试 | 5 题（行为/技术/情景/文化/压力），逐题打分 + 参考回答 + 复盘报告 |
| 投递闭环 | 生成求职信 → 附优化版 PDF → SMTP 发到注册邮箱 → `applications` 记录状态流转 |
| 进度看板 | 已投递 / 已邀面 / 已结束三列，每次流转写时间轴，漏斗与邀面率实时统计 |
| 导出 | 单文件 HTML / PDF（优化版、原始版、对比版） |

**技术栈**：Next.js 15 (App Router) + Tailwind · FastAPI + Pydantic v2 · DeepSeek（SSE 流式）· Chroma · SQLite(WAL) · PyJWT

---

## 2. 目录结构

```
resume-ai/
├── docs/ResumePilot-Pro-技术方案.md    # 重构方案（表结构/路由/算法/分阶段计划）
├── backend/
│   ├── app/
│   │   ├── main.py              # 入口 + lifespan（启动时幂等导入岗位池）
│   │   ├── api.py               # 简历/诊断/追问/面试/导出路由 + 子路由挂载
│   │   ├── security.py          # PBKDF2 密码哈希 + JWT 签发校验 + 依赖注入
│   │   ├── users.py             # 用户仓储
│   │   ├── jobs.py              # 岗位仓储 + Chroma 索引 + 语义检索
│   │   ├── jobs_seed.py         # 50 条岗位种子（25 原型 × 2 职级）
│   │   ├── matches.py           # 匹配记录与报告快照
│   │   ├── applications.py      # 投递记录 + 状态机 + 时间轴
│   │   ├── mailer.py            # SMTP 发送 / 无凭据时写 .eml 存档
│   │   ├── deps.py              # 会话归属依赖（越权即 404）
│   │   ├── sse.py               # SSE 帧协议 + 落盘收尾
│   │   ├── runtime.py           # LLM 单例（熔断状态全局共享）
│   │   ├── routers/             # auth / jobs / matching / applications
│   │   ├── services/
│   │   │   ├── matching.py      # 三路召回打分 + 白名单校验 + 报告映射
│   │   │   ├── cover.py         # 求职信生成（LLM + 模板兜底 + 姓名纠偏）
│   │   │   ├── agents.py        # 简历 Agent / 面试官 Agent + 降级
│   │   │   ├── pdf_parser.py    # 文本层 → OCR → 结构化
│   │   │   ├── ocr.py           # RapidOCR + PyMuPDF 渲染（分带识别）
│   │   │   ├── llm.py           # 流式 + 错误分类 + 重试 + 熔断
│   │   │   ├── rag.py           # 简历模板检索（hash-trick 向量）
│   │   │   ├── mock_engine.py   # 无 Key 时的确定性演示引擎
│   │   │   ├── state.py         # 8 阶段状态机（非法迁移 409）
│   │   │   └── exporter.py      # HTML / PDF 渲染
│   │   └── db.py                # 表结构 + 幂等迁移
│   ├── data/                    # resumepilot.db / chroma / templates / outbox
│   └── tests/                   # 112 个 pytest 用例
└── frontend/
    ├── middleware.ts            # 路由守卫（Cookie → 未登录 307 到 /login）
    ├── app/
    │   ├── page.tsx             # /            总览 Dashboard
    │   ├── login/page.tsx       # /login       登录/注册
    │   ├── jobs/page.tsx        # /jobs        岗位广场
    │   ├── jobs/[id]/page.tsx   # /jobs/[id]   岗位详情 + 一键测匹配
    │   ├── workspace/[sid]/     # /workspace  简历工作台（5 个 Tab）
    │   └── applications/        # /applications 投递看板
    ├── components/              # AppShell / RadarChart / MatchPanel / RecommendedJobs / ApplyDialog …
    └── lib/                     # api(含 token 注入) / auth(Provider) / types / stage / diff
```

---

## 3. 数据库

| 表 | 作用 |
|---|---|
| `users` | 账号（email 唯一，PBKDF2 哈希） |
| `sessions` | 简历会话（新增 `user_id` 归属、`job_id` 当前岗位） |
| `stage_history` | 阶段迁移审计 |
| `jobs` | 岗位池 50 条（薪资/技能/完整 JD） |
| `job_matches` | Top3 推荐 + 报告快照（`UNIQUE(session_id, job_id)`） |
| `applications` | 投递记录（状态 + 邮件状态 + 附件路径，`UNIQUE(user_id, job_id)` 防重复投递） |
| `application_events` | 投递状态流水（看板时间轴） |

迁移策略：启动时 `PRAGMA table_info` 检查缺列才 `ALTER`，旧会话 `user_id` 保持 NULL，不会串到任何账号。

---

## 4. API 一览

```
POST   /api/auth/register | /login          GET /api/auth/me
GET    /api/jobs?q=&city=&seniority=        GET /api/jobs/{id}      GET /api/jobs/filters
POST   /api/sessions                        GET /api/sessions/{sid}
POST   /api/sessions/{sid}/match            → Top3 推荐
POST   /api/sessions/{sid}/match/{job_id}   → 匹配报告（SSE，事件 match_report）
GET    /api/sessions/{sid}/matches
POST   /api/sessions/{sid}/analyze          → 手填 JD 模式的诊断（SSE）
POST   /api/sessions/{sid}/chat             → 追问 / 重写 / 面试作答（SSE）
POST   /api/sessions/{sid}/interview/start  POST .../interview/answer
GET    /api/sessions/{sid}/preview|export
POST   /api/applications                    GET /api/applications
PATCH  /api/applications/{id}               GET /api/applications/{id}/events|resume
```

---

## 5. 启动

> 端口说明：本项目固定用 **8001（后端）/ 3001（前端）**，避开常驻的 3000/8000。

**① 安装依赖**（首次克隆后执行一次）

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-rag.txt -r requirements-ocr.txt
cp .env.example .env          # 填入 DEEPSEEK_API_KEY；不填则自动走演示引擎

cd ../frontend
npm install
cp .env.example .env.local    # 可选，默认已指向 127.0.0.1:8001
```

**② 启动**

```bash
# 后端
cd backend
.venv/Scripts/python -m uvicorn app.main:app --port 8001

# 前端（端口与后端地址在 build 时固化，换端口需重新 build）
cd frontend
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8001 API_PROXY=http://127.0.0.1:8001 npm run build
API_PROXY=http://127.0.0.1:8001 ./node_modules/.bin/next start -p 3001
```

打开 http://127.0.0.1:3001 → 注册账号 → 上传简历。

> 首次启动会自动建表并幂等导入 50 条岗位、建立 Chroma 索引，无需手动初始化数据。
> `backend/data/` 下的数据库、向量索引、发件箱均在 `.gitignore` 中，克隆后自动生成。

**`DEEPSEEK_API_KEY`**（`backend/.env`，不配也能跑）：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

不配置时 LLM 调用回退到 `mock_engine`（确定性演示输出），全流程依然可走通。

**SMTP 配置**（`backend/.env`，不配也能跑）：

```env
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的邮箱
SMTP_PASSWORD=授权码          # 不是登录密码
```

不配置时投递走「演示模式」：邮件 + PDF 写入 `backend/data/outbox/`，`mail_status=simulated`，前端可下载 `.eml`。

**③ 单端口部署（线上形态）**

线上只有**一个 Python 进程**，前端是静态产物，无需 Node 运行时：

```bash
cd frontend && NEXT_PUBLIC_API_BASE= npx next build   # 关键：显式设为空串 → 走同源 /api/*
cd .. && rm -rf backend/web && cp -r frontend/out backend/web
cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

`app/main.py` 会按 `STATIC_DIR` → `backend/web` → `./web` → `frontend/out` 顺序探测静态目录并挂到根路径，
`/api/*` 与 `/docs` 仍由 FastAPI 处理。为此前端做了两处妥协：

- 删除 `middleware.ts`，路由守卫改为客户端（`AuthProvider` 检测无 token 即跳登录）；
- 动态路由改为查询参数：`/workspace/?sid=xxx`、`/jobs/detail/?id=job_017`，因为静态导出不支持动态段。

**部署环境需要注意的两个坑**（已修复，改代码时别退回去）：

- `JWT_SECRET` 必须显式配置。默认实现是把密钥写入 `data/.jwt_secret`，在多实例或无持久盘的环境里
  每个实例各生成一份，表现为「登录成功但下一个请求 401」。
- 凭证除了 `Authorization: Bearer` 还支持 `X-RP-Token` 头与 `rp_auth` Cookie。部分托管平台的网关会
  给每个请求注入自己的 `Authorization` 与同名 Cookie，把业务凭证覆盖掉。

---

## 6. 测试

```bash
cd backend && .venv/Scripts/python -m pytest -q      # 112 passed
cd frontend && ./node_modules/.bin/tsc --noEmit      # 类型检查
```

覆盖：状态机、PDF/OCR、SSE 端到端、LLM 降级、SQLite 持久化、JWT 与跨用户隔离、
岗位池（50 条/筛选/检索相关性）、匹配（白名单丢弃、雷达 6 维、技能不编造）、投递（前置校验/重复/流转/附件）。

---

## 7. 关键设计

**① 岗位推荐不新增状态机阶段**
推荐是 `PARSED` 上的只读查询；选中岗位后才把该岗位 JD 灌入会话并推进到 `DIAGNOSED`。
原有状态机、步骤条、75 个历史用例全部不用改，重构风险最低。

**② 「不编造岗位」三道闸门**
1. Prompt 白名单：候选以 `job_007 | 岗位 | 公司 | 技能` 紧凑格式喂给模型；
2. 服务端校验：返回的 `job_id` 逐个比对候选集，非白名单直接丢弃并记 warning；
3. 数量兜底：丢弃后不足 3 条按规则分补齐。
技能缺口同理——`skill_gap[].skill` 必须能在岗位 `skills` 或 JD 原文中找到。

**③ 报告即诊断**
`MatchReport` 生成后映射为原有 `Diagnosis`（雷达 6 维 → dimensions，技能缺口 → missing_keywords），
所以「追问 → STAR 重写 → 模拟面试」链路零改动续跑。

**④ 求职信事实纪律**
Prompt 明确「姓名逐字使用、年限只能用简历写过的数字、禁止推算」，
服务端再做一次署名兜底，杜绝模型替候选人改名或虚增年限。

**⑤ 降级不中断**
LLM 401/402 熔断、429/5xx 重试；失败时推 `warning` 并回退演示引擎。
Chroma 不可用降级内存余弦；SMTP 不可用降级本地存档。任何一环挂了，主流程都能走完。

---

## 8. 已知限制

- 岗位池为**虚构模拟数据**，公司与薪资仅用于演示语义检索，不代表真实招聘。
- 邮件只发往注册邮箱（后端从 JWT 取，前端无法指定），避免被当作群发工具。
- 同一岗位不可重复投递（`UNIQUE(user_id, job_id)`），撤回后如需重投请删除记录。

---

## 9. License

[MIT](./LICENSE) © 2026 林
