# FinPulse 智能投研引擎

> **FinPulse** 是一套端到端的智能金融投研系统：基于 **LangGraph 多节点 Agent** 与**国盛证券《择时六面图》35 项定量指标引擎**，实现从 `28 大财经媒体秒级抓取 → LLM 真实打标分类 → 结构化落库 → 多板块深度推理 → 全局研报合成 → 高保真 PDF 导出` 的全自动流水线，并提供 Vue3 可视化大屏与 Node.js BFF 网关。

- **后端**：Python **FastAPI** + **Motor(异步 MongoDB)** + **LangGraph**，端口 `8000`
- **BFF**：Node.js 原生 HTTP 聚合网关，端口 `3000`
- **前端**：**Vue3 + Vite + ant-design-vue + ECharts**，端口 `5173`

---

## 仓库结构 (Monorepo)

```text
FinPulse/
├── backend/                # Python 后端：抓取引擎 / Agent 体系 / 择时六面图 / PDF 研报
│   ├── app/
│   │   ├── api/v1/         # REST 路由 (health, insights, news, config)
│   │   ├── agents/         # Extractor / Tagger / Analyst / Synthesizer / Auditor 智能体
│   │   ├── core/           # LLMFactory、日志、LangGraph 状态图、排版校验
│   │   ├── data_fetchers/  # 28 大媒体抓取引擎 + 4 类特色特征算子
│   │   ├── db/             # MongoDB 异步驱动与连接池 (Motor)
│   │   ├── models/         # Pydantic Schema (RawNews / StructuredNews)
│   │   ├── timing_hexagon/ # 择时六面图 35 项指标计算与图表引擎
│   │   └── main.py         # FastAPI 入口 (Port 8000)
│   ├── data/               # 原始抓取数据 / 清洗后数据 / 源数据 / 结果 CSV
│   ├── scripts/            # 端到端流水线 / PDF 转换 / 数据库运维脚本
│   ├── skills/             # Agent 技能库 (skill-creator 规范)
│   ├── output/             # 自动生成的 HTML / PDF 研报
│   ├── pyproject.toml      # PEP 517/518 打包与全量依赖 (pip install -e .)
│   └── README.md           # 后端详细说明
│
├── frontend/               # Vue3 前端可视化大屏 (Port 5173)
│   ├── src/
│   │   ├── views/          # DashboardView / HexagonView / SectorsView / SectorDetailView
│   │   ├── components/     # EChart 组件
│   │   ├── router/         # vue-router 路由
│   │   └── api/            # axios 封装
│   └── README.md           # 前端详细说明
│
├── bff/                    # Node.js BFF 聚合转发服务 (Port 3000，零第三方依赖原生 http)
│   └── README.md           # BFF 详细说明
│
└── README.md               # 本文件（系统总览）
```

---

## 系统架构与核心数据流

FinPulse 的核心是「**两库分离 + LLM 真实打标**」：

```text
[28 大财经媒体] --FlashNewsFetcher--► raw_news_collection (sector="未分类", 仅源级提示)
                                          │
                                          ▼  node_extract
            ┌──────────────────────────────────────────────┐
            │ ExtractorAgent: 抽核心事实 / 实体 / 情绪 / 评价值 │
            │ TaggerAgent:     两阶段 LLM 真实分类打标         │
            │   Stage1: 宏观 / 行业板块                       │
            │   Stage2: 国内·国外宏观 或 东财 86 官方行业       │
            └──────────────────────────────────────────────┘
                                          │
                                          ▼
                          structured_news_collection (真实分类的权威源)
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                     /news/flash    /news/sectors    /news/by_sector
                        (总览大屏)      (板块聚合)         (板块详情)
```

> **关键设计**：所有展示端（前端大屏 / 板块聚合 / 板块详情）**只从 `structured_news_collection` 读取**。`raw_news_collection` 只是流水线的输入/暂存层，其 `sector` 为占位、不代表真实分类。真实板块归属由 **TaggerAgent 逐条调用 LLM** 判定，杜绝手工硬编码兜底。

### 六节点 LangGraph 研报流水线

```
node_extract → node_aggregate → node_analyze → node_synthesize → node_audit → node_validate_and_export
 (萃取+打标)    (板块分组+特征算子)  (分板块Analyst)  (全局Synthesizer)   (Auditor审查)     (排版+PDF)
```

- **node_extract**：12 路**有界并发**打标，保证 24h 全量新闻逐条真实 LLM 标注（而非抽样或串行数小时）。
- **node_analyze**：AnalystAgent 按板块纯资讯深度推理（结合两融 / DR007 / ERP 等定量指标）。
- **node_synthesize**：SynthesizerAgent 全局总揽（模块化直拼：总评 / 择时六面图 / 资讯分析 三章节）。
- **node_audit**：AuditorAgent 金融真实性与防幻觉审查，实时比对指标数值与图表一致性。
- **node_validate_and_export**：ReportValidator 修复排版 + Playwright 编译高保真 PDF 研报。

---

## 核心技术特性

| 模块 | 说明 |
|---|---|
| 28 大媒体抓取 | 新浪 / 东财 / 财联社 / 华尔街见闻 / Reuters / Bloomberg 等，`asyncio.gather` 并发抓取 + 早停熔断 |
| TaggerAgent | 两阶段 LLM 分类；严格区分「个股/板块成交→所属行业」与「全市场/宏观资金面→国内宏观·市场流动性」 |
| 择时六面图 | 国盛证券《择时六面图》35 项定量指标，无未来函数，`ThreadPoolExecutor` 多线程爬取 + 三阶合规流水线 |
| ECharts 大屏 | 雷达图 / 双 Y 轴对比折线图，`Radar_Six_Dimensions.png` 嵌入研报 PDF |
| LangGraph | 全原生 `async def` 节点，单事件循环，复用 MongoDB 异步连接池 |
| Auditor + Validator | 纯 LLM 防幻觉审查 + Markdown 结构校验 + 高保真 PDF 编译 |

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- MongoDB（默认 `mongodb://localhost:27017`，库名 `intelligent_research_db`）

### 1. 后端

```bash
cd backend
pip install -e .            # 安装全部依赖（PEP 517/518，统一由 pyproject.toml 管理）
cp .env.example .env        # 配置 LLM / MongoDB / SMTP 等密钥（.env 已被 gitignore，不会提交）
python scripts/run_end_to_end_pipeline.py   # 一键跑通全流程（抓取→计算→AI打标→研报→PDF）
python app/main.py          # 启动 FastAPI (Port 8000)，文档 http://localhost:8000/docs
```

### 2. BFF

```bash
cd bff
node server.js              # 启动 Node.js BFF (Port 3000)，零第三方依赖
# 健康检查: http://localhost:3000/bff/health
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev                 # 启动 Vue3 Vite 开发服务器 (Port 5173)
```

### 4. 每日自动调度（可选）

```bash
cd backend
python daily_scheduler_7am.py        # 每日 07:00 自动执行整条流水线
python daily_scheduler_7am.py --now  # 手动立即触发一次
```

---

## 服务与端口

| 服务 | 技术栈 | 端口 | 说明 |
|---|---|---|---|
| backend | FastAPI + Motor + LangGraph | `8000` | 数据抓取 / Agent 推理 / 研报生成，`/docs` |
| bff | Node.js 原生 http | `3000` | 前后端聚合转发 + CORS，探针 `/bff/health` |
| frontend | Vue3 + Vite + ECharts | `5173` | 可视化大屏（Vite 代理 `/api`、`/static` → 后端） |

---

## 安全与代码规范

- `.env` 密钥配置（LLM API Key、MongoDB URI、SMTP 口令）已被 `.gitignore` 排除，**不会提交**。
- `venv/`、`node_modules/`、`__pycache__/`、`*.egg-info/`、`logs/`、`output/`、生成的 PDF/HTML 均不入库。
- `.env.example` 提供无敏感信息的配置模板，供部署使用。

---

## 子模块说明

- [backend/README.md](backend/README.md) — 后端架构、Agent 体系、择时六面图、脚本、环境变量详解
- [frontend/README.md](frontend/README.md) — 前端视图、组件、API 对接、构建说明
- [bff/README.md](bff/README.md) — BFF 代理路由、端点、配置说明
