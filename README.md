# ⚡ FinPulse Backend (智能投研后端服务与自动化数据引擎)

> **FinPulse Backend** 是基于 AI Agent 多节点推演与 **国盛证券《择时六面图》** 35 项定量指标计算引擎打造的智能金融投研后端系统。系统支持全量 28 大财经媒体秒级抓取、三阶数据清洗、择时量化图谱计算、全自动化 PDF 金融研报生成以及 SMTP 每日定时邮件推送。

---

## 📁 目录结构 (Directory Structure)

```text
backend/
├── app/                                  # 后端核心应用包 (FastAPI Core & Agent 体系)
│   ├── api/                              # REST API v1 路由层 (health, insights, news, config)
│   ├── agents/                           # LangGraph 多节点 Agent 引擎 (Analyst, Synthesizer, Auditor...)
│   ├── core/                             # LLM 工厂、日志、状态图与排版验证基础设施
│   ├── data_fetchers/                    # 28大媒体抓取引擎与4类特色特征算子
│   ├── db/                               # MongoDB 异步驱动与连接池 (Motor)
│   ├── models/                           # Pydantic Schema 数据校验模型
│   ├── timing_hexagon/                   # 择时六面图 35 项量化指标计算与质量合规引擎
│   └── main.py                           # FastAPI Core 服务主入口 (Port 8000)
│
├── data/                                 # 投研原始数据与 35 项指标数据集
│   ├── raw/                              # 上交所/深交所/中证/期权等原始抓取数据
│   ├── results/                          # 择时六面图 35 项指标计算输出与边界复查 CSV
│   ├── source_data/                      # 基础宏观与行情源数据
│   └── docs/                             # 基准研报与复现简报
│
├── scripts/                              # 运维测试与端到端自动化流水线脚本
│   ├── run_end_to_end_pipeline.py        # 🚀 一键跑通全流程 (抓取->计算->落盘->AI推演->PDF导出)
│   ├── convert_report_to_pdf.py          # Markdown/HTML 研报一键转换为高保真 PDF
│   ├── import_source_data_to_db.py       # 源数据导入 MongoDB 数据库脚本
│   ├── test_mongodb_functions.py         # 🧪 MongoDB 核心接口单元测试脚本
│   ├── test_aggregator.py                # 🧪 NewsAggregator 动态物理簇聚合测试脚本
│   └── view_db.py                        # 本地/远程 MongoDB 数据统计与查验脚本
│
├── logs/                                 # 日志存储目录 (自动轮转落盘 app_pipeline.log)
├── output/                               # 自动生成的 HTML / PDF 每日研报导出目录
├── daily_scheduler_7am.py                # ⏰ 每日早晨 07:00 常驻定时服务脚本
├── send_daily_report_email.py            # 📧 单日研报 SMTP 邮件发送服务脚本
├── requirements.txt                      # 后端 Python 依赖列表
├── .env.example                          # 环境变量配置模板
└── README.md                             # 项目说明文档
```

---

## 🔥 核心功能与架构特性

### 1. 全量 28 大财经媒体与投研源秒级并发抓取 (`app/data_fetchers/flash_news_fetcher.py` & `scripts/run_end_to_end_pipeline.py`)
- **覆盖数据源与源头纯化**：新浪财经、东方财富、财联社、华尔街见闻、36氪、IT之家、钛媒体、EE Times、机器之心、量子位、Reuters、Bloomberg、Yahoo Finance，扩展“高股息/红利”、“低估值/破净/回购”与“大消费/白酒/零售”三大垂直板块。
- **并发并行抓取引擎 (`Concurrent Parallel Crawling`)**：使用 `asyncio.gather` 结合 `asyncio.to_thread` 将 28 大媒体快讯异步拉取与 35 项择时六面图指标多源爬虫并行化并发执行，Stage 1 抓取效率提升近 50%。
- **数据源绑定固定 Sector 标签 (`Source-to-Sector Binding`)**：抓取阶段各数据源直接绑定其固定主题 Sector 标签（如国内宏观、海外宏观、半导体芯片、硬科技/AI、高股息、低估值、大消费等），后续扩展新源无需改动后端计算链条。
- **早停熔断机制 (`Early-Exit Short-Circuit`)**：倒序解析快讯，一旦发布时间超出指定窗口 (由 `settings.REPORT_HOURS_BACK` 全局控制) 自动切断网络请求，同时支持 Google News RSS 智能兜底容灾。
- **强类型 Schema & 极速批量落盘**：采用 Pydantic V2 `model_dump()` 标准导出与纯自增序列 ID（`news_1`, `news_2` ...），结合 `insert_many(..., ordered=False)` 批量直接追加落盘与 `publish_time` 时间降序索引。

### 2. 择时六面图 35 项定量指标计算与图表引擎 (`app/timing_hexagon/`)
基于国盛证券《择时六面图：流动性上行、景气度下行》基准研报：
- **无未来函数设计**：严格引入保守发布延迟、历史分位数与 Z-score 标准化清洗。
- **多线程并发增量爬取**：`run_all.py` 采用 `ThreadPoolExecutor` 并行调度 8 大指标组爬虫任务，显著缩短爬取等待耗时。
- **三阶合规流水线**：
  1. `01_数据清洗.py`：对齐日期、格式标准化与基础质量审计。
  2. `02_指标计算.py`：逐段计算 35 项择时信号（流动性、宏观、估值、资金、技术、情绪及期权等 6 大维度）。
  3. `03_质量检查.py`：自动校验 35 项指标时间连续性与数据过期检查。
- **高保真图表渲染引擎 (`app/timing_hexagon/plotter.py`)**：
  - 自动渲染 35 项量化指标双 Y 轴对比折线图（含中证 800 基准收盘价、三次样条曲线平滑、看多肉色/看空浅绿趋势背景区间 shading、基准参考线及顶部自适应图例）。
  - 自动生成合规六维综合雷达图 (`Radar_Six_Dimensions.png`)，仅包含可聚合指标均值与 0 轴中性线。
  - 动态集成入研报 PDF：Synthesizer Agent 在 Markdown `## 二、择时六面图` 章节中自动嵌入雷达图与各指标高清折线图，经 Playwright PDF 引擎编译为标准金融研报图表。

### 3. 配置驱动与严格 Fail-Fast 多节点 Agent 引擎 (`app/agents/` & `app/core/pipeline_graph.py`)
- **配置驱动架构 (Env-Driven & Fail-Fast)**：移除所有硬编码参数默认值，强制从 `.env` 读取配置并启用 `override=True`；彻底移除所有 Heuristic 降级/兜底硬规则（包括 AnalystAgent、SynthesizerAgent、AuditorAgent 与 Playwright PDF 引擎），遇到异常即严格抛错并记录 App Logger。
- **动态日期约束**：Prompt 模板动态注入系统当前实时日期 (`today_str`)，强约束研报标题及一级 Markdown 标题必须以当前实时日期开头，确保内容时效性。
- **原生全异步 Node 架构**：全链路采用 `async def` 异步节点定义与单统一事件循环，避免反复创建/销毁事件循环的开销，并全局复用高并发 MongoDB 连接池。
- **Extractor Agent**：对海量资讯执行关联实体抽离、事实提取与情绪标注，并严格继承保留数据源落库时的固定 Sector 标签。
- **SectorGrouper 板块分类分组**：彻底取消聚类算法，依据卡片原生 `sector` 分类标签进行高效字典 `Group-By` 分组，无缝兼容任意新增行业。
- **Analyst Agent**：结合两融资金、DR007 利差、ERP 溢价等定量指标执行多板块纯资讯深度推理。
- **Synthesizer Agent（模块化直拼架构）**：废除大模型二次汇总全篇，采用确定性 Python 代码直接组装三大章节：
  - **`## 一、总评`**：Synthesizer CIO Agent 专精生成全局策略总揽、风险警示、跨行业传导链与仓位建议。
  - **`## 二、择时六面图`**：代码强控制 6 大维度 35 项指标固定格式输出（各维度 3~4 个指标换行单列），配合 LLM 快速生成各面总结论。
  - **`## 三、资讯分析`**：代码直拼各板块 Analyst 总结，100% 完整保留所有板块信息，避免上下文受限导致遗漏。
- **Auditor Agent**：纯 LLM 驱动的金融真实性与防幻觉合规审查节点，实时比对指标数值与图表一致性。
- **Report Validator**：校验修复 Markdown 结构缺陷，编译高保真金融 PDF 研报。

### 4. 自动化定时调度与邮件投递 (`daily_scheduler_7am.py` & `send_daily_report_email.py`)
- **常驻 Timer 服务**：每日早晨 `07:00:00` 自动触发端到端流水线。
- **高保真 PDF 编译**：基于 Playwright 无头浏览器导出 PDF。
- **SMTP 邮件推送**：通过 SSL (端口 465) 自动将单日研报投递至指定团队邮箱。

### 5. 全流程正式化去 Emoji 改造与跨平台编码稳定性 (`scripts/run_end_to_end_pipeline.py` & `scripts/convert_report_to_pdf.py`)
- **去视觉 Emoji 规范**：全系统移除控制台日志、Loguru 输出、Agent Prompt 模板及 PDF/Markdown 研报中的 Emoji 符号，替换为买方金融机构合规的方括号标记（如 `[看多]`、`[看空]`、`[风险警示]`、`[传导链条]` 等）。
- **子进程 UTF-8 编码防暴**：主流程管道在 Windows 环境下的 `subprocess.run` 中显式添加 `encoding="utf-8"` 与 `errors="replace"`，彻底避免非 GBK 字符导致的 `UnicodeDecodeError` 及子进程崩溃。
- **Playwright 本地资源跨域与 PDF 编译优化**：采用 `file://` 协议导航 (`page.goto(html_path.resolve().as_uri(), wait_until="networkidle")`) 与图片相对路径映射（`charts/...`），解决无头浏览器在 `about:blank` 域下拦截本地图片的问题，保障 35 项指标折线图与雷达图 100% 渲染落盘。

---

## 🛠️ 环境配置指南 (`.env`)

本系统通过 `app.core.config.settings` 统一管理敏感凭证与运行时环境变量（本地已配置 `.gitignore`，请勿将 `.env` 提交至代码仓库）。

复制模版文件创建本地配置：
```bash
cp .env.example .env
```

`.env` 常用参数说明：
```ini
# 1. LLM 配置
LLM_API_KEY=your_deepseek_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
FLASH_MODEL_NAME=deepseek-v4-flash
PRO_MODEL_NAME=deepseek-reasoner

# 2. MongoDB 数据库配置
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=intelligent_research_db

# 3. 后端服务配置
FASTAPI_PORT=8000
```

> 💡 **Dummy Mock 降级保护**：当 `LLM_API_KEY` 为空或使用 `mock` 前缀时，系统会自动切入内置 `DummyMockLLM` 模式，无 Token 消耗即可跑通完整流程。

---

## 🚀 快速开始

### 1. 安装依赖
支持 Python 3.10+ 环境：
```bash
pip install -r requirements.txt
```

### 2. 运行端到端流水线 (Data -> Hexagon -> Agents -> PDF)
```bash
python scripts/run_end_to_end_pipeline.py
```
*运行完成后，研报结果将自动保存至 `output/` 目录下（包含最新研报 `market_insight_report.pdf` 以及在 MongoDB 中自动归档记录的带时间戳文件 `智能投研综合研报_择时六面图_YYYYMMDD_HHMMSS.pdf`）。*

### 3. 启动 FastAPI 交互式后端服务
```bash
python app/main.py
# 或使用 uvicorn
uvicorn app.main:app --reload --port 8000
```
访问 API 文档地址: `http://localhost:8000/docs`

### 4. 启动 07:00 每日自动化调度器
```bash
# 启动常驻定时服务 (每天 07:00 自动执行)
python daily_scheduler_7am.py

# 手动立即测试一次整套调度与邮件发送
python daily_scheduler_7am.py --now
```

### 5. 单独触发研报邮件发送
```bash
python send_daily_report_email.py
```

---

## 🔒 代码规范与安全说明

- `.env` 密钥配置文件已加入 `.gitignore`。
- 生成的 `logs/*.log` 与 `output/*.pdf/html` 不会上传至 Git 远程仓库。
- `.env.example` 提供无敏感信息的配置模版，供团队成员部署使用。
