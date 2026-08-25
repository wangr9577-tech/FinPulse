# 🔀 FinPulse BFF (Node.js 聚合转发服务)

> **FinPulse BFF**（Backend For Frontend）是介于 Vue3 前端与 FastAPI 后端之间的聚合网关，基于 **Node.js 原生 `http` 模块**实现（**零第三方依赖**，`node server.js` 即可启动），为前端提供统一 API 路由聚合、跨域 CORS 支持与探针转发。

- 端口：`3000`
- 后端目标：`http://127.0.0.1:8000`

---

## 📁 结构

```text
bff/
├── server.js        # 原生 http 服务 + 路由转发逻辑
├── .env             # 端口 / 后端地址 / CORS 配置（无敏感信息）
├── package.json
└── README.md
```

---

## 🚀 快速开始

```bash
cd bff
node server.js            # 或 npm run start / npm run dev (node --watch)
```

健康检查：`GET http://localhost:3000/bff/health`

---

## ⚙️ 配置 (`.env`)

```ini
PORT=3000
FASTAPI_BASE_URL=http://127.0.0.1:8000
CORS_ORIGIN=*
NODE_ENV=development
```

---

## 🔌 代理端点

| 方法 | 路径 | 转发到后端 | 说明 |
|---|---|---|---|
| GET | `/bff/health` | — | 本地探针，并探测后端健康度 |
| GET | `/api/v1/insights/latest` | `/api/v1/insights/latest` | 最新研报 / 择时指标 |
| GET/POST | `/api/v1/config/subscriptions` | `/api/v1/config/subscriptions` | 订阅配置查询与更新 |
| GET | `/api/v1/news/flash` | `/api/v1/news/flash` | 结构化资讯快讯流 |

> BFF 同时处理 **CORS**（`Access-Control-Allow-Origin: *`），解决前端开发期的跨域问题。其中 `/api/v1/news/flash` 转发的是**结构化库**内容（板块标签由后端 TaggerAgent 真实打标）。

---

## ⚠️ 容灾

若后端 FastAPI 不可达，BFF 会返回 `503` 并附带 `fallback_mode: true` 的「服务暂时不可用」提示，不直接抛异常中断。
