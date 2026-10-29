# ResumePilot Pro · 智能求职全链路平台 —— 重构方案

> 状态：待确认　|　基线：ResumePilot v1（75 pytest 全绿）
> 目标：从「单机工具」升级为「多用户平台」，补齐 岗位池 / 双向匹配 / 投递追踪 三条主干。

---

## 一、现状盘点

| 维度 | 现状 | 改造结论 |
|---|---|---|
| 用户体系 | 无，`localStorage` 存 `sid` 直接访问 | **新增** JWT + users 表 |
| 会话归属 | `sessions` 表无 `user_id`，任何人拿到 sid 即可读 | `sessions` 加 `user_id`，所有路由强制 owner 校验 |
| 岗位数据 | 无，JD 为用户手填字符串 | **新增** `jobs` 表（50 条）+ Chroma 独立集合 |
| 匹配 | 单 JD 诊断（`Diagnosis`） | **扩展**：简历→Top3 岗位召回 + 岗位→雷达图报告 |
| 投递 | 无 | **新增** `applications` 表 + SMTP + 看板 |
| 前端 | 单页 `/` 工作台 | **重构**为 6 个路由，原工作台迁至 `/workspace/[sid]` |

**可完整复用的部分（约占现有代码 70%，不重写）**
- SSE 协议与 `sse_stream()` 收尾落盘
- 状态机 `Stage` + `stage_history` 审计
- `pdf_parser` / `ocr` / `exporter` / `llm` 降级与熔断
- `Diagnosis` → `GapQuestion` → STAR 追问 → 重写 → 面试 的完整链路
- `HashEmbedding`（384 维 hash-trick）+ Chroma 降级内存余弦的写法

**关键设计取舍**：岗位推荐**不新增状态机阶段**。推荐是 `PARSED` 阶段上的只读查询（`GET` 语义），选中岗位后才走原有 `/analyze` 把 JD 灌入 → `DIAGNOSED`。这样状态机、Header 步骤条、既有测试全部不用动，风险最低。

---

## 二、工作量评估

### 2.1 后端（新增 ≈2,600 行 / 改 6 文件，新增 9 文件）

| 模块 | 新增文件 | 改动文件 | 新增行数 | 风险 |
|---|---|---|---|---|
| 鉴权底座 | `security.py`(JWT+PBKDF2)、`users.py` | `db.py`、`api.py` | ~420 | 低 |
| 数据迁移 | `migrate.py` | `session.py`、`config.py` | ~180 | 中（改老表结构） |
| 岗位池 | `jobs_seed.json`(50 条)、`jobs.py` | `rag.py` | ~1,450（其中种子数据 1,300） | 低 |
| 双向匹配 | `matching.py`、`match_prompt.py` | `agents.py`、`schemas.py` | ~520 | **高**（LLM 编造岗位） |
| 投递 | `mailer.py`、`applications.py` | `api.py` | ~430 | 中（SMTP 依赖外部） |
| 测试 | `test_auth.py`、`test_jobs.py`、`test_matching.py`、`test_applications.py` | `conftest.py` | ~500 | 低 |

### 2.2 前端（新增 ≈1,500 行 / 新增 11 文件，改 4 文件）

| 模块 | 新增文件 | 新增行数 |
|---|---|---|
| 认证 | `app/login/page.tsx`、`lib/auth.tsx`（AuthProvider+token 注入） | ~300 |
| 平台外壳 | `components/AppShell.tsx`（侧边导航 + 用户菜单） | ~200 |
| 总览 | `app/page.tsx`（改为 Dashboard） | ~240 |
| 岗位 | `app/jobs/page.tsx`、`app/jobs/[id]/page.tsx` | ~360 |
| 匹配 | `components/RadarChart.tsx`（纯 SVG，零图表库）、`components/MatchPanel.tsx` | ~330 |
| 投递 | `components/ApplyDialog.tsx`（邮件预览 + 确认发送） | ~180 |
| 看板 | `app/applications/page.tsx` | ~250 |
| 工作台迁移 | `app/workspace/[sid]/page.tsx`（原 `page.tsx` 搬移） | ~560（搬移为主） |

### 2.3 汇总

- **净新增 ≈4,100 行**，触及 **36 个文件**（新增 20，修改 16）
- 新增依赖仅 **3 个**：`PyJWT`（JWT）、标准库 `smtplib`/`email`（邮件）、`hashlib.pbkdf2_hmac`（密码哈希，零依赖）
- 测试规模：75 → **约 110 个用例**
- 分 6 个阶段交付，每阶段均可独立运行 + 测试

> 工作量画像：这是一次**中等偏大的横向扩展**，难点不在代码量，而在三处一致性——鉴权与旧数据的兼容、LLM 输出的岗位白名单约束、路由重构后的状态恢复。

---

## 三、数据库表结构变更

### 3.1 新增表（5 张）

```sql
-- 1) 用户
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,          -- uuid hex
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,             -- pbkdf2_sha256$迭代数$salt$hash
    display_name  TEXT DEFAULT '',
    phone         TEXT DEFAULT '',
    created_at    REAL NOT NULL,
    last_login_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 2) 岗位池（SQLite 为 source of truth，Chroma 只做索引）
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,            -- job_001 ... job_050
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    city        TEXT DEFAULT '',
    salary_min  INTEGER DEFAULT 0,           -- 单位：K/月
    salary_max  INTEGER DEFAULT 0,
    seniority   TEXT DEFAULT '',             -- 校招 / 1-3年 / 3-5年 / 5-10年
    industry    TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',           -- JSON: ["大厂","双休","弹性"]
    skills      TEXT DEFAULT '[]',           -- JSON: 硬性技能关键词，用于技能缺口比对
    jd_text     TEXT NOT NULL,               -- 完整 JD 原文
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_city ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);

-- 3) 匹配记录（Top3 召回 + 岗位级报告快照）
CREATE TABLE IF NOT EXISTS job_matches (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    job_id       TEXT NOT NULL,
    match_score  INTEGER DEFAULT 0,
    rank         INTEGER DEFAULT 0,          -- 1..3 表示推荐位次；0=用户手动选的岗位
    source       TEXT DEFAULT 'rag',         -- rag | manual
    reason       TEXT DEFAULT '',            -- 推荐理由（LLM 生成，白名单内）
    report_json  TEXT,                       -- MatchReport 快照（含雷达图）
    created_at   REAL,
    UNIQUE(session_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_session ON job_matches(session_id, rank);

-- 4) 投递
CREATE TABLE IF NOT EXISTS applications (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    job_id        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'applied',  -- applied|interviewing|offer|rejected|withdrawn
    match_score   INTEGER DEFAULT 0,
    email_to      TEXT DEFAULT '',
    email_subject TEXT DEFAULT '',
    email_body    TEXT DEFAULT '',                  -- HTML 正文
    mail_status   TEXT DEFAULT 'pending',           -- pending|sent|failed|simulated
    mail_error    TEXT DEFAULT '',
    attachment    TEXT DEFAULT '',                  -- data/outbox/xxx.pdf
    note          TEXT DEFAULT '',
    created_at    REAL,
    updated_at    REAL,
    UNIQUE(user_id, job_id)
);

-- 5) 投递状态流水（看板时间轴 + 审计）
CREATE TABLE IF NOT EXISTS application_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    from_status    TEXT,
    to_status      TEXT NOT NULL,
    note           TEXT DEFAULT '',
    created_at     REAL NOT NULL
);
```

### 3.2 既有表变更

```sql
ALTER TABLE sessions ADD COLUMN user_id TEXT;   -- 归属用户
ALTER TABLE sessions ADD COLUMN job_id  TEXT;   -- 当前选中的岗位（可空=手填 JD）
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at DESC);
```

**迁移策略**（`migrate.py`，启动时幂等执行）
1. `PRAGMA table_info(sessions)` 检查列是否存在，缺失才 `ALTER`
2. 旧数据 `user_id` 保持 `NULL` —— 所有查询都带 `WHERE user_id = ?`，历史演示数据自然不展示给任何账号（不做"认领"，避免串号）
3. `jobs` 表为空时从 `jobs_seed.json` 导入 50 条，并 upsert 到 Chroma `jobs_hash384` 集合
4. Chroma 不可用 → 降级内存余弦，`/api/health` 的 `rag.jobs_backend` 标记状态

---

## 四、前端页面路由设计

```
/login                     登录 / 注册（同页 Tab 切换，成功后跳转 ?next=）
/                          Dashboard：我的简历、Top3 推荐、投递漏斗、快捷入口
/jobs                      岗位广场：50 条岗位，搜索 + 城市/年限/薪资筛选
/jobs/[id]                 岗位详情：完整 JD + 一键「用我的简历测匹配」
/workspace/[sid]           简历工作台（原 / 迁入）：预览 / 红绿对比 / 匹配诊断 / 推荐岗位 / 模拟面试
/applications              投递看板：已投递 → 已邀面 → 已结束（offer / rejected）
```

**路由守卫**：`middleware.ts` 校验 `rp_token` Cookie（同时写 localStorage 供 SSR 外读取），未登录一律 302 到 `/login?next=`；`AuthProvider` 负责 401 时清 token 并跳登录。

**工作台 Tab 变更**（`/workspace/[sid]`）
现有 `preview | diff | diagnosis | interview` → 新增 `jobs`（Top3 推荐）与 `apply`（投递）两个 Tab；`diagnosis` Tab 内升级为雷达图 + 技能缺口双区。

---

## 五、API 契约（新增，全部挂在 `/api`）

### 5.1 认证
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/register` | `{email, password, display_name}` → `{token, user}`，邮箱唯一，密码 ≥8 位 |
| POST | `/auth/login` | → `{token, user}`，签发 7 天 HS256 JWT（`sub=user_id`） |
| GET | `/auth/me` | 当前用户，用于刷新页面恢复登录态 |
| POST | `/auth/logout` | 清 Cookie（前端为主） |

### 5.2 岗位池
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/jobs?q=&city=&seniority=&limit=&offset=` | 列表，返回总数与分页 |
| GET | `/jobs/{job_id}` | 详情（含 `skills[]`、`salary`、完整 JD） |
| GET | `/jobs/filters` | 可选筛选项（城市、年限枚举） |

### 5.3 双向匹配
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/sessions/{sid}/match` | **简历 → Top3**。抽取简历特征 → Chroma 召回 12 → 规则预排 6 → LLM 精排 3。返回 `[{job, score, reason, matched_skills, missing_skills}]`，结果落 `job_matches` |
| POST | `/sessions/{sid}/match/{job_id}` | **岗位 → 匹配报告**（SSE 流式）。产出 `MatchReport`：`radar[]` + `skill_gap[]` + verdict/strengths/risks + `gap_questions[]`；写入 `job_matches.report_json` 与 `session.diagnosis`，阶段推进到 `DIAGNOSED` |
| GET | `/sessions/{sid}/matches` | 已产生的推荐与报告，供刷新恢复 |

> **与原流程的衔接**：`/match/{job_id}` 除雷达图外仍产出 `gap_questions`，因此用户选完岗位后，原有「追问 → STAR 重写 → 模拟面试」链路**零改动直接续跑**。

### 5.4 投递
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/applications` | `{session_id, job_id, note?}`。生成求职信 → PDF 附件 → SMTP 发送到**注册邮箱** → 落库 |
| GET | `/applications?status=` | 看板数据（含岗位名、公司、匹配分、邮件状态） |
| PATCH | `/applications/{id}` | `{status, note}` 状态流转，写 `application_events` |
| GET | `/applications/{id}/resume` | 下载当时投递的 PDF 附件 |

**投递前置校验**：`session.stage ∈ {OPTIMIZED, REVIEWED}`（必须先优化完），否则 409；重复投递同一岗位 → 409。

---

## 六、匹配算法与「不编造岗位」的硬约束

### 6.1 简历 → Top3（三路打分）
```
query_text = headline + skills + 每段经历/项目首条 bullet（截断 1,500 字）
召回：Chroma jobs_hash384 → top 12
预排：score = 0.5×技能命中率 + 0.3×向量余弦 + 0.2×(年限/城市适配)  → 取 top 6
精排：LLM 在 6 个候选里排序，输出 top3 + 理由（禁止引入候选外的岗位）
```

### 6.2 防编造三道闸门（对应需求第 5 条）
1. **Prompt 白名单**：候选以 `job_007 | 字节跳动 | 后端开发…` 形式给出，明确「只能从下列编号中选择，不得虚构」；
2. **服务端校验**：LLM 返回的 `job_id` 逐个比对候选集，非白名单条目直接丢弃并记 `log.warning`；
3. **数量兜底**：丢弃后不足 3 条，按预排分数从候选集补齐 —— 保证「推荐一定有 3 条，且全部真实存在于岗位池」。

技能缺口同理：`skill_gap[].skill` 必须能在 `jobs.skills` 或 JD 原文中匹配到，否则剔除（沿用现有 `_merge_skills` 的"只允许重排、不允许新增"思路）。

### 6.3 MatchReport 结构（雷达图数据）
```json
{
  "overall_score": 78,
  "verdict": "整体匹配度良好，核心技能覆盖 7/10",
  "radar": [
    {"dimension": "技能覆盖", "score": 82, "benchmark": 90, "comment": "缺少 Kafka 实战"},
    {"dimension": "经验深度", "score": 75, "benchmark": 85, "comment": "3 年 vs 要求 5 年"},
    {"dimension": "项目复杂度", "score": 88, "benchmark": 80, "comment": "有高并发项目"},
    {"dimension": "行业相关", "score": 70, "benchmark": 75, "comment": "电商转金融"},
    {"dimension": "学历资质", "score": 85, "benchmark": 80, "comment": "本科对口"},
    {"dimension": "薪资预期", "score": 66, "benchmark": 70, "comment": "期望略低于区间下限"}
  ],
  "skill_gap": [
    {"skill": "Kafka", "importance": "high", "have": false,
     "evidence": "", "suggestion": "补一个消息队列异步解耦的项目案例"}
  ],
  "strengths": ["..."], "risks": ["..."],
  "missing_keywords": ["Kafka", "分布式事务"],
  "gap_questions": [{"id": "g1", "topic": "...", "question": "...", "bullet_id": "b1"}]
}
```

---

## 七、投递链路（SMTP）

```
[投递按钮] → 生成求职信(LLM，模板兜底) → render_pdf(optimized 简历)
        → EmailMessage(HTML + PDF 附件) → smtplib.SMTP_SSL(注册邮箱)
        → mail_status=sent | failed | simulated → 落库 → 看板刷新
```

- 配置：`SMTP_HOST/PORT/USER/PASSWORD/FROM_NAME`（QQ 邮箱用授权码，非登录密码）
- **未配置 SMTP 时优雅降级**：`mail_status='simulated'`，把 `.eml` + PDF 写入 `data/outbox/`，前端明确标注「演示模式：邮件已生成未真实发送，可下载 .eml 查看」
- 发送失败**不阻塞投递记录**（`mail_status=failed` + 错误原因，看板可重发）
- 同步 `smtplib` 用 `asyncio.to_thread` 包装，避免阻塞事件循环

> 需要你确认：SMTP 凭据由谁提供、用哪个邮箱服务商（QQ / 163 / Gmail）。未提供则默认走"模拟发送 + 本地 .eml"。

---

## 八、分阶段实施计划

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0 鉴权底座** | users 表、JWT、PBKDF2、迁移、`get_current_user` 依赖、旧路由加 owner 校验 | 未登录访问 401；A 用户读不到 B 的 session（专测）；旧 75 用例仍全绿 |
| **P1 岗位池** | 50 条种子数据、jobs 表、Chroma `jobs_hash384`、列表/详情 API + 两个页面 | 50 条入库、检索返回合理 Top，分页/筛选正确 |
| **P2 双向匹配** | 特征抽取、三路召回、白名单校验、MatchReport prompt、雷达图组件、匹配 Tab | 推荐结果全部命中岗位池（断言 `job_id in 集合`）；雷达图 6 维渲染 |
| **P3 投递** | mailer、applications 表、求职信生成、投递按钮 + 邮件预览弹窗 | 无 SMTP 时产出 .eml；配置后真实收信；重复投递 409 |
| **P4 看板** | applications 看板、状态流转、事件时间轴 | 状态流转写流水；漏斗计数正确 |
| **P5 平台化收尾** | Dashboard、路由重构、middleware 守卫、`page.tsx` 迁移、全量回归 | 6 条路由可访问；未登录被拦截；**约 110 用例 100% 通过** |

每个阶段结束我都会：跑 pytest → 用真实 Key 走一遍端到端 → 给你可点击的验证路径。

---

## 九、需要你确认的 3 个决策点

1. **SMTP 邮箱**：现在就配（提供 QQ/163 授权码 + 收件邮箱），还是先做「模拟发送 + .eml 下载」？（推荐先降级，P3 阶段再补真实凭据）
2. **原有手填 JD 模式**：保留为「自由诊断」入口（老用户不受影响），还是强制走岗位池？（推荐保留，`session.job_id` 为空即手填模式）
3. **岗位池数据**：50 条由我按主流大厂（字节/阿里/腾讯/美团/拼多多等）+ 常见技术栈生成，**纯模拟数据、不涉及真实招聘信息**，可否？

确认后我按 P0 → P5 顺序开工。
