/**
 * Node.js BFF (Backend For Frontend) 路由服务
 * 职责：
 * 1. 为 Vue3 前端提供统一 API 路由聚合与跨域 CORS 支持
 * 2. 探针与转发前端请求至 FastAPI Core 后端逻辑层
 * 3. 前端配置拼装与研报结构轻量二次加工
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

// 读取 .env 环境变量
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
  const envConfig = fs.readFileSync(envPath, 'utf8');
  envConfig.split('\n').forEach(line => {
    const [key, val] = line.split('=');
    if (key && val) {
      process.env[key.trim()] = val.trim();
    }
  });
}

const PORT = parseInt(process.env.PORT || '3000', 10);
const FASTAPI_BASE_URL = process.env.FASTAPI_BASE_URL || 'http://127.0.0.1:8000';

console.log(`[BFF Node.js Engine] 启动中... 端口: ${PORT}, FastAPI 目标: ${FASTAPI_BASE_URL}`);

// 通用 HTTP 请求辅助函数
async function forwardToFastAPI(endpoint, method = 'GET', body = null) {
  const targetUrl = `${FASTAPI_BASE_URL}${endpoint}`;
  try {
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    };
    if (body && (method === 'POST' || method === 'PUT')) {
      options.body = JSON.stringify(body);
    }
    const response = await fetch(targetUrl, options);
    const data = await response.json();
    return { status: response.status, data };
  } catch (err) {
    console.error(`[BFF Proxy Error] 无法连接到 FastAPI Core (${targetUrl}):`, err.message);
    return {
      status: 503,
      data: {
        code: 503,
        message: `FastAPI Core 服务暂时不可用 (${err.message})`,
        fallback_mode: true
      }
    };
  }
}

// HTTP 原生服务器 (不依赖第三方 node_modules 即可直接启动，保障极高稳定性)
const server = http.createServer(async (req, res) => {
  // CORS 响应头
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const urlParts = req.url.split('?');
  const pathName = urlParts[0];

  // 1. BFF 本地探针接口: GET /bff/health
  if (pathName === '/bff/health' && req.method === 'GET') {
    const fastApiStatus = await forwardToFastAPI('/api/v1/health');
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({
      code: 200,
      service: 'Node.js BFF Router Service',
      port: PORT,
      fastapi_backend: {
        target: FASTAPI_BASE_URL,
        status: fastApiStatus.status === 200 ? 'healthy' : 'degraded',
        response: fastApiStatus.data
      }
    }, null, 2));
    return;
  }

  // 2. 研报情报数据透传接口: GET /api/v1/insights/latest
  if (pathName === '/api/v1/insights/latest' && req.method === 'GET') {
    const result = await forwardToFastAPI('/api/v1/insights/latest');
    res.writeHead(result.status, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(result.data));
    return;
  }

  // 3. 配置更新/获取接口: /api/v1/config/subscriptions
  if (pathName === '/api/v1/config/subscriptions') {
    if (req.method === 'GET') {
      const result = await forwardToFastAPI('/api/v1/config/subscriptions', 'GET');
      res.writeHead(result.status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(result.data));
      return;
    } else if (req.method === 'POST') {
      let bodyData = '';
      req.on('data', chunk => { bodyData += chunk; });
      req.on('end', async () => {
        try {
          const parsed = JSON.parse(bodyData || '{}');
          const result = await forwardToFastAPI('/api/v1/config/subscriptions', 'POST', parsed);
          res.writeHead(result.status, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify(result.data));
        } catch (e) {
          res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ code: 400, message: 'Invalid JSON Body' }));
        }
      });
      return;
    }
  }

  // 4. 增量快讯接口: GET /api/v1/news/flash
  if (pathName === '/api/v1/news/flash' && req.method === 'GET') {
    const result = await forwardToFastAPI(req.url, 'GET');
    res.writeHead(result.status, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(result.data));
    return;
  }

  // 默认根路径或 404
  if (pathName === '/') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({
      message: 'Welcome to Intelligent Equity Research Engine Node.js BFF Service',
      bff_health: '/bff/health',
      proxied_endpoints: [
        '/api/v1/insights/latest',
        '/api/v1/config/subscriptions',
        '/api/v1/news/flash'
      ]
    }));
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify({ code: 404, message: 'BFF Route Not Found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ [BFF Node.js] 路由探针服务已成功运行于 http://127.0.0.1:${PORT}`);
});
