<script setup>
import { ref, onMounted, computed, h } from 'vue'
import { Card, Checkbox, Button, Space, Tag, Empty, Alert, Spin, Descriptions, Row, Col, Divider, message } from 'ant-design-vue'
import { ReloadOutlined, SaveOutlined, FilePdfOutlined, ReadOutlined } from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { marked } from 'marked'
import { fetchLatestInsight, fetchSubscriptions, updateSubscriptions, fetchSectors } from '../api'

// 默认研报包含板块 (与后端 ConfigSubscriptionSchema / get_system_config 默认值保持一致)
const DEFAULT_SECTORS = ['国内宏观', '国外宏观', '半导体', '互联网服务', '银行']

const report = ref(null)
const checkedSectors = ref([...DEFAULT_SECTORS])
const sectorOptions = ref([...DEFAULT_SECTORS])
const loading = ref(true)
const saving = ref(false)

function fmtTime(t) {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

// 将 Markdown 研报渲染为 HTML (内容来自后端自身合成的资讯研报)
const reportHtml = computed(() => {
  const md = report.value?.markdown_content || ''
  return md ? marked.parse(md) : ''
})

async function loadReport() {
  try {
    const res = await fetchLatestInsight()
    report.value = res?.data || null
  } catch (e) {
    console.error('加载最新研报失败:', e)
  }
}

async function loadConfig() {
  try {
    const res = await fetchSubscriptions()
    const cfg = res?.data || {}
    const selected = Array.isArray(cfg.report_sectors) ? cfg.report_sectors : DEFAULT_SECTORS
    checkedSectors.value = selected.filter((s) => !!s)
    // 已勾选板块始终出现在选项里，避免默认板块无资讯时仍可勾选/取消
    sectorOptions.value = mergeOptions(sectorOptions.value, selected)
  } catch (e) {
    console.error('加载板块配置失败:', e)
  }
}

async function loadSectors() {
  try {
    const res = await fetchSectors()
    const list = res?.data || []
    const names = list.map((it) => it.sector || it._id).filter((s) => !!s)
    sectorOptions.value = mergeOptions(sectorOptions.value, names)
  } catch (e) {
    console.error('加载板块列表失败:', e)
  }
}

function mergeOptions(base, extra) {
  const set = new Set([...base, ...extra])
  return Array.from(set)
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.allSettled([loadReport(), loadConfig(), loadSectors()])
  } finally {
    loading.value = false
  }
}

async function saveSectors() {
  saving.value = true
  try {
    // 保留其他订阅配置字段，仅更新报告板块
    const res = await fetchSubscriptions()
    const cfg = res?.data || {}
    const payload = { ...cfg, report_sectors: checkedSectors.value }
    await updateSubscriptions(payload)
    message.success('板块配置已保存')
  } catch (e) {
    console.error('保存板块配置失败:', e)
  } finally {
    saving.value = false
  }
}

function openPdf(url) {
  const target = url || '/static/market_insight_report.pdf'
  window.open(target, '_blank')
}

onMounted(loadAll)
</script>

<template>
  <div class="report-view-container">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <Space>
        <span style="font-size: 16px; font-weight: 600; color: #1f1f1f;">研报中心</span>
        <span style="color: #8c8c8c; font-size: 13px;">预览当天生成的资讯研报，并控制研报包含的板块</span>
      </Space>
      <div>
        <span style="color: #8c8c8c; font-size: 12px; margin-right: 8px;">
          最新生成: {{ report ? fmtTime(report.generation_time) : '暂未生成' }}
        </span>
        <Button @click="loadAll" :loading="loading">
          <template #icon><ReloadOutlined /></template>
          刷新
        </Button>
      </div>
    </div>

    <Row :gutter="[16, 16]">
      <!-- 板块配置 -->
      <Col :xs="24" :lg="8">
        <Card title="研报包含板块" :loading="loading" style="border-radius: 8px;">
          <Alert
            type="info"
            show-icon
            message="勾选后，当天新生成的资讯研报将仅收录这些板块；不勾选则收录全部活跃板块。"
            style="margin-bottom: 16px;"
          />
          <div class="sector-scroll">
            <Checkbox.Group
              v-model:value="checkedSectors"
              :options="sectorOptions.map((s) => ({ label: s, value: s }))"
              style="display: flex; flex-direction: column; gap: 8px;"
            />
          </div>
          <div style="margin-top: 20px;">
            <Button type="primary" :loading="saving" @click="saveSectors">
              <template #icon><SaveOutlined /></template>
              保存板块配置
            </Button>
            <Button style="margin-left: 8px" @click="checkedSectors = [...DEFAULT_SECTORS]">
              恢复默认
            </Button>
          </div>
          <Divider v-if="report" style="margin: 16px 0;" />
          <Descriptions v-if="report" :column="1" size="small" bordered>
            <Descriptions.Item label="实际包含板块数">
              {{ report.sector_count ?? report.sectors?.length ?? 0 }}
            </Descriptions.Item>
            <Descriptions.Item label="实际包含板块">
              <template v-if="report.sectors && report.sectors.length">
                <Tag v-for="s in report.sectors" :key="s" color="purple" style="margin-bottom: 4px;">{{ s }}</Tag>
              </template>
              <span v-else style="color: #8c8c8c;">-</span>
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>

      <!-- 研报预览 -->
      <Col :xs="24" :lg="16">
        <Card
          :title="report ? report.title : '当天资讯研报'"
          :loading="loading"
          style="border-radius: 8px;"
          :body-style="{ padding: '0' }"
        >
          <template #extra>
            <Button type="link" :href="report?.pdf_url || '/static/market_insight_report.pdf'" target="_blank">
              <template #icon><FilePdfOutlined /></template>
              打开 PDF
            </Button>
          </template>

          <Spin :spinning="loading">
            <div v-if="reportHtml" class="report-md-preview" v-html="reportHtml"></div>
            <Empty v-else description="暂无当天资讯研报，请先运行研报生成流水线" style="padding: 40px 0;" />
          </Spin>
        </Card>
      </Col>
    </Row>
  </div>
</template>

<style scoped>
.report-view-container {
  padding-bottom: 24px;
}
.sector-scroll {
  max-height: 320px;
  overflow-y: auto;
  padding: 6px 8px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  background: #fafafa;
}
.report-md-preview {
  padding: 20px 24px;
  max-height: 72vh;
  overflow-y: auto;
  line-height: 1.7;
  color: #1f2937;
  font-size: 14px;
}
.report-md-preview :deep(h1) {
  font-size: 20px;
  color: #0f172a;
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 8px;
}
.report-md-preview :deep(h2) {
  font-size: 17px;
  color: #1e3a8a;
  border-left: 4px solid #2563eb;
  padding-left: 10px;
}
.report-md-preview :deep(h3) {
  font-size: 15px;
  color: #0f172a;
}
.report-md-preview :deep(h4) {
  font-size: 14px;
  color: #334155;
}
.report-md-preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}
.report-md-preview :deep(th),
.report-md-preview :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 6px 9px;
  text-align: left;
}
.report-md-preview :deep(th) {
  background-color: #eff6ff;
}
.report-md-preview :deep(blockquote) {
  background-color: #f8fafc;
  border-left: 4px solid #3b82f6;
  margin: 12px 0;
  padding: 8px 16px;
}
</style>
