<script setup>
import { ref, reactive, onMounted, computed, h } from 'vue'
import { Card, Row, Col, Statistic, Tag, Table, Badge, Button, Alert, Empty, Space, Modal, Switch, Input, message } from 'ant-design-vue'
import {
  ReloadOutlined,
  FilePdfOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  EyeOutlined,
  ClockCircleOutlined,
  MailOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { isToday } from '../utils/time'
import {
  fetchHealth,
  fetchLatestInsight,
  fetchHexagonOverview,
  fetchFlashNews,
  fetchReportHistory,
  fetchAutoRunConfig,
  updateAutoRunConfig,
  fetchEmailConfig,
  updateEmailConfig,
  triggerAutoRunNow,
} from '../api'

const health = ref(null)
const latestInsight = ref(null)
const hexagon = ref(null)
const flashNews = ref([])
const reportHistory = ref([])
const loading = ref(true)
const lastUpdated = ref(null)

// 自动化设置（按钮1：定时运行；按钮2：邮件接收）
const autoRun = ref({ enabled: false, run_time: '07:00', next_run_time: null })
const emailCfg = ref({ enabled: false, recipients: [] })
const autoRunModal = reactive({ open: false, enabled: false, run_time: '07:00' })
const emailModal = reactive({ open: false, enabled: false, recipients: '' })
const runningNow = ref(false)

function isDateToday(t) {
  // 今日 = 过去 24 小时 (非自然日历日)
  return isToday(t)
}

const todayFlashCount = computed(() => {
  return flashNews.value.filter((n) => isDateToday(n.publish_time || n.crawled_at)).length
})

async function loadAll() {
  loading.value = true
  try {
    const [h, insight, hex, news, history] = await Promise.allSettled([
      fetchHealth(),
      fetchLatestInsight(),
      fetchHexagonOverview(),
      fetchFlashNews(0),
      fetchReportHistory(50),
    ])
    if (h.status === 'fulfilled') health.value = (h.value && h.value.database) ? h.value : (h.value?.data || null)
    if (insight.status === 'fulfilled') latestInsight.value = insight.value?.data || insight.value || null
    if (hex.status === 'fulfilled') hexagon.value = hex.value?.data || null
    if (news.status === 'fulfilled') {
      const rawList = news.value?.data || []
      // 严格倒序排列 (最新新闻放前面)
      rawList.sort((a, b) => {
        const ta = new Date(a.publish_time || a.crawled_at || 0).getTime()
        const tb = new Date(b.publish_time || b.crawled_at || 0).getTime()
        return tb - ta
      })
      flashNews.value = rawList
    }
    if (history.status === 'fulfilled') reportHistory.value = history.value?.data || []
    await fetchAutomation()
    lastUpdated.value = new Date()
  } catch (err) {
    console.error('加载大屏数据失败:', err)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

async function fetchAutomation() {
  try {
    const [a, e] = await Promise.allSettled([fetchAutoRunConfig(), fetchEmailConfig()])
    if (a.status === 'fulfilled') autoRun.value = a.value?.data || { enabled: false, run_time: '07:00' }
    if (e.status === 'fulfilled') emailCfg.value = e.value?.data || { enabled: false, recipients: [] }
  } catch (err) {
    console.error('加载自动化配置失败:', err)
  }
}

function openAutoRunModal() {
  autoRunModal.enabled = !!autoRun.value.enabled
  autoRunModal.run_time = autoRun.value.run_time || '07:00'
  autoRunModal.open = true
}

async function saveAutoRun() {
  const payload = { enabled: autoRunModal.enabled, run_time: autoRunModal.run_time || '07:00' }
  const res = await updateAutoRunConfig(payload)
  if (res && res.code === 200) {
    autoRun.value = res.data || payload
    message.success('定时运行设置已保存')
    autoRunModal.open = false
  }
}

function openEmailModal() {
  emailModal.enabled = !!emailCfg.value.enabled
  emailModal.recipients = (emailCfg.value.recipients || []).join(',')
  emailModal.open = true
}

async function saveEmail() {
  const recipients = (emailModal.recipients || '')
    .split(/[,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = { enabled: emailModal.enabled, recipients }
  const res = await updateEmailConfig(payload)
  if (res && res.code === 200) {
    emailCfg.value = res.data || payload
    message.success('邮件接收设置已保存')
    emailModal.open = false
  }
}

async function runNow() {
  runningNow.value = true
  try {
    const res = await triggerAutoRunNow()
    if (res && res.code !== 200) return
    message.success('已开始全量运行（资讯+六面图+公告选股），稍后可在对应页面查看')
  } catch (err) {
    console.error('触发运行失败:', err)
  } finally {
    runningNow.value = false
  }
}

const signalSummary = computed(() => {
  const d = hexagon.value
  if (!d) return { bullish: 0, bearish: 0, neutral: 0, total: 0 }
  return {
    bullish: d.bullish_signals ? d.bullish_signals.length : 0,
    bearish: d.bearish_signals ? d.bearish_signals.length : 0,
    neutral: d.neutral_signals ? d.neutral_signals.length : 0,
    total: d.total_indicators || d.indicators?.length || 0,
  }
})

function fmtTime(t) {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

function openReport(url) {
  const target = url || '/static/market_insight_report.html'
  window.open(target, '_blank')
}

const reportColumns = [
  { title: '生成时间', dataIndex: 'generation_time', width: 150, customRender: ({ text }) => fmtTime(text) },
  {
    title: '研报标题',
    dataIndex: 'title',
    ellipsis: true,
    customRender: ({ record }) => {
      const targetUrl = record.html_url || record.pdf_url || '/static/market_insight_report.html'
      return h(
        'a',
        {
          href: targetUrl,
          target: '_blank',
          style: 'color: #1890ff; font-weight: 500;',
        },
        record.title || '智能投研综合研报'
      )
    },
  },
  {
    title: '操作',
    width: 90,
    align: 'center',
    customRender: ({ record }) => {
      const targetUrl = record.html_url || record.pdf_url || '/static/market_insight_report.html'
      return h(
        Button,
        {
          type: 'link',
          size: 'small',
          icon: h(EyeOutlined),
          onClick: () => openReport(targetUrl),
        },
        () => '预览'
      )
    },
  },
]
</script>

<template>
  <div class="dashboard-view-container">
    <!-- 数据库警报 -->
    <Alert
      v-if="health && health.database && !health.database.connected"
      type="warning"
      show-icon
      message="MongoDB 数据库未连接"
      description="后端 API 服务已启动，但 MongoDB 数据库连接异常，部分数据可能无法实时同步。"
      style="margin-bottom: 16px; border-radius: 6px;"
    />

    <!-- 顶部状态栏 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <Space>
        <span style="font-size: 16px; font-weight: 600; color: #1f1f1f;">投研大屏概览</span>
        <span v-if="lastUpdated" style="color: #8c8c8c; font-size: 13px;">
          (更新时刻: {{ dayjs(lastUpdated).format('HH:mm:ss') }})
        </span>
      </Space>
      <Space>
        <Button @click="openAutoRunModal">
          <template #icon><ClockCircleOutlined /></template>
          定时运行<Badge v-if="autoRun.enabled" status="processing" text="开启" />
          <span v-else style="color: #8c8c8c;">未开启</span>
        </Button>
        <Button @click="openEmailModal">
          <template #icon><MailOutlined /></template>
          邮件接收<Badge v-if="emailCfg.enabled" status="success" text="开启" />
          <span v-else style="color: #8c8c8c;">未开启</span>
        </Button>
        <Button type="primary" @click="loadAll" :loading="loading">
          <template #icon><ReloadOutlined /></template>
          刷新大屏
        </Button>
      </Space>
    </div>

    <!-- 核心指标卡片 -->
    <Row :gutter="[16, 16]">
      <Col :xs="24" :sm="12" :lg="6">
        <Card :loading="loading" hoverable style="border-radius: 8px;">
          <Statistic title="后端服务状态" value="运行正常" :value-style="{ color: '#389e0d', fontSize: '20px' }">
            <template #prefix><CheckCircleOutlined /></template>
          </Statistic>
          <div style="margin-top: 8px">
            <Badge
              :status="health?.database?.connected ? 'success' : 'error'"
              :text="health?.database?.connected ? 'MongoDB 数据库在线' : 'MongoDB 断开'"
            />
          </div>
        </Card>
      </Col>

      <Col :xs="24" :sm="12" :lg="6">
        <Card :loading="loading" hoverable style="border-radius: 8px;">
          <Statistic
            :title="`六面图信号 (共 ${signalSummary.total} 项有效指标)`"
            :value="signalSummary.bullish"
            suffix="项看多"
            :value-style="{ color: '#cf1322', fontSize: '20px' }"
          />
          <div style="margin-top: 8px; display: flex; gap: 6px;">
            <Tag color="error">看多 {{ signalSummary.bullish }}</Tag>
            <Tag color="success">看空 {{ signalSummary.bearish }}</Tag>
            <Tag>中性 {{ signalSummary.neutral }}</Tag>
          </div>
        </Card>
      </Col>

      <Col :xs="24" :sm="12" :lg="6">
        <Card
          :loading="loading"
          hoverable
          style="border-radius: 8px; cursor: pointer;"
          @click="openReport(latestInsight?.html_url || latestInsight?.pdf_url)"
        >
          <Statistic
            title="最新综合投研研报"
            :value="latestInsight?.generation_time ? fmtTime(latestInsight.generation_time) : '暂无'"
            :value-style="{ fontSize: '15px', fontWeight: 600, color: '#1890ff' }"
          >
            <template #prefix><FilePdfOutlined /></template>
          </Statistic>
          <div style="margin-top: 8px; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 12px; color: #8c8c8c; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ latestInsight?.title || '点击在线预览研报' }}
            </span>
            <Tag color="processing">点击预览 →</Tag>
          </div>
        </Card>
      </Col>

      <Col :xs="24" :sm="12" :lg="6">
        <Card :loading="loading" hoverable style="border-radius: 8px;">
          <Statistic
            title="高频快讯池"
            :value="flashNews.length"
            suffix="条24h快讯"
            :value-style="{ fontSize: '20px' }"
          >
            <template #prefix><ThunderboltOutlined style="color: #faad14" /></template>
          </Statistic>
          <div style="margin-top: 8px; display: flex; justify-content: space-between; align-items: center;">
            <Badge
              v-if="todayFlashCount > 0"
              status="error"
              :text="`今日新增 +${todayFlashCount} 条`"
              style="font-weight: 600; color: #cf1322;"
            />
            <span v-else style="color: #8c8c8c; font-size: 12px;">16 大财经媒体实时监控</span>
          </div>
        </Card>
      </Col>
    </Row>

    <!-- 下半部分：历史研报列表 -->
    <Row :gutter="[16, 16]" style="margin-top: 16px">
      <Col :xs="24" :lg="24">
        <Card title="历史综合投研研报" :loading="loading" style="min-height: 380px; border-radius: 8px;">
          <Table
            :columns="reportColumns"
            :data-source="reportHistory"
            :pagination="{ pageSize: 6, size: 'small' }"
            size="small"
            row-key="report_id"
          >
            <template #emptyText><Empty description="暂无历史研报" /></template>
          </Table>
        </Card>
      </Col>
    </Row>

    <!-- 按钮1：每日定时运行设置 -->
    <Modal
      v-model:open="autoRunModal.open"
      title="每日定时运行"
      @ok="saveAutoRun"
      @cancel="autoRunModal.open = false"
      ok-text="保存"
      cancel-text="取消"
    >
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span>启用每日自动运行</span>
          <Switch v-model:checked="autoRunModal.enabled" />
        </div>
        <div>
          <div style="margin-bottom: 6px;">运行时间</div>
          <Input v-model:value="autoRunModal.run_time" placeholder="07:00" style="width: 120px;" />
        </div>
        <Alert
          type="info"
          show-icon
          message="每日到达设定时间后自动运行：资讯研报 + 择时六面图 + 公告选股（每日投资日报）。"
          description="需后端服务在运行中才可触发。当日公告多发布于盘中，7:00 可能暂无数据（显示空态，不编造）。"
        />
      </div>
    </Modal>

    <!-- 按钮2：邮件接收设置 -->
    <Modal
      v-model:open="emailModal.open"
      title="邮件接收设置"
      @ok="saveEmail"
      @cancel="emailModal.open = false"
      ok-text="保存"
      cancel-text="取消"
    >
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span>启用邮件发送</span>
          <Switch v-model:checked="emailModal.enabled" />
        </div>
        <div>
          <div style="margin-bottom: 6px;">接收邮箱（逗号分隔）</div>
          <Input.TextArea
            v-model:value="emailModal.recipients"
            :rows="3"
            placeholder="例：a@example.com, b@example.com"
          />
        </div>
        <Alert
          type="info"
          show-icon
          message="运行完成后，将把「资讯研报 + 六面图 + 每日投资日报」PDF 作为附件发送到邮箱。"
          description="收件人默认读取 .env 的 DEFAULT_RECEIVERS（上方为 env + 已填邮箱合并结果）。未启用或全为空则不发。"
        />
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.dashboard-view-container {
  padding-bottom: 24px;
}
</style>
