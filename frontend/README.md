# FinPulse Frontend (Vue3 可视化大屏)

> **FinPulse Frontend** 是智能投研引擎的前端可视化大屏，基于 **Vue3 + Vite + ant-design-vue + ECharts + Pinia** 构建，用于展示机构级投研大屏：资讯总览、择时六面图、板块聚合与板块详情。

- 端口：`5173`（Vite 开发服务器）
- 开发期通过 Vite 代理将 `/api`、`/static` 转发到后端 **FastAPI (`:8000`)**。

---

## 目录结构

```text
frontend/
├── src/
│   ├── views/
│   │   ├── DashboardView.vue      # 总览大屏 (快讯流 / 研报卡片)
│   │   ├── HexagonView.vue        # 择时六面图 (35 项指标 / 雷达图)
│   │   ├── SectorsView.vue        # 板块聚合统计
│   │   └── SectorDetailView.vue   # 板块详情资讯
│   ├── components/
│   │   └── EChart.vue             # ECharts 通用封装组件
│   ├── router/
│   │   └── index.js               # vue-router 路由
│   ├── api/
│   │   ├── http.js                # axios 实例与拦截器
│   │   └── index.js               # 后端接口聚合
│   ├── App.vue
│   ├── main.js
│   └── style.css
├── index.html
├── vite.config.js                 # 端口 / 代理 / 构建配置
├── package.json
└── .gitignore
```

---

## 技术栈

| 依赖 | 用途 |
|---|---|
| vue | 视图框架 |
| vue-router | 路由 |
| pinia | 状态管理 |
| ant-design-vue | UI 组件库 |
| @ant-design/icons-vue | 图标 |
| echarts | 数据可视化（择时六面图 / 雷达图 / K 线等） |
| axios | HTTP 请求 |
| dayjs | 时间格式化 |
| marked | Markdown 渲染（研报正文） |
| vite | 构建/开发服务器 |
| @vitejs/plugin-vue | Vue3 单文件组件支持 |

---

## 快速开始

### 环境要求

- Node.js 18+
- 后端服务已启动（FastAPI `:8000`）

### 安装与运行

```bash
cd frontend
npm install
npm run dev        # 开发服务器 -> http://localhost:5173
```

### 生产构建

```bash
npm run build      # 产物输出到 dist/
npm run preview    # 本地预览构建产物
```

---

## 代理配置 (`vite.config.js`)

开发期前端不直接跨域访问后端，而是通过 Vite 代理：

```js
server: {
  host: '0.0.0.0',
  port: 5173,
  proxy: {
    '/api':     { target: 'http://127.0.0.1:8000', changeOrigin: true },
    '/static':  { target: 'http://127.0.0.1:8000', changeOrigin: true },
  },
}
```

- `/api` —— 后端 REST 接口（`/news/flash`、`/news/sectors`、`/news/by_sector`、`/insights/latest` 等）
- `/static` —— 后端生成的研报静态资源（HTML / PDF）

---

## 对接后端接口

| 前端页面 | 后端接口 | 说明 |
|---|---|---|
| 总览大屏 | `GET /api/v1/news/flash` | 结构化资讯快讯流 |
| 板块聚合 | `GET /api/v1/news/sectors` | 按板块统计卡片数 |
| 板块详情 | `GET /api/v1/news/by_sector?sector=...` | 板块下资讯列表 |
| 择时六面图 | `GET /api/v1/insights/latest` | 最新研报与择时指标（经 BFF 转发） |

> 板块标签的权威来源是后端 **TaggerAgent 落库结果**（`structured_news_collection`）。前端只展示结构化库内容。
