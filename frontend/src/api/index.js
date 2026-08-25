import http from './http'

// 系统健康
export const fetchHealth = () => http.get('/api/v1/health')

// 最新研报
export const fetchLatestInsight = () => http.get('/api/v1/insights/latest')

// 历史研报列表
export const fetchReportHistory = (limit = 20) =>
  http.get('/api/v1/reports/history', { params: { limit } })

// 快讯流 (limit 用于展示分页；传 0 表示拉取 24h 时间窗内全量资讯，不做截断)
export const fetchFlashNews = (limit = 0) =>
  http.get('/api/v1/news/flash', { params: { limit } })

// 触发全量抓取
export const triggerFetchNews = () => http.post('/api/v1/news/fetch')

// 择时六面图概览
export const fetchHexagonOverview = () => http.get('/api/v1/hexagon/overview')

// 板块聚合统计
export const fetchSectors = () => http.get('/api/v1/news/sectors')

// 板块内资讯 (limit=0 表示拉取该板块 24h 时间窗内全量资讯，不做截断)
export const fetchSectorNews = (sector, limit = 0) =>
  http.get('/api/v1/news/by_sector', { params: { sector, limit } })

// 订阅配置
export const fetchSubscriptions = () => http.get('/api/v1/config/subscriptions')
export const updateSubscriptions = (payload) =>
  http.post('/api/v1/config/subscriptions', payload)
