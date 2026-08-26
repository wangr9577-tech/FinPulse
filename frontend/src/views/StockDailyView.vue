<script setup>
import { ref, onMounted, computed, h } from 'vue'
import {
  Card, Row, Col, Statistic, Tag, Table, Empty, Button, Space, Spin,
  Alert, Descriptions, Divider, Collapse, Badge, Progress, message,
} from 'ant-design-vue'
import {
  ReloadOutlined, PlayCircleOutlined, FundProjectionScreenOutlined,
  ThunderboltOutlined, FileTextOutlined, LineChartOutlined, StarOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import {
  fetchStockDailyLatest, fetchStockDailyDate, fetchStockDailyHistory, runStockDaily,
} from '../api'

const loading = ref(true)
const running = ref(false)
const report = ref(null)          // GET 返回的整份 doc：{date, available, data, run_meta, generated_at}
const history = ref([])
const selectedDate = ref(dayjs())

// ---------- 计算 ----------
const daily = computed(() => report.value?.data || null)
const ann = computed(() => daily.value?.announcements || null)
const strong = computed(() => daily.value?.sectors_strong || [])
const medium = computed(() => daily.value?.sectors_medium || [])
const picks = computed(() => daily.value?.stock_picks || null)
const forecasts = computed(() => daily.value?.forecasts || [])
const highRows = computed(() => ann.value?.high_level || [])
const mediumRows = computed(() => ann.value?.medium_level || [])
const available = computed(() => report.value ? report.value.available !== false && !!daily.value : false)

function todayStr() {
  return dayjs().format('YYYY-MM-DD')
}
function fmtSelectedDate() {
  return selectedDate.value ? dayjs(selectedDate.value).format('YYYY-MM-DD') : todayStr()
}

// ---------- 格式化 ----------
function fmtMoney(v) {
  const n = Number(v)
  if (!n && n !== 0) return '-'
  const abs = Math.abs(n)
  if (abs >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(0)
}
function fmtPct(v) {
  const n = Number(v)
  if (!n && n !== 0) return '-'
  return n.toFixed(2) + '%'
}
function fmtUpSide(v) {
  const n = Number(v)
  if (!n && n !== 0) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
// 目标价空间：有正空间正常显示；为 0 时区分"研报未披露目标价"与"目标价=现价"。
// 东财 reportapi 的 indvAimPriceT/L 绝大多数为空，故多数为"未披露"，不应误导为 0%。
function pickUpside(p) {
  const v = Number(p.target_upside)
  if (v > 0) return { text: fmtUpSide(v), color: '#cf1322' }
  const hasTarget = Array.isArray(p.reports) && p.reports.some((r) => {
    const rp = r?.report
    return rp && (Number(rp.aim_price_t) > 0 || Number(rp.aim_price_l) > 0)
  })
  return hasTarget ? { text: fmtUpSide(v), color: '#8c8c8c' } : { text: '未披露', color: '#8c8c8c' }
}
function fmtInt(v) {
  const n = Number(v)
  if (n === null || n === undefined || Number.isNaN(n)) return '-'
  return n.toLocaleString('zh-CN')
}

function levelColor(level) {
  return level === '高' ? 'red' : level === '中' ? 'orange' : 'default'
}
function sentimentColor(s) {
  return s === '利好' ? 'red' : s === '利空' ? 'green' : 'default'
}
function boardColor(type) {
  return type === 'industry' ? 'blue' : 'purple'
}
function gradeColor(g) {
  return g === '强' ? 'red' : g === '中' ? 'orange' : 'default'
}
function forecastColor(t) {
  const map = {
    预增: 'red', 扭亏: 'magenta', 略增: 'orange', 续盈: 'orange',
    预减: 'green', 略减: 'green', 续亏: 'green', 首亏: 'green', 不确定: 'default',
  }
  return map[t] || 'default'
}
function ratingColor(r) {
  const map = { 买入: 'volcano', 增持: 'orange', 中性: 'blue', 减持: 'green', 卖出: 'default' }
  return map[r] || 'default'
}
// StockPick 不携带评级字段，评级取自其引用的首份研报 (reports[].report.rating)
function pickRating(p) {
  if (p && Array.isArray(p.reports) && p.reports.length && p.reports[0].report) {
    return p.reports[0].report.rating || ''
  }
  return ''
}

// ---------- 表格内嵌 render 组件 ----------
function hTagBoard(record) {
  return h('span', null, [
    h(Tag, { color: boardColor(record.board_type) }, () => (record.board_type === 'industry' ? '行业' : '概念')),
    record.board_name,
  ])
}
function hProgress(text) {
  const v = Number(text) || 0
  return h('div', { style: 'display:flex;align-items:center;gap:6px' }, [
    h(Progress, { percent: v, size: 'small', showInfo: false, style: 'width:70px' }),
    h('span', null, v.toFixed(1)),
  ])
}

// ---------- 表格列 ----------
const strongColumns = [
  { title: '板块', dataIndex: 'board_name', width: 160, fixed: 'left',
    customRender: ({ record }) => hTagBoard(record) },
  { title: '评分', dataIndex: 'score', width: 130,
    customRender: ({ text }) => hProgress(text) },
  { title: '涨幅', dataIndex: 'pct_change', width: 90,
    customRender: ({ text }) => `${fmtPct(text)}` },
  { title: '资金净流入', dataIndex: 'net_inflow', width: 120,
    customRender: ({ text }) => fmtMoney(text) },
  { title: '上涨家数', dataIndex: 'up_count', width: 90,
    customRender: ({ text }) => fmtInt(text) },
  { title: '领涨股', dataIndex: 'leader_stocks', width: 180,
    customRender: ({ text }) => (Array.isArray(text) && text.length ? text.join('、') : '-') },
  { title: '券商观点', dataIndex: 'research_note', width: 140,
    customRender: ({ text }) => (text ? text : '-') },
  { title: 'DeepSeek 点评', dataIndex: 'comment', width: 260, ellipsis: true,
    customRender: ({ text }) => (text ? text : '-') },
]

const forecastColumns = [
  { title: '代码', dataIndex: 'stock_code', width: 100 },
  { title: '简称', dataIndex: 'stock_name', width: 110 },
  { title: '预告类型', dataIndex: 'forecast_type', width: 110,
    customRender: ({ text }) => (text ? h(Tag, { color: forecastColor(text) }, () => text) : '-') },
  { title: '净利润变动', key: 'change', width: 130,
    customRender: ({ record }) => fC(record) },
  { title: '预告内容', dataIndex: 'content', ellipsis: true },
]

function fC(r) {
  const lo = r.change_lower
  const hi = r.change_upper
  if (lo == null && hi == null) return '-'
  if (lo == null) return fmtPct(hi)
  if (hi == null) return fmtPct(lo)
  return `${fmtPct(lo)} ~ ${fmtPct(hi)}`
}

// ---------- 加载 ----------
async function loadLatest() {
  try {
    const res = await fetchStockDailyLatest()
    report.value = res?.data || null
  } catch (e) {
    console.error('加载最新投资日报失败:', e)
  }
}
async function loadDate(d) {
  loading.value = true
  try {
    const res = await fetchStockDailyDate(d)
    report.value = res?.data || null
  } catch (e) {
    console.error('加载当日投资日报失败:', e)
  } finally {
    loading.value = false
  }
}
async function loadHistory() {
  try {
    const res = await fetchStockDailyHistory(20)
    history.value = res?.data || []
  } catch (e) {
    console.error('加载投资日报历史失败:', e)
  }
}
async function loadAll() {
  loading.value = true
  try {
    await Promise.allSettled([loadLatest(), loadHistory()])
  } finally {
    loading.value = false
  }
}

function pollDate(d) {
  return new Promise((resolve) => {
    let tries = 0
    const timer = setInterval(async () => {
      tries += 1
      try {
        const res = await fetchStockDailyDate(d)
        if (res?.data?.run_meta) {
          clearInterval(timer)
          resolve()
          return
        }
      } catch (e) { /* 忽略单次失败 */ }
      if (tries >= 30) {
        clearInterval(timer)
        resolve()
      }
    }, 5000)
  })
}

async function onRun() {
  const d = fmtSelectedDate()
  running.value = true
  message.info(`已开始运行 ${d} 投资日报，完成后自动刷新`)
  try {
    await runStockDaily(d)
    await pollDate(d)
    await loadDate(d)
  } catch (e) {
    message.error('触发运行失败')
  } finally {
    running.value = false
  }
}

function onQuery() {
  loadDate(fmtSelectedDate())
}

onMounted(loadAll)
</script>

<template>
  <div class="stock-daily-view">
    <div class="page-header">
      <Space>
        <span class="page-title"><FundProjectionScreenOutlined /> 每日投资日报</span>
        <span class="page-sub">上市公司公告 · 强势板块 · 每日选股 · 业绩预告</span>
      </Space>
      <Space>
        <a-date-picker v-model:value="selectedDate" :allow-clear="false" />
        <Button @click="onQuery">
          <template #icon><ReloadOutlined /></template>
          查询
        </Button>
        <Button type="primary" :loading="running" @click="onRun">
          <template #icon><PlayCircleOutlined /></template>
          {{ running ? '运行中' : '运行' }}
        </Button>
      </Space>
    </div>

    <!-- 运行状态 / 空态 -->
    <Spin :spinning="loading">
      <div v-if="!available && !running" class="empty-wrap">
        <Empty description="今日暂无投资日报数据（可能未运行或非交易日）">
          <template #extra>
            <Button type="primary" @click="onRun">
              <template #icon><PlayCircleOutlined /></template>
              立即运行今日投资日报
            </Button>
          </template>
        </Empty>
      </div>

      <template v-else-if="daily">
        <!-- run_meta / 数据源告警 -->
        <Alert
          v-if="ann && ann.sources_note"
          type="warning"
          show-icon
          :message="ann.sources_note"
          style="margin-bottom: 16px; border-radius: 6px;"
        />
        <Alert
          v-if="picks && picks.degraded"
          type="warning"
          show-icon
          message="选股推荐为降级结果（研报数据不可达）"
          style="margin-bottom: 16px; border-radius: 6px;"
        />

        <!-- KPI 概览 -->
        <Row :gutter="[16, 16]">
          <Col :xs="24" :sm="12" :lg="5">
            <Card hoverable class="kpi-card">
              <Statistic title="利好公告" :value="ann ? ann.total : 0" :value-style="{color:'#cf1322'}">
                <template #prefix><FileTextOutlined style="color:#cf1322" /></template>
              </Statistic>
            </Card>
          </Col>
          <Col :xs="24" :sm="12" :lg="5">
            <Card hoverable class="kpi-card">
              <Statistic title="强势板块" :value="strong.length" :value-style="{color:'#fa8c16'}">
                <template #prefix><ThunderboltOutlined style="color:#fa8c16" /></template>
              </Statistic>
            </Card>
          </Col>
          <Col :xs="24" :sm="12" :lg="5">
            <Card hoverable class="kpi-card">
              <Statistic title="中等板块" :value="medium.length" :value-style="{color:'#faad14'}">
                <template #prefix><LineChartOutlined style="color:#faad14" /></template>
              </Statistic>
            </Card>
          </Col>
          <Col :xs="24" :sm="12" :lg="5">
            <Card hoverable class="kpi-card">
              <Statistic title="业绩预告" :value="forecasts.length" :value-style="{color:'#2f54eb'}">
                <template #prefix><FileTextOutlined style="color:#2f54eb" /></template>
              </Statistic>
            </Card>
          </Col>
          <Col :xs="24" :lg="4">
            <Card hoverable class="kpi-card">
              <Statistic title="选股推荐" :value="picks ? picks.picks.length : 0" :value-style="{color:'#13c2c2'}">
                <template #prefix><StarOutlined style="color:#13c2c2" /></template>
              </Statistic>
            </Card>
          </Col>
        </Row>

        <!-- 每日选股推荐 -->
        <Card class="block-card" title="每日选股推荐" :bordered="true">
          <template #extra>
            <span v-if="daily.date" style="color:#8c8c8c; font-size:12px;">{{ daily.date }}</span>
          </template>
          <div v-if="picks && picks.picks && picks.picks.length">
            <Row :gutter="[16, 16]">
              <Col v-for="(p, i) in picks.picks" :key="p.stock_code" :xs="24" :lg="12">
                <Card size="small" class="pick-card">
                  <div class="pick-head">
                    <Space>
                      <Tag color="red" :style="{fontWeight:600}">{{ i + 1 }}</Tag>
                      <span class="stock-name">{{ p.stock_name }}</span>
                      <span class="stock-code">{{ p.stock_code }}</span>
                    </Space>
                    <Tag :color="ratingColor(pickRating(p))">{{ pickRating(p) || '-' }}</Tag>
                  </div>
                  <div class="pick-upside">
                    <span>目标价空间</span>
                    <b :style="{color: pickUpside(p).color}">{{ pickUpside(p).text }}</b>
                  </div>
                  <div class="pick-reason">{{ p.reason || '-' }}</div>
                  <Divider style="margin:8px 0" />
                  <div class="pick-brief">
                    <strong>公告要点</strong>
                    <p>{{ p.ann_brief || '-' }}</p>
                  </div>
                  <div class="pick-brief">
                    <strong>研报观点</strong>
                    <p>{{ p.research_brief || '-' }}</p>
                  </div>
                  <div v-if="p.risk_note" class="pick-risk">
                    <strong style="color:#cf1322">风险提示</strong> {{ p.risk_note }}
                  </div>
                  <Collapse v-if="p.reports && p.reports.length" ghost>
                    <Collapse.Panel :key="p.stock_code + i" header="查看完整研报观点">
                      <div v-for="(rpt, ri) in p.reports" :key="ri" class="rpt-item">
                        <div class="rpt-meta">
                          <Tag :color="ratingColor(rpt.report.rating)">{{ rpt.report.rating || '-' }}</Tag>
                          <span>{{ rpt.report.org_name }}</span>
                          <span>{{ rpt.report.researcher }}</span>
                          <span>{{ rpt.report.publish_date }}</span>
                          <span v-if="rpt.target_price">目标价 {{ rpt.target_price }}元</span>
                          <a v-if="rpt.report.pdf_url" :href="rpt.report.pdf_url" target="_blank" style="margin-left:auto">PDF</a>
                        </div>
                        <div class="rpt-title">{{ rpt.report.title }}</div>
                        <div v-if="rpt.summary" class="rpt-txt">摘要：{{ rpt.summary }}</div>
                        <div v-if="rpt.highlights && rpt.highlights.length" class="rpt-list">
                          <div v-for="(hl, hi) in rpt.highlights" :key="hi">· {{ hl }}</div>
                        </div>
                        <div v-if="rpt.risks && rpt.risks.length" class="rpt-list risk">
                          <div v-for="(rk, rik) in rpt.risks" :key="rik">警示：{{ rk }}</div>
                        </div>
                      </div>
                    </Collapse.Panel>
                  </Collapse>
                </Card>
              </Col>
            </Row>
          </div>
          <Empty v-else description="今日无选股推荐" />
        </Card>

        <!-- 强势板块 -->
        <Card class="block-card" title="强势板块" :bordered="true">
          <Table
            :columns="strongColumns"
            :data-source="strong"
            size="small"
            row-key="board_name"
            :pagination="false"
            :scroll="{ x: 1200 }"
          >
            <template #emptyText><Empty description="暂无强势板块数据" /></template>
          </Table>
        </Card>

        <!-- 中等板块 -->
        <Card v-if="medium.length" class="block-card" title="中等板块" :bordered="true">
          <Table
            :columns="strongColumns"
            :data-source="medium"
            size="small"
            row-key="board_name"
            :pagination="false"
            :scroll="{ x: 1200 }"
          >
            <template #emptyText><Empty description="暂无数据" /></template>
          </Table>
        </Card>

        <!-- 业绩预告 -->
        <Card class="block-card" title="业绩预告" :bordered="true">
          <Table
            :columns="forecastColumns"
            :data-source="forecasts"
            size="small"
            row-key="stock_code"
            :pagination="{ pageSize: 10 }"
          >
            <template #emptyText><Empty description="今日暂无业绩预告" /></template>
          </Table>
        </Card>

        <!-- 利好公告 -->
        <Row :gutter="[16, 16]">
          <Col :xs="24" :lg="12">
            <Card class="block-card" title="利好公告 · 高" :bordered="true">
              <div v-if="highRows.length" class="ann-scroll">
                <div v-for="(row, ri) in highRows" :key="ri" class="ann-row">
                  <div class="ann-head">
                    <Tag :color="levelColor(row.analysis.level)">{{ row.analysis.level }}</Tag>
                    <Tag :color="sentimentColor(row.analysis.sentiment)">{{ row.analysis.sentiment }}</Tag>
                    <span class="ann-title">{{ row.announcement.title }}</span>
                  </div>
                  <div class="ann-meta">
                    <span>{{ row.announcement.stock_name }} {{ row.announcement.stock_code }}</span>
                    <a v-if="row.announcement.pdf_url" :href="row.announcement.pdf_url" target="_blank">查看原文</a>
                  </div>
                  <div v-if="row.analysis.reason" class="ann-reason">{{ row.analysis.reason }}</div>
                </div>
              </div>
              <Empty v-else description="无高关注度利好公告" />
            </Card>
          </Col>
          <Col :xs="24" :lg="12">
            <Card class="block-card" title="利好公告 · 中" :bordered="true">
              <div v-if="mediumRows.length" class="ann-scroll">
                <div v-for="(row, ri) in mediumRows" :key="ri" class="ann-row">
                  <div class="ann-head">
                    <Tag :color="levelColor(row.analysis.level)">{{ row.analysis.level }}</Tag>
                    <Tag :color="sentimentColor(row.analysis.sentiment)">{{ row.analysis.sentiment }}</Tag>
                    <span class="ann-title">{{ row.announcement.title }}</span>
                  </div>
                  <div class="ann-meta">
                    <span>{{ row.announcement.stock_name }} {{ row.announcement.stock_code }}</span>
                    <a v-if="row.announcement.pdf_url" :href="row.announcement.pdf_url" target="_blank">查看原文</a>
                  </div>
                  <div v-if="row.analysis.reason" class="ann-reason">{{ row.analysis.reason }}</div>
                </div>
              </div>
              <Empty v-else description="无中等关注度利好公告" />
            </Card>
          </Col>
        </Row>
      </template>
    </Spin>
  </div>
</template>

<style scoped>
.stock-daily-view { padding-bottom: 24px; }
.page-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;
}
.page-title { font-size: 16px; font-weight: 600; color: #1f1f1f; }
.page-sub { color: #8c8c8c; font-size: 12px; margin-left: 8px; }
.empty-wrap { padding: 60px 0; }
.kpi-card { border-radius: 8px; }
.block-card { margin-top: 16px; border-radius: 8px; }
.pick-card { border-radius: 8px; height: 100%; }
.pick-head { display: flex; justify-content: space-between; align-items: center; }
.stock-name { font-size: 15px; font-weight: 600; color: #1f1f1f; }
.stock-code { color: #8c8c8c; font-size: 12px; }
.pick-upside { margin-top: 8px; display: flex; gap: 8px; align-items: baseline; color: #8c8c8c; font-size: 12px; }
.pick-upside b { font-size: 18px; }
.pick-reason { margin-top: 6px; color: #1f2937; font-size: 13px; line-height: 1.5; }
.pick-brief { margin-top: 6px; font-size: 12px; color: #4b5563; }
.pick-brief p { margin: 4px 0 0; }
.pick-risk { margin-top: 8px; font-size: 12px; color: #9c3b3b; background: #fff1f0; padding: 6px 8px; border-radius: 4px; }
.rpt-item { background: #fafafa; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.rpt-meta { display: flex; gap: 8px; align-items: center; color: #8c8c8c; font-size: 12px; }
.rpt-title { font-size: 13px; font-weight: 600; color: #1f2937; margin: 4px 0; }
.rpt-txt { font-size: 12px; color: #374151; margin: 4px 0; }
.rpt-list { font-size: 12px; color: #4b5563; margin: 4px 0; }
.rpt-list.risk { color: #9c3b3b; }
.ann-scroll { max-height: 460px; overflow-y: auto; padding-right: 4px; }
.ann-row { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.ann-row:last-child { border-bottom: none; }
.ann-head { display: flex; gap: 6px; align-items: flex-start; }
.ann-title { font-size: 13px; color: #1f1f1f; line-height: 1.5; }
.ann-meta { display: flex; justify-content: space-between; color: #8c8c8c; font-size: 12px; margin: 4px 0 0 60px; }
.ann-reason { margin: 4px 0 0 60px; font-size: 12px; color: #4b5563; }
</style>
