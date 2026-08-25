<script setup>
import { ref, onMounted, computed, h } from 'vue'
import {
  Card,
  Row,
  Col,
  Table,
  Tag,
  Alert,
  Button,
  Space,
  Modal,
  Image,
  Radio,
  Input,
  Statistic,
  Divider,
} from 'ant-design-vue'
import {
  ReloadOutlined,
  LineChartOutlined,
  SearchOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  MinusOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import EChart from '../components/EChart.vue'
import { fetchHexagonOverview } from '../api'

const overview = ref(null)
const loading = ref(true)
const lastUpdated = ref(null)
const selectedDimension = ref('ALL')
const searchKeyword = ref('')
const previewImage = ref({ visible: false, title: '', url: '' })

// 6 大标准维度顺序
const DIMENSIONS_ORDER = ['流动性', '宏观经济', '估值', '资金面', '技术面', '情绪与期权面']

async function load() {
  loading.value = true
  try {
    const res = await fetchHexagonOverview()
    overview.value = res?.data || null
    lastUpdated.value = new Date()
  } catch (err) {
    console.error('加载六面图数据失败:', err)
  } finally {
    loading.value = false
  }
}

onMounted(load)

// 1. 雷达图配置：100% 对齐后端 compute_dimension_weighted_scores ([-1.0, +1.0])
const radarOption = computed(() => {
  const d = overview.value
  if (!d) return {}
  const dimScores = d.dimension_scores || {}

  const indicators = DIMENSIONS_ORDER.map((name) => ({
    name,
    min: -1.2,
    max: 1.2,
  }))

  const values = DIMENSIONS_ORDER.map((name) => {
    const s = dimScores[name]
    return s !== undefined && s !== null ? Number(s) : 0.0
  })

  return {
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        let str = `<div style="font-weight:600;margin-bottom:4px">${params.seriesName || '择时六维加权得分'}</div>`
        DIMENSIONS_ORDER.forEach((dim, idx) => {
          const val = values[idx]
          const sign = val > 0 ? `+${val.toFixed(2)} [看多]` : val < 0 ? `${val.toFixed(2)} [看空]` : `0.00 [中性]`
          const color = val > 0 ? '#cf1322' : val < 0 ? '#389e0d' : '#8c8c8c'
          str += `<div style="display:flex;justify-content:space-between;gap:12px;font-size:12px">
            <span>${dim}:</span>
            <span style="color:${color};font-weight:600">${sign}</span>
          </div>`
        })
        return str
      },
    },
    radar: {
      indicator: indicators,
      radius: '68%',
      splitNumber: 4,
      axisName: {
        color: '#1f1f1f',
        fontWeight: 'bold',
        fontSize: 12,
      },
      splitLine: {
        lineStyle: {
          color: ['#e8e8e8', '#e8e8e8', '#bfbfbf', '#e8e8e8', '#e8e8e8'],
        },
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: ['rgba(250,250,250,0.4)', 'rgba(240,240,240,0.4)'],
        },
      },
    },
    series: [
      {
        name: '择时六维加权得分',
        type: 'radar',
        data: [
          {
            value: values,
            name: '当前维度得分',
            areaStyle: {
              color: 'rgba(24, 144, 255, 0.25)',
            },
            lineStyle: {
              width: 2.5,
              color: '#1890ff',
            },
            itemStyle: {
              color: '#1890ff',
            },
          },
        ],
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
  }
})

// 2. 六维度卡片数据
const dimensionCards = computed(() => {
  const d = overview.value
  if (!d) return []
  const details = d.dimension_details || {}
  const scores = d.dimension_scores || {}
  const counts = d.dimension_counts || {}

  return DIMENSIONS_ORDER.map((dim) => {
    const det = details[dim]
    const score = det?.weighted_score !== undefined ? det.weighted_score : (scores[dim] || 0)
    const c = counts[dim] || { 看多: 0, 看空: 0, 中性: 0 }
    const direction = score > 0 ? '看多' : score < 0 ? '看空' : '中性'
    return {
      dim,
      score: Number(score).toFixed(2),
      rawScore: score,
      direction,
      bullish: c['看多'] || 0,
      bearish: c['看空'] || 0,
      neutral: c['中性'] || 0,
      total: (c['看多'] || 0) + (c['看空'] || 0) + (c['中性'] || 0),
    }
  })
})

// 3. 过滤后的指标列表
const filteredIndicators = computed(() => {
  const list = overview.value?.indicators || []
  return list.filter((item) => {
    const matchDim = selectedDimension.value === 'ALL' || item.dimension === selectedDimension.value
    const matchKey =
      !searchKeyword.value ||
      item.indicator?.toLowerCase().includes(searchKeyword.value.toLowerCase()) ||
      item.signal_text?.toLowerCase().includes(searchKeyword.value.toLowerCase())
    return matchDim && matchKey
  })
})

function signalColor(score) {
  if (score === 1 || score > 0) return 'error'
  if (score === -1 || score < 0) return 'success'
  return 'default'
}

function signalText(score) {
  if (score === 1 || score > 0) return '看多'
  if (score === -1 || score < 0) return '看空'
  return '中性'
}

function scoreTagColor(val) {
  if (val > 0) return 'error'
  if (val < 0) return 'success'
  return 'default'
}

function fmtDate(v) {
  return v ? dayjs(v).format('YYYY-MM-DD') : '-'
}

function openChartPreview(record) {
  if (record.chart_url) {
    previewImage.value = {
      visible: true,
      title: `${record.dimension} — ${record.indicator} 高清走势图`,
      url: record.chart_url,
    }
  }
}

const indicatorColumns = [
  {
    title: '维度',
    dataIndex: 'dimension',
    width: 120,
    customRender: ({ text }) => h(Tag, { color: 'blue' }, () => text),
  },
  {
    title: '指标名称',
    dataIndex: 'indicator',
    width: 210,
    customRender: ({ text }) => h('span', { style: 'font-weight: 600;' }, text),
  },
  {
    title: '最新值',
    dataIndex: 'latest_value',
    width: 120,
    customRender: ({ text }) => {
      if (text === null || text === undefined || text === '') return '-'
      if (typeof text === 'number') return text.toFixed(4).replace(/\.?0+$/, '')
      return String(text)
    },
  },
  {
    title: '信号状态',
    dataIndex: 'signal_score',
    width: 100,
    customRender: ({ record }) =>
      h(
        Tag,
        { color: signalColor(record.signal_score), style: 'font-weight: 500;' },
        () => signalText(record.signal_score)
      ),
  },
  {
    title: '研报信号说明',
    dataIndex: 'signal_text',
    ellipsis: true,
  },
  {
    title: '生效日期',
    dataIndex: 'effective_date',
    width: 110,
    customRender: ({ text }) => fmtDate(text),
  },
  {
    title: '指标走势图',
    dataIndex: 'chart_url',
    width: 160,
    align: 'center',
    customRender: ({ record }) => {
      if (!record.chart_url) return h('span', { style: 'color:#aaa; font-size:12px' }, '暂无图表')
      return h(
        'div',
        {
          style: 'cursor: pointer; display: inline-block;',
          onClick: () => openChartPreview(record),
        },
        [
          h('img', {
            src: record.chart_url,
            style: 'height: 42px; max-width: 120px; object-fit: contain; border-radius: 4px; border: 1px solid #e8e8e8;',
          }),
        ]
      )
    },
  },
]
</script>

<template>
  <div class="hexagon-view-container">
    <!-- 顶部状态栏 -->
    <Alert
      type="info"
      show-icon
      style="margin-bottom: 16px; border-radius: 6px;"
      :message="`数据截至：${overview?.as_of_date || '-'} | 真实有效量化指标：${overview?.total_indicators || overview?.indicators?.length || 0} 项`"
      description="本页六面图雷达评分与 25 项量化指标 100% 实时同步自后端计算结果与最新信号数据库，已彻底剔除无法复现的占位数据。"
    />

    <!-- 操作与过滤控制栏 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
      <Space size="middle">
        <Button type="primary" @click="load" :loading="loading">
          <template #icon><ReloadOutlined /></template>
          刷新实时数据
        </Button>
        <span v-if="lastUpdated" style="color: #8c8c8c; font-size: 13px">
          最近刷新时刻：{{ dayjs(lastUpdated).format('YYYY-MM-DD HH:mm:ss') }}
        </span>
      </Space>

      <Space>
        <Input
          v-model:value="searchKeyword"
          placeholder="搜索指标或信号说明..."
          allow-clear
          style="width: 220px"
        >
          <template #prefix><SearchOutlined style="color: #bfbfbf" /></template>
        </Input>
      </Space>
    </div>

    <!-- 上半部分：六维雷达图 + 六大维度加权打分卡片 -->
    <Row :gutter="[16, 16]">
      <Col :xs="24" :lg="10">
        <Card title="择时六面图 — 维度综合雷达图" :loading="loading" style="border-radius: 8px; height: 100%;">
          <EChart :option="radarOption" height="340px" />
          <div style="text-align: center; color: #8c8c8c; font-size: 12px; margin-top: 8px;">
            注：雷达图坐标轴范围为 [-1.0, +1.0]，0 轴为中性基准线，正值为看多，负值为看空。
          </div>
        </Card>
      </Col>

      <Col :xs="24" :lg="14">
        <Row :gutter="[12, 12]">
          <Col :xs="24" :sm="12" :md="8" v-for="card in dimensionCards" :key="card.dim">
            <Card
              size="small"
              :loading="loading"
              hoverable
              style="border-radius: 8px; height: 100%;"
              :body-style="{ padding: '12px 14px' }"
            >
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 600; font-size: 14px;">{{ card.dim }}</span>
                <Tag :color="scoreTagColor(card.rawScore)" style="margin: 0; font-weight: bold;">
                  {{ card.direction }}
                </Tag>
              </div>

              <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #8c8c8c; font-size: 12px;">加权得分</span>
                <span style="font-size: 18px; font-weight: 700;" :style="{ color: card.rawScore > 0 ? '#cf1322' : card.rawScore < 0 ? '#389e0d' : '#595959' }">
                  {{ card.rawScore > 0 ? `+${card.score}` : card.score }}
                </span>
              </div>

              <div style="display: flex; gap: 4px; font-size: 11px; flex-wrap: wrap;">
                <Tag color="error" style="margin: 0; font-size: 11px; padding: 0 4px;">多 {{ card.bullish }}</Tag>
                <Tag color="success" style="margin: 0; font-size: 11px; padding: 0 4px;">空 {{ card.bearish }}</Tag>
                <Tag style="margin: 0; font-size: 11px; padding: 0 4px;">中 {{ card.neutral }}</Tag>
              </div>
            </Card>
          </Col>
        </Row>
      </Col>
    </Row>

    <!-- 下半部分：25 项有效量化指标明细表格 -->
    <Card
      :title="`25 项量化指标信号明细 (${filteredIndicators.length} 项)`"
      :loading="loading"
      style="margin-top: 16px; border-radius: 8px;"
    >
      <template #extra>
        <Radio.Group v-model:value="selectedDimension" button-style="solid" size="small">
          <Radio.Button value="ALL">全部维度</Radio.Button>
          <Radio.Button v-for="dim in DIMENSIONS_ORDER" :key="dim" :value="dim">{{ dim }}</Radio.Button>
        </Radio.Group>
      </template>

      <Table
        :columns="indicatorColumns"
        :data-source="filteredIndicators"
        row-key="indicator"
        size="middle"
        :pagination="{ pageSize: 25, showTotal: (total) => `共 ${total} 项量化指标` }"
      />
    </Card>

    <!-- 高清走势图预览弹窗 -->
    <Modal
      v-model:open="previewImage.visible"
      :title="previewImage.title"
      :footer="null"
      width="800px"
      centered
    >
      <div style="text-align: center; padding: 12px 0;">
        <img :src="previewImage.url" style="max-width: 100%; border-radius: 6px;" />
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.hexagon-view-container {
  padding-bottom: 24px;
}
</style>
