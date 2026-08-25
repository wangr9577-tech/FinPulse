<script setup>
import { ref, onMounted, computed, h } from 'vue'
import { Card, Row, Col, Statistic, Tag, Table, Badge, Button, Alert, Empty, Space } from 'ant-design-vue'
import {
  ReloadOutlined,
  FilePdfOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  EyeOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import {
  fetchHealth,
  fetchLatestInsight,
  fetchHexagonOverview,
  fetchFlashNews,
  fetchReportHistory,
} from '../api'

const health = ref(null)
const latestInsight = ref(null)
const hexagon = ref(null)
const flashNews = ref([])
const reportHistory = ref([])
const loading = ref(true)
const lastUpdated = ref(null)

function isDateToday(t) {
  if (!t) return false
  const d = dayjs(t)
  return d.isSame(dayjs(), 'day')
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
    lastUpdated.value = new Date()
  } catch (err) {
    console.error('加载大屏数据失败:', err)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

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

const newsColumns = [
  {
    title: '发布时间',
    dataIndex: 'publish_time',
    width: 130,
    customRender: ({ text }) => {
      if (isDateToday(text)) {
        return h(Tag, { color: 'error', style: 'font-weight: 600;' }, () => `今日 ${dayjs(text).format('HH:mm')}`)
      }
      return h(Tag, { color: 'default' }, () => dayjs(text).format('MM-DD HH:mm'))
    }
  },
  {
    title: '资讯来源',
    dataIndex: 'source',
    width: 100,
    customRender: ({ text }) => h(Tag, { color: 'blue' }, () => text || '权威媒体')
  },
  {
    title: '资讯标题与要点 (最新置顶)',
    dataIndex: 'title',
    ellipsis: true,
    customRender: ({ text, record }) => {
      const today = isDateToday(record.publish_time)
      if (today) {
        return h('span', { style: 'color: #991b1b; font-weight: 600;' }, [
          h(Tag, { color: 'red', style: 'margin-right: 4px; font-size: 11px;' }, () => '今日'),
          text
        ])
      }
      return h('span', { style: 'color: #374151;' }, text)
    }
  },
  {
    title: '所属板块',
    dataIndex: 'sector',
    width: 130,
    customRender: ({ text }) => h(Tag, { color: 'purple' }, () => text || '宏观/行业')
  },
]

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
      <Button type="primary" @click="loadAll" :loading="loading">
        <template #icon><ReloadOutlined /></template>
        刷新大屏
      </Button>
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

    <!-- 下半部分：高频快讯流 + 历史研报列表 -->
    <Row :gutter="[16, 16]" style="margin-top: 16px">
      <Col :xs="24" :lg="14">
        <Card title="高频财经快讯流 (实时)" :loading="loading" style="min-height: 380px; border-radius: 8px;">
          <Table
            :columns="newsColumns"
            :data-source="flashNews"
            :pagination="{ pageSize: 6, size: 'small' }"
            size="small"
            row-key="news_id"
          >
            <template #emptyText><Empty description="暂无快讯数据" /></template>
          </Table>
        </Card>
      </Col>

      <Col :xs="24" :lg="10">
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
  </div>
</template>

<style scoped>
.dashboard-view-container {
  padding-bottom: 24px;
}
</style>
