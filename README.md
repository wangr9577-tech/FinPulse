# FinPulse 智能投研引擎

> **FinPulse** 是一套端到端的智能金融投研系统，基于 **LangGraph 多节点 Agent** 与**国盛证券《择时六面图》35 项定量指标引擎**，实现从 `28 大财经媒体秒级抓取 → LLM 真实打标分类 → 结构化落库 → 多板块深度推理 → 全局研报合成 → 高保真 PDF 导出` 的全自动流水线，并提供 Vue3 可视化大屏与 Node.js BFF 网关。系统另扩展了**上市公司每日投资日报**：自动爬取沪、深交易所公告，经标题情绪判定 + PDF 全文复核、板块强度分析、研报选股与业绩预告，汇总为一份可直接入库与展示的《投资日报》。

- **后端**：Python **FastAPI** + **Motor(异步 MongoDB)** + **LangGraph**，端口 `8000`
- **BFF**：Node.js 原生 HTTP 聚合网关（零第三方依赖），端口 `3000`
- **前端**：**Vue3 + Vite + ant-design-vue + ECharts + Pinia**，端口 `5173`

---

## 核心特性总览

| 能力 | 说明 |
|---|---|
| 多源财经媒体抓取 | 覆盖新浪、东方财富、财联社、华尔街见闻、Reuters、Bloomberg 等 28 大财经媒体，并扩展「高股息/红利」「低估值/破净/回购」「大消费/白酒/零售」三类垂直板块，`asyncio.gather` 并发抓取 + 早停熔断 |
| LLM 真实打标分类 | Extractor 萃取核心事实与情绪，Tagger 两阶段 LLM 真实判定板块归属（先大类「宏观/行业板块」，再细分国内/海外宏观或东财 86 个官方行业），**无手工硬编码兜底** |
| 择时六面图 | 国盛证券《择时六面图》35 项定量指标，跨 6 大维度（经济面、估值面、资金面、技术面、情绪面、流动性），无未来函数，多线程爬取 + 三阶合规流水线 |
| 多节点 Agent 引擎 | Extractor / Tagger / Analyst / Synthesizer / Auditor 五类 Agent，原生全异步 `async def` 节点，单事件循环复用 MongoDB 异步连接池 |
| 防幻觉审查 | Auditor 纯 LLM 金融真实性核验 + ReportValidator Markdown 结构校验，Playwright 编译高保真 PDF 研报 |
| 买方技能库 | 基于 `skill-creator` 规范沉淀买方 08:00 盘前分析逻辑，SkillLoader 运行时动态注入 Analyst / Synthesizer 上下文 |
| 每日投资日报 | 沪深交易所公告爬取 → 标题情绪判定 + PDF 全文 DeepSeek 复核 → 板块强度 → 研报选股 → 业绩预告 → 《投资日报》 |
| 自动化投递 | 每日 07:00 常驻调度器自动跑全流程，SMTP SSL 邮件推送单日研报 |

---

## 系统架构与核心数据流

FinPulse 的核心设计是「**两库分离 + LLM 真实打标**」：抓取层只作为流水线输入/暂存，权威层由 LLM 逐条真实判定，所有展示端只读权威层。

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

> **设计要点**：所有展示端（前端大屏 / 板块聚合 / 板块详情）**只从 `structured_news_collection` 读取**。`raw_news_collection` 的 `sector` 为占位、不代表真实分类；真实板块归属由 **TaggerAgent 逐条调用 LLM** 判定，杜绝手工硬编码兜底，保证分类质量可溯源。

### LangGraph 六节点研报流水线

```
node_extract → node_aggregate → node_analyze → node_synthesize → node_audit → node_validate_and_export
 (萃取+打标)    (板块分组+特征算子)  (分板块Analyst)  (全局Synthesizer)   (Auditor审查)     (排版+PDF)
```

流水线状态由 `PipelineGraphState` 承载，各节点职责如下：

| 节点 | 职责与实现 |
|---|---|
| `node_extract` | ExtractorAgent 萃取情报卡片 + TaggerAgent 两阶段打标，**12 路有界并发**（`asyncio.Semaphore` + `asyncio.to_thread`），保证 24h 时间窗内全量新闻逐条真实 LLM 标注而非抽样或串行数小时；结果 `upsert` 落库到 `structured_news_collection` |
| `node_aggregate` | FeatureOperatorEngine 实时抓取全市场特征算子（两融 / 流动性 / ERP 等）；SectorGrouper 依据结构化卡片原生 `sector` 标签做纯字典 `Group-By` 分组，无需聚类算法，天然兼容任意新增行业 |
| `node_analyze` | AnalystAgent 按板块并发做纯资讯深度推理（并发度 4，单板块失败不中断整条流水线）；若前端订阅配置勾选了 `report_sectors`，则经 `expand_sector_selection` 展开别名后只分析这些板块 |
| `node_synthesize` | SynthesizerAgent 全局统稿，输出拆分的 `hexagon_report_markdown`（总评 + 择时六面图）与 `news_report_markdown`（资讯分析），二者合并为完整研报 |
| `node_audit` | AuditorAgent 对择时研报做金融真实性与防幻觉审查，实时比对指标数值与图表一致性；发现偏差即纠偏并回写 `corrected_report_markdown` |
| `node_validate_and_export` | ReportValidator 校验修复 Markdown 结构，经 Playwright 编译 `market_insight_report.pdf` 与 `timing_report.pdf`，并将研报元数据（含实际包含板块清单）写入 `market_insight_reports` |

---

## 核心功能与实现详解

### 多源财经媒体抓取引擎

- **覆盖范围**：新浪财经、东方财富、财联社、华尔街见闻、36 氪、IT 之家、钛媒体、EE Times、机器之心、量子位、Reuters、Bloomberg、Yahoo Finance，并扩展「高股息/红利」「低估值/破净/回购」「大消费/白酒/零售」三大垂直板块。
- **并发抓取**：`asyncio.gather` 结合 `asyncio.to_thread`，把 28 大媒体快讯异步拉取与 35 项择时指标多源爬虫并行化，Stage 1 抓取效率提升近 50%。
- **早停熔断**：倒序解析快讯，一旦发布时间超出 `REPORT_HOURS_BACK` 设定的时间窗口即自动切断网络请求；同时支持 Google News RSS 与 RSSHub 多镜像节点做网络容灾。
- **快速落盘**：Pydantic V2 `model_dump()` 标准导出 + 纯自增序列 ID，配合 `insert_many(..., ordered=False)` 批量追加落库与 `publish_time` 降序索引。

### TaggerAgent 两阶段 LLM 打标

- **Stage 1** 先判 `category_type`（`宏观` / `行业板块`），严格区分「单只个股/单一板块成交额 → 归其所属东财行业」与「全市场/宏观资金面（两市总量、央行动作、DR007/SHIBOR、社融、M2、LPR、北向全市场、两融余额）→ 国内宏观·市场流动性」。
- **Stage 2** 再细分 `sub_category` / `sector`（国内/国外宏观，或东财 86 个官方行业）。
- 全量覆盖时间窗内每条新闻，**绝不使用手工硬编码标签兜底**；单条打标失败时仅降级为「行业板块 / 其他板块」，不影响整批。

### 择时六面图 35 项指标引擎

基于国盛证券《择时六面图：流动性上行、景气度下行》基准研报，跨 6 大维度（经济面、估值面、资金面、技术面、情绪面、流动性）计算 35 项定量指标：

- **无未来函数**：严格引入保守发布延迟、历史分位数与 Z-score 标准化清洗，任一指标均只使用「截至统一截面」的已知信息。
- **三阶合规流水线**：`01_数据清洗.py`（对齐日期、格式标准化、质量审计）→ `02_指标计算.py`（逐段计算 35 项信号）→ `03_质量检查.py`（自动校验时间连续性与过期检查），由 `run_all.py` 顺序驱动。
- **多线程增量爬取**：`ThreadPoolExecutor` 并行调度 8 大指标组爬虫，显著缩短等待耗时。
- **高保真图表引擎**（`plotter.py`）：自动渲染双 Y 轴对比折线图（含中证 800 基准收盘价、三次样条平滑、看多/看空趋势背景 shading、基准参考线、自适应图例），并生成合规六维综合雷达图 `Radar_Six_Dimensions.png`，动态嵌入研报 PDF。

### 五类 Agent 与买方技能库

- **ExtractorAgent**：对海量资讯执行关联实体抽离、事实提取与情绪标注（只做内容提炼，板块归属交由 TaggerAgent）。
- **TaggerAgent**：两阶段真实打标（见上）。
- **AnalystAgent**：结合两融资金、DR007 利差、ERP 溢价等定量指标，做多板块纯资讯深度推理；由 SkillLoader 动态注入买方分析规则。
- **SynthesizerAgent**：模块化直拼架构，弃用大模型二次汇总全篇，改用确定性 Python 代码直接组装三大章节——`## 一、总评`、`## 二、择时六面图`（代码强控 35 项指标固定格式 + 内嵌走势图）、`## 三、资讯分析`（直拼各板块 Analyst 总结，100% 保留全部板块信息）。
- **AuditorAgent**：纯 LLM 驱动的金融真实性防幻觉合规审查节点，实时比对指标数值与图表一致性。
- **买方技能库**（`skills/premarket-audio-analysis`）：沉淀买方顶级博主 08:00 盘前分析逻辑，含「真金白银」回购审计（区分注销式缩股回购与员工持股/股权激励回购）、Q2 环比加速 (QoQ) 优先于单季同比高增 (YoY)、海外与产业链传导（美股云巨头 Capex 映射国内算力/光模块）、以及「三个收敛」配置（上下游收敛、中外折价收敛、科技/非科技风格收敛）。`app/core/skill_loader.py` 的 `SkillLoader` 在运行时为 Analyst / Synthesizer 动态装载并注入 Prompt 增强上下文。

### 研报合成、校验与高保真 PDF

- **ReportValidator**：校验并修复 Markdown 结构缺陷（标题层级、列表、图片引用），保证产物规范。
- **PDF 编译**：基于 Playwright 无头浏览器，采用 `file://` 协议导航与图片相对路径映射（`charts/...`），解决无头浏览器在 `about:blank` 域下拦截本地图片的问题，保障 35 项指标折线图与雷达图 100% 渲染落盘。
- **双研报输出**：主研报 `market_insight_report.pdf`（资讯，用于预览/落库）+ 择时研报 `timing_report.pdf`；二者元数据带时间戳归档到 MongoDB。

### 上市公司每日投资日报（stock_daily）

面向上市公司的每日自动情报模块，与主研报流水线并行，覆盖「公告 → 分析 → 板块 → 选股 → 业绩预告」全链路：

- **两所并行爬取**：分别驱动上交所、深交所公告爬虫（内部再并行拉页），合并去重后补齐股票简称（上交所接口不返回简称，用东财批量查询补全）。
- **交易日门控**：非交易日直接返回空态，不发空报告。
- **利好消息优先判定**：先按标题做情绪判定分桶——利好直接定论（`利好/利空/中性例行`），「中性待复核」条目再并发下载 PDF → pypdf 解析正文 → DeepSeek 全文判定，落回最终结论；解析为空走标题降级判定，保证单条异常不阻断整批。
- **断点续跑**：按日期维护分析缓存 JSON，已判结果跨运行复用，避免重复调用 LLM。
- **板块强度与选股**：`sector/analyzer` 计算当日板块强度，输出强势/中等板块；`research/picker+scorer` 结合券商研报做选股推荐；`forecast` 抓取当日业绩预告。
- **报告结构**：汇总为 `DailyReportData`（含公告列表按 高/中/低 分级、板块强度、研报选股、业绩预告），经 NaN 消毒后落库 `daily_stock_reports`，前端以《投资日报》页面展示，无数据则返回 `available: false` 空态。

### 自动化调度与邮件投递

- **每日调度器**：`daily_scheduler_7am.py` 常驻 Timer，每日 07:00 自动触发端到端流水线；`--now` 可手动立即触发一次。
- **邮件推送**：`send_daily_report_email.py` 通过 SMTP SSL（端口 465）将单日研报投递至指定团队邮箱。

---

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | FastAPI + Motor(异步 MongoDB) + LangGraph + Pydantic V2 | API、数据抓取、Agent 推理、研报生成 |
| 数据计算 | pandas / akshare / numpy / scipy | 35 项择时指标与特征算子计算 |
| LLM | OpenAI 兼容协议（默认 deepseek-v4-flash） | 萃取、打标、分析、综合、审查 |
| 前端 | Vue3 + Vite + ant-design-vue + ECharts + Pinia | 可视化大屏与研报展示 |
| BFF | Node.js 原生 http（零第三方依赖） | 前后端聚合转发 + CORS |
| 导出 | Playwright | 高保真 PDF 研报编译 |
| 定时/邮件 | 常驻 Timer + SMTP | 每日自动调度与投递 |

---

## 仓库结构（Monorepo）

```text
FinPulse/
├── backend/                # Python 后端：抓取引擎 / Agent 体系 / 择时六面图 / PDF 研报 / 每日投资日报
│   ├── app/
│   │   ├── api/v1/         # REST 路由 (health, news, insights, hexagon, reports, config, automation, stock_daily)
│   │   ├── agents/         # Extractor / Tagger / Analyst / Synthesizer / Auditor 智能体
│   │   ├── core/           # LLMFactory、日志、LangGraph 状态图、排版校验、SkillLoader、板块工具
│   │   ├── data_fetchers/  # 28 大媒体抓取引擎 + 特色特征算子引擎
│   │   ├── db/             # MongoDB 异步驱动、连接池与 SectorGrouper 聚合
│   │   ├── models/         # Pydantic Schema (RawNews / StructuredNews)
│   │   ├── timing_hexagon/ # 择时六面图 35 项指标计算、清洗、质检与图表引擎
│   │   ├── stock_daily/    # 上市公司每日投资日报（公告爬取/分析/板块/选股/业绩预告）
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
│   │   ├── views/          # DashboardView / HexagonView / SectorsView / SectorDetailView / ReportView / StockDailyView
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

## 快速开始

### 环境要求

- Python 3.10+，Node.js 18+，MongoDB（默认 `mongodb://localhost:27017`，库名 `intelligent_research_db`）

### 1. 后端

```bash
cd backend
pip install -e .            # 安装全部依赖（PEP 517/518，统一由 pyproject.toml 管理）
cp .env.example .env        # 按模板创建本地配置，填入 LLM / MongoDB / SMTP 等密钥
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

### 4. 每日自动调度（可选）+ 每日投资日报

```bash
cd backend
python daily_scheduler_7am.py        # 每日 07:00 自动执行整条流水线
python daily_scheduler_7am.py --now  # 手动立即触发一次
python -c "from app.stock_daily.runner import run_for_date; run_for_date()"  # 生成当日投资日报
```

---

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/news/fetch` | 触发全量抓取 |
| GET | `/api/v1/news/flash` | 结构化资讯快讯流 |
| GET | `/api/v1/news/sectors` | 板块聚合统计 |
| GET | `/api/v1/news/by_sector` | 板块下资讯列表 |
| GET | `/api/v1/insights/latest` | 最新研报与择时指标 |
| GET | `/api/v1/hexagon/overview` | 择时六面图概览 |
| GET | `/api/v1/reports/history` | 历史研报列表 |
| GET/POST | `/api/v1/config/subscriptions` | 订阅配置查询与更新 |
| GET/POST | `/api/v1/automation/schedule` | 调度配置查询与更新 |
| GET/POST | `/api/v1/automation/email` | 邮件配置查询与更新 |
| POST | `/api/v1/automation/run-now` | 立即触发一次自动化流程 |
| POST | `/api/v1/stock-daily/run` | 触发一日投资日报运行 |
| GET | `/api/v1/stock-daily/latest` | 最新投资日报 |
| GET | `/api/v1/stock-daily/history` | 投资日报历史列表 |
| GET | `/api/v1/stock-daily/{ann_date}` | 按日期查询投资日报 |

---

## 服务与端口

| 服务 | 技术栈 | 端口 | 说明 |
|---|---|---|---|
| backend | FastAPI + Motor + LangGraph | `8000` | 数据抓取 / Agent 推理 / 研报生成，`/docs` |
| bff | Node.js 原生 http | `3000` | 前后端聚合转发 + CORS，探针 `/bff/health` |
| frontend | Vue3 + Vite + ECharts | `5173` | 可视化大屏（Vite 代理 `/api`、`/static` → 后端） |

---

## 配置

系统通过 `app.core.config.settings`（Pydantic Settings）统一管理敏感凭证与运行时环境变量。请将 `backend/.env.example` 复制为 `backend/.env` 并填入实际值，关键项包括：

```ini
# LLM 配置（全系统统一 Agent 模型，OpenAI 兼容协议）
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_NAME=deepseek-v4-flash

# MongoDB 数据库配置
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=intelligent_research_db

# 研报时间窗口与爬虫超时
REPORT_HOURS_BACK=24.0
CRAWL_REQUEST_TIMEOUT=12.0

# SMTP 邮件推送
SMTP_SERVER=smtp.qq.com
SMTP_PORT=465
SMTP_SENDER_EMAIL=your_email@domain.com
SMTP_AUTH_CODE=your_smtp_auth_code
DEFAULT_RECEIVERS=receiver1@domain.com,receiver2@domain.com

# RSSHub 镜像节点（逗号分隔）
RSSHUB_INSTANCES=https://rsshub.rssforever.com,https://rsshub.app

# 后端服务端口
FASTAPI_PORT=8000
```

完整键名清单见 `backend/.env.example`。`stock_daily` 模块的独立配置（下载并发、分析并发、PDF 目录等）见 `app/stock_daily/config.py`。

---

## 子模块说明

- [backend/README.md](backend/README.md) — 后端架构、Agent 体系、择时六面图、脚本、环境变量详解
- [frontend/README.md](frontend/README.md) — 前端视图、组件、API 对接、构建说明
- [bff/README.md](bff/README.md) — BFF 代理路由、端点、配置说明
