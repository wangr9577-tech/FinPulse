<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  Card,
  Row,
  Col,
  Tag,
  Badge,
  Input,
  Radio,
  Tabs,
  TabPane,
  Empty,
  Spin,
  Space,
  Statistic,
  Button
} from 'ant-design-vue'
import {
  BankOutlined,
  GlobalOutlined,
  AppstoreOutlined,
  StockOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  FireOutlined,
  ArrowRightOutlined
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { useRouter } from 'vue-router'
import { fetchSectors } from '../api'

const router = useRouter()
const loading = ref(true)
const dbSectorMap = ref({})
const dbSectorTodayMap = ref({})
const searchQuery = ref('')
const selectedGroup = ref('ALL')

// =========================================================================
// 东方财富 86 个官方标准行业板块定义 (按大类分组)
// =========================================================================
const EASTMONEY_SECTOR_GROUPS = [
  {
    key: 'TMT',
    name: '电子与硬科技',
    tagColor: 'blue',
    items: [
      '半导体', '消费电子', '光学光电子', '元件', '电子化学品', '电子元件',
      '软件开发', '互联网服务', '计算机设备', 'IT服务',
      '通信设备', '通信服务',
      '游戏', '数字媒体', '影视院线', '广告营销', '出版'
    ]
  },
  {
    key: 'MFG',
    name: '高端制造与新能源',
    tagColor: 'green',
    items: [
      '光伏设备', '电池', '风电设备', '电网设备', '电源设备',
      '汽车整车', '汽车零部件', '汽车服务', '电机',
      '通用设备', '专用设备', '自动化设备', '工程机械', '仪器仪表', '轨交设备',
      '航空机场', '航天航空', '船舶制造'
    ]
  },
  {
    key: 'MED',
    name: '医药生物与大健康',
    tagColor: 'cyan',
    items: [
      '化学制药', '中药', '生物制品', '医疗器械', '医疗服务', '医药商业'
    ]
  },
  {
    key: 'CONSUME',
    name: '大消费与商贸农业',
    tagColor: 'orange',
    items: [
      '酿酒行业', '食品饮料', '农牧饲渔', '农化制品',
      '商业百货', '旅游酒店', '美容护理', '纺织服装',
      '家电行业', '轻工制造', '家居用品'
    ]
  },
  {
    key: 'FIN_PROP',
    name: '大金融与地产建材',
    tagColor: 'purple',
    items: [
      '银行', '证券', '保险', '多元金融',
      '房地产开发', '房地产服务', '工程建设', '水泥建材',
      '装修装饰', '装修建材'
    ]
  },
  {
    key: 'CYCLICAL',
    name: '周期与能源资源',
    tagColor: 'volcano',
    items: [
      '有色金属', '贵金属', '小金属', '钢铁行业',
      '煤炭行业', '石油行业', '燃气',
      '化学原料', '化学制品', '橡胶制品', '塑料制品',
      '玻璃玻纤', '造纸印刷'
    ]
  },
  {
    key: 'UTILITY_LOG',
    name: '公用环保与交运物流',
    tagColor: 'geekblue',
    items: [
      '电力行业', '公用事业', '环保行业', '综合行业',
      '航运港口', '公路铁路', '物流行业'
    ]
  }
]

// 扁平化全部 86 个行业列表 (携带今日与累计统计)
const ALL_86_SECTORS = computed(() => {
  const list = []
  for (const group of EASTMONEY_SECTOR_GROUPS) {
    for (const name of group.items) {
      list.push({
        name,
        groupKey: group.key,
        groupName: group.name,
        tagColor: group.tagColor,
        totalCount: getSectorNewsCount(name),
        todayCount: getSectorTodayNewsCount(name)
      })
    }
  }
  return list
})

// 过滤后的行业板块列表
const filteredSectors = computed(() => {
  let list = ALL_86_SECTORS.value
  if (selectedGroup.value !== 'ALL') {
    list = list.filter((s) => s.groupKey === selectedGroup.value)
  }
  if (searchQuery.value && searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter((s) => s.name.toLowerCase().includes(q) || s.groupName.toLowerCase().includes(q))
  }
  return list
})

// 宏观统计数据计算
const macroDomesticCount = computed(() => {
  const map = dbSectorMap.value
  return (map['国内宏观'] || 0) + (map['国内宏观与金融流动性'] || 0) + (map['国内宏观与流动性'] || 0) + (map['国内'] || 0)
})

const macroDomesticTodayCount = computed(() => {
  const tmap = dbSectorTodayMap.value
  return (tmap['国内宏观'] || 0) + (tmap['国内宏观与金融流动性'] || 0) + (tmap['国内宏观与流动性'] || 0) + (tmap['国内'] || 0)
})

const macroGlobalCount = computed(() => {
  const map = dbSectorMap.value
  return (map['海外宏观'] || 0) + (map['国外宏观'] || 0) + (map['海外宏观与地缘政治'] || 0) + (map['全球宏观与大类资产'] || 0) + (map['海外'] || 0)
})

const macroGlobalTodayCount = computed(() => {
  const tmap = dbSectorTodayMap.value
  return (tmap['海外宏观'] || 0) + (tmap['国外宏观'] || 0) + (tmap['海外宏观与地缘政治'] || 0) + (tmap['全球宏观与大类资产'] || 0) + (tmap['海外'] || 0)
})

const totalAllTodayCount = computed(() => {
  let sum = 0
  for (const c of Object.values(dbSectorTodayMap.value)) {
    sum += c
  }
  return sum
})

const totalIndustryTodayCount = computed(() => {
  let sum = 0
  for (const group of EASTMONEY_SECTOR_GROUPS) {
    for (const name of group.items) {
      sum += getSectorTodayNewsCount(name)
    }
  }
  return sum
})

function getGroupTodayCount(groupKey) {
  const group = EASTMONEY_SECTOR_GROUPS.find((g) => g.key === groupKey)
  if (!group) return 0
  let sum = 0
  for (const name of group.items) {
    sum += getSectorTodayNewsCount(name)
  }
  return sum
}

async function load() {
  loading.value = true
  try {
    const res = await fetchSectors()
    const list = res?.data || []
    const map = {}
    const todayMap = {}
    for (const item of list) {
      const sec = item.sector
      if (sec) {
        map[sec] = item.card_count || 0
        todayMap[sec] = item.today_card_count || 0
      }
    }
    dbSectorMap.value = map
    dbSectorTodayMap.value = todayMap
  } catch (err) {
    console.error('加载板块数据失败:', err)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function getSectorNewsCount(sectorName) {
  const map = dbSectorMap.value
  if (map[sectorName] !== undefined) return map[sectorName]
  let count = 0
  for (const [k, v] of Object.entries(map)) {
    if (k.includes(sectorName) || sectorName.includes(k)) {
      count += v
    }
  }
  return count
}

function getSectorTodayNewsCount(sectorName) {
  const tmap = dbSectorTodayMap.value
  if (tmap[sectorName] !== undefined) return tmap[sectorName]
  let count = 0
  for (const [k, v] of Object.entries(tmap)) {
    if (k.includes(sectorName) || sectorName.includes(k)) {
      count += v
    }
  }
  return count
}

function goSector(name) {
  router.push({ path: `/sectors/${encodeURIComponent(name)}` })
}
</script>

<template>
  <div class="sectors-container">
    <!-- 顶部状态栏与快速搜索 -->
    <div class="header-banner">
      <div class="banner-title">
        <h2 style="margin: 0; color: #1f2937; font-weight: 700; display: flex; align-items: center; gap: 8px">
          <AppstoreOutlined style="color: #1890ff" />
          全景资讯情报中心
          <Badge
            v-if="totalAllTodayCount > 0"
            :count="`今日全网新增 +${totalAllTodayCount} 条`"
            :number-style="{ backgroundColor: '#ff4d4f', fontWeight: '600', fontSize: '12px', padding: '0 8px' }"
          />
        </h2>
        <div style="color: #6b7280; font-size: 13px; margin-top: 4px">
          覆盖宏观经济、东方财富 86 个标准行业板块及个股标的情报，直连 MongoDB 实时更新，最新快讯置顶排列
        </div>
      </div>
      <div class="banner-search">
        <Input
          v-model:value="searchQuery"
          placeholder="搜索行业板块 (如：半导体、光伏、电池、白酒...)"
          allow-clear
          style="width: 320px"
        >
          <template #prefix>
            <SearchOutlined style="color: #999" />
          </template>
        </Input>
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- 第一栏：宏观 (国内 / 海外 两个可点击格子) -->
    <!-- ========================================================================= -->
    <Card class="section-card" :bordered="false">
      <template #title>
        <div class="section-title">
          <BankOutlined style="color: #1890ff" />
          <span>宏观资讯</span>
          <Tag color="blue" style="margin-left: 8px">核心宏观视角</Tag>
          <Badge
            v-if="(macroDomesticTodayCount + macroGlobalTodayCount) > 0"
            :count="`宏观今日 +${macroDomesticTodayCount + macroGlobalTodayCount} 条`"
            :number-style="{ backgroundColor: '#ff4d4f', fontSize: '11px' }"
            style="margin-left: 8px"
          />
        </div>
      </template>

      <Row :gutter="[20, 20]">
        <!-- 宏观格子 1：国内宏观 -->
        <Col :xs="24" :sm="12" :md="12">
          <div class="macro-box domestic-box" :class="{ 'has-today-news': macroDomesticTodayCount > 0 }" @click="goSector('国内宏观')">
            <div class="macro-box-header">
              <div class="macro-box-title">
                <span class="flag-icon">🇨🇳</span>
                <span class="title-text">国内宏观</span>
                <span v-if="macroDomesticTodayCount > 0" class="today-red-tag">
                  <FireOutlined style="font-size: 11px; margin-right: 2px" />
                  +{{ macroDomesticTodayCount }} 今日新增
                </span>
              </div>
              <Tag color="red" class="badge-tag">点击查看资讯 <ArrowRightOutlined /></Tag>
            </div>
            <div class="macro-box-desc">
              涵盖中国人民银行货币政策、财政赤字与发债、国内社融信贷、PMI、CPI/PPI 通胀及金融监管调控。
            </div>
            <div class="macro-box-footer">
              <div class="tags-row">
                <Tag color="volcano">降准降息</Tag>
                <Tag color="orange">社融信贷</Tag>
                <Tag color="red">货币流动性</Tag>
                <Tag color="gold">经济增长</Tag>
              </div>
              <div class="count-badge">
                <div class="macro-stat-stack">
                  <span class="macro-stat-today" v-if="macroDomesticTodayCount > 0">
                    今日 <strong>+{{ macroDomesticTodayCount }}</strong> 条
                  </span>
                  <span class="macro-stat-total">
                    累计 <strong>{{ macroDomesticCount }}</strong> 条
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Col>

        <!-- 宏观格子 2：海外宏观 -->
        <Col :xs="24" :sm="12" :md="12">
          <div class="macro-box global-box" :class="{ 'has-today-news': macroGlobalTodayCount > 0 }" @click="goSector('海外宏观')">
            <div class="macro-box-header">
              <div class="macro-box-title">
                <span class="flag-icon">🌍</span>
                <span class="title-text">海外宏观</span>
                <span v-if="macroGlobalTodayCount > 0" class="today-red-tag">
                  <FireOutlined style="font-size: 11px; margin-right: 2px" />
                  +{{ macroGlobalTodayCount }} 今日新增
                </span>
              </div>
              <Tag color="blue" class="badge-tag">点击查看资讯 <ArrowRightOutlined /></Tag>
            </div>
            <div class="macro-box-desc">
              跟踪美联储利率决议、海外央行货币政策、美债收益率、美元汇率异动、全球大宗商品及地缘格局。
            </div>
            <div class="macro-box-footer">
              <div class="tags-row">
                <Tag color="blue">美联储降息</Tag>
                <Tag color="cyan">美债与美元</Tag>
                <Tag color="purple">全球大宗</Tag>
                <Tag color="geekblue">地缘外汇</Tag>
              </div>
              <div class="count-badge">
                <div class="macro-stat-stack">
                  <span class="macro-stat-today" v-if="macroGlobalTodayCount > 0">
                    今日 <strong>+{{ macroGlobalTodayCount }}</strong> 条
                  </span>
                  <span class="macro-stat-total">
                    累计 <strong>{{ macroGlobalCount }}</strong> 条
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Col>
      </Row>
    </Card>

    <!-- ========================================================================= -->
    <!-- 第二栏：行业板块 (东方财富 86 个行业可点击格子) -->
    <!-- ========================================================================= -->
    <Card class="section-card" :bordered="false" style="margin-top: 20px">
      <template #title>
        <div class="section-title">
          <AppstoreOutlined style="color: #52c41a" />
          <span>行业板块</span>
          <Tag color="green" style="margin-left: 8px">东方财富 86 个官方行业分类</Tag>
          <Badge
            v-if="totalIndustryTodayCount > 0"
            :count="`行业今日 +${totalIndustryTodayCount} 条`"
            :number-style="{ backgroundColor: '#ff4d4f', fontSize: '11px' }"
            style="margin-left: 8px"
          />
        </div>
      </template>
      <template #extra>
        <span style="color: #666; font-size: 13px">
          共 <strong style="color: #1890ff">{{ ALL_86_SECTORS.length }}</strong> 个标准行业，点击任意板块进入专属资讯流
        </span>
      </template>

      <!-- 快速行业大类筛选 -->
      <div class="group-filter-tabs">
        <Radio.Group v-model:value="selectedGroup" button-style="solid" size="middle">
          <Radio.Button value="ALL">
            全部行业 ({{ ALL_86_SECTORS.length }})
            <span v-if="totalIndustryTodayCount > 0" class="radio-red-dot">
              +{{ totalIndustryTodayCount }}
            </span>
          </Radio.Button>
          <Radio.Button
            v-for="grp in EASTMONEY_SECTOR_GROUPS"
            :key="grp.key"
            :value="grp.key"
          >
            {{ grp.name }} ({{ grp.items.length }})
            <span v-if="getGroupTodayCount(grp.key) > 0" class="radio-red-dot">
              +{{ getGroupTodayCount(grp.key) }}
            </span>
          </Radio.Button>
        </Radio.Group>
      </div>

      <Spin :spinning="loading">
        <div class="industry-grid" v-if="filteredSectors.length">
          <div
            v-for="s in filteredSectors"
            :key="s.name"
            class="industry-card"
            :class="{ 'has-today-news': s.todayCount > 0 }"
            @click="goSector(s.name)"
          >
            <div class="card-top">
              <span class="sector-name">{{ s.name }}</span>
              <span v-if="s.todayCount > 0" class="today-red-tag">
                <FireOutlined style="font-size: 10px; margin-right: 2px" />+{{ s.todayCount }} 今日
              </span>
            </div>
            <div class="card-bottom">
              <Tag :color="s.tagColor" size="small" style="margin: 0; font-size: 11px">
                {{ s.groupName }}
              </Tag>
              <span class="view-link">查看 <ArrowRightOutlined style="font-size: 10px" /></span>
            </div>
          </div>
        </div>
        <Empty v-else description="未找到匹配的行业板块" style="margin: 40px 0" />
      </Spin>
    </Card>

    <!-- ========================================================================= -->
    <!-- 第三栏：个股资讯 (保留栏目，不设置具体格子) -->
    <!-- ========================================================================= -->
    <Card class="section-card stock-section" :bordered="false" style="margin-top: 20px">
      <template #title>
        <div class="section-title">
          <StockOutlined style="color: #722ed1" />
          <span>个股资讯</span>
          <Tag color="purple" style="margin-left: 8px">全市场 5000+ 标的穿透 (保留规划)</Tag>
        </div>
      </template>

      <div class="stock-placeholder-box">
        <div class="placeholder-icon">
          <StockOutlined style="font-size: 42px; color: #722ed1" />
        </div>
        <div class="placeholder-content">
          <h4 style="margin: 0 0 6px 0; color: #1f2937; font-weight: 600; font-size: 16px">
            个股资讯与实时标的深度追踪
          </h4>
          <p style="margin: 0 0 10px 0; color: #6b7280; font-size: 13px; line-height: 1.6">
            本栏目预留支持沪深京全市场 A 股上市公司的财报披露、盘中公告、龙虎榜异动与主力舆情深度穿透。
            当前阶段保持架构占位，不设置具体格子，后续将与个股数据库无缝打通。
          </p>
          <Space>
            <Tag color="purple">个股研报萃取</Tag>
            <Tag color="blue">大单资金流向</Tag>
            <Tag color="cyan">业绩预告透视</Tag>
            <Tag color="default">功能保留接入中</Tag>
          </Space>
        </div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.sectors-container {
  padding: 4px 0 24px 0;
}

.header-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.section-card {
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  background: #ffffff;
}

.section-title {
  display: flex;
  align-items: center;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  gap: 6px;
}

/* 宏观盒子样式 */
.macro-box {
  border-radius: 8px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.25s ease;
  border: 1px solid transparent;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 160px;
  position: relative;
}

.domestic-box {
  background: linear-gradient(135deg, #fff1f0 0%, #fff7e6 100%);
  border-color: #ffccc7;
}

.domestic-box:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(245, 34, 45, 0.15);
  border-color: #ff4d4f;
}

.global-box {
  background: linear-gradient(135deg, #e6f7ff 0%, #f0f5ff 100%);
  border-color: #bae7ff;
}

.global-box:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(24, 144, 255, 0.15);
  border-color: #1890ff;
}

.macro-box.has-today-news {
  border-color: #ff4d4f;
  box-shadow: 0 2px 8px rgba(255, 77, 79, 0.12);
}

.macro-box-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.macro-box-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.flag-icon {
  font-size: 22px;
}

.title-text {
  font-size: 18px;
  font-weight: 700;
  color: #1f2937;
}

.badge-tag {
  cursor: pointer;
}

.macro-box-desc {
  color: #4b5563;
  font-size: 13px;
  line-height: 1.5;
  margin: 10px 0;
}

.macro-box-footer {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-top: 6px;
}

.tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.macro-stat-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.macro-stat-today {
  color: #cf1322;
  font-size: 14px;
  font-weight: 700;
  background: #fff1f0;
  border: 1px solid #ffa39e;
  border-radius: 4px;
  padding: 2px 6px;
}

.macro-stat-total {
  color: #6b7280;
  font-size: 12px;
}

/* 行业板块分类切换与网格 */
.group-filter-tabs {
  margin-bottom: 16px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.radio-red-dot {
  background: #ff4d4f;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  border-radius: 10px;
  padding: 0 5px;
  margin-left: 4px;
  display: inline-block;
  line-height: 14px;
}

.industry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
}

.industry-card {
  background: #fdfdfd;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 76px;
  position: relative;
}

.industry-card:hover {
  background: #ffffff;
  border-color: #1890ff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(24, 144, 255, 0.12);
}

.industry-card.has-today-news {
  border-color: #ffa39e;
  background: linear-gradient(135deg, #ffffff 0%, #fffbfb 100%);
}

.industry-card.has-today-news:hover {
  border-color: #ff4d4f;
  box-shadow: 0 4px 14px rgba(255, 77, 79, 0.16);
}

.today-red-tag {
  background: #fff1f0;
  color: #cf1322;
  border: 1px solid #ffa39e;
  border-radius: 10px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.sector-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.view-link {
  font-size: 11px;
  color: #9ca3af;
  display: flex;
  align-items: center;
  gap: 2px;
  transition: color 0.2s;
}

.industry-card:hover .view-link {
  color: #1890ff;
}

/* 个股占位区样式 */
.stock-placeholder-box {
  background: #f9fafb;
  border: 1px dashed #d1d5db;
  border-radius: 8px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 24px;
}

.placeholder-icon {
  background: #f3e8ff;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
