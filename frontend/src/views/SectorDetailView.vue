<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import {
  Card,
  List,
  Tag,
  Space,
  Empty,
  Spin,
  Button,
  Breadcrumb,
  BreadcrumbItem,
  Statistic,
  Row,
  Col
} from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  ThunderboltOutlined,
  CalendarOutlined,
  RiseOutlined,
  FallOutlined,
  MinusCircleOutlined,
  ApartmentOutlined
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { useRoute, useRouter } from 'vue-router'
import { fetchSectorNews } from '../api'

const route = useRoute()
const router = useRouter()
const sectorName = computed(() => decodeURIComponent(route.params.name || ''))
const items = ref([])
const loading = ref(true)

// =========================================================================
// 核心宏观与东财重点行业产业链与监控指标图谱库
// =========================================================================
const SECTOR_CHAINS = {
  '国内宏观': [
    { name: '货币政策', indicators: ['SHIBOR 1W', 'DR007偏离度', 'M2/M1同比', '降准降息', '公开市场逆回购'] },
    { name: '信用周期', indicators: ['社融存量增速', '新增人民币贷款', '企业中长期贷款', '信贷脉冲'] },
    { name: '实体经济', indicators: ['官方制造业PMI', '财新PMI', '工业增加值', 'CPI/PPI同比', '固定资产投资'] }
  ],
  '海外宏观': [
    { name: '美债与汇率', indicators: ['10年期美债收益率', '美元指数 (DXY)', '中美利差', '离岸人民币 (CNH)'] },
    { name: '大宗商品', indicators: ['COMEX 黄金价格', 'WTI 原油价格', 'LME 铜价', '波罗的海干散货BDI'] },
    { name: '全球流动性', indicators: ['美联储隔夜逆回购 (ON RRP)', '美联储资产负债表', '全球央行购金量'] }
  ],
  '半导体': [
    { name: '上游设备与材料', indicators: ['光刻机/刻蚀机出货', '大硅片出货量', '光刻胶国产化率', '电子特气'] },
    { name: '中游制造与封测', indicators: ['晶圆代工产能利用率', '8/12英寸晶圆代工价', '先进封测产能 (CoWoS)'] },
    { name: '下游终端需求', indicators: ['AI服务器出货量', '智能手机出货增速', '汽车MCU芯片库存'] }
  ],
  '消费电子': [
    { name: '核心零部件', indicators: ['OLED面板报价', 'CIS图像传感器', '光学镜头出货', '精密结构件'] },
    { name: '品牌终端出货', indicators: ['AI手机渗透率', '折叠屏手机销量', '智能手表与TWS耳机', 'MR/VR出货量'] },
    { name: '渠道与库存', indicators: ['消费电子渠道库存周期', '北美/欧洲假日季销量', '国内电商大促GMV'] }
  ],
  '软件开发': [
    { name: '算力与模型底层', indicators: ['大模型API调用量', '算力调度系统', '开源算法社区活跃度'] },
    { name: '企业级SaaS与应用', indicators: ['企业数字化IT支出', '信创软件招投标', '工业软件国产化率'] },
    { name: '网络与数据安全', indicators: ['网安合规采购额', '数据要素流通规模', '云安全支出'] }
  ],
  '电池': [
    { name: '上游原材料', indicators: ['电池级碳酸锂现货价', '氢氧化锂报价', '前驱体价格', '负极石墨开工率'] },
    { name: '电芯制造', indicators: ['动力电池装车量', '储能电池出货量', '三元/磷酸铁锂占比', '固态电池研发进展'] },
    { name: '下游新能源应用', indicators: ['新能源汽车单车带电量', '大储能电站并网容量', '工商业储能IRR'] }
  ],
  '光伏设备': [
    { name: '主产业链价格', indicators: ['致密料硅料报价', 'P/N型硅片价格', 'TOPCon/HJT电池片价格', '组件中标价'] },
    { name: '辅材与设备', indicators: ['光伏玻璃库存', '金刚线出货', '逆变器出口金额', '银浆加工费'] },
    { name: '终端装机', indicators: ['国内集中式光伏装机', '分布式光伏新增量', '欧洲光伏进口数据'] }
  ],
  '汽车整车': [
    { name: '产销与渗透率', indicators: ['乘用车月度零售销量', '新能源车渗透率', '乘联会批发销量', '豪华车市占率'] },
    { name: '出海与出口', indicators: ['汽车整车出口数量', '滚装船运价', '欧洲/东南亚海外建厂进度'] },
    { name: '价格战与毛利', indicators: ['单车平均降价幅度', '整车企业毛利率', '经销商库存预警指数'] }
  ],
  '化学制药': [
    { name: '新药研发与管线', indicators: ['IND/NDA审批数量', '临床三期成功率', '海外授权License-out金额'] },
    { name: '政策与集采', indicators: ['国家医保谈判降幅', '化药国家集采落地', '基本药物目录调整'] },
    { name: '原料药与外贸', indicators: ['API原料药出口价格', '抗生素中间体价格', 'CDMO商业化订单'] }
  ],
  '中药': [
    { name: '中药材上游', indicators: ['中药材价格指数', '天然牛黄/天然麝香价格', '道地药材种植面积'] },
    { name: '品牌中药与OTC', indicators: ['独家品种进院比例', 'OTC中成药药房销售', '经典名方获批数量'] }
  ],
  '酿酒行业': [
    { name: '高端白酒批价', indicators: ['飞天茅台整箱/散瓶批价', '普五/国窖批价', '酒企回款进度'] },
    { name: '库存与动销', indicators: ['经销商库存月份', '商务宴请与婚宴场景动销', '次高端白酒开瓶率'] },
    { name: '啤酒与大众酒', indicators: ['吨酒均价高端化进度', '大麦与包装铝材成本', '夜场与餐饮复苏指数'] }
  ],
  '银行': [
    { name: '息差与盈利', indicators: ['净息差 (NIM)', '存贷款基准利率', '存款定期化比例', '非息收入占比'] },
    { name: '资产质量', indicators: ['不良贷款率 (NPL)', '拨备覆盖率', '关注类贷款迁徙率', '地产城投敞口风险'] }
  ],
  '证券': [
    { name: '市场交投活跃度', indicators: ['A股两市日均成交额', '两融余额 (融资融券)', '万得全A换手率'] },
    { name: '投行与财富管理', indicators: ['IPO/再融资承销规模', '公募基金代销保有量', '券商自营投资收益率'] }
  ],
  '房地产开发': [
    { name: '销售端表现', indicators: ['30城商品房成交面积', '百强房企全口径销售', '二手房挂牌量与成交量'] },
    { name: '投资与拿地', indicators: ['房企拿地金额', '土地溢价率', '房屋新开工面积', '保交楼竣工面积'] },
    { name: '政策与房贷', indicators: ['首套/二套房贷利率', '公积金贷款额度上限', '白名单项目融资落地'] }
  ],
  '有色金属': [
    { name: '工业金属', indicators: ['SHFE/LME 阴极铜价格', '电解铝现货报价', '铝土矿/氧化铝供应', '全球主要铜矿扰动率'] },
    { name: '贵金属与稀缺资源', indicators: ['COMEX 黄金/白银现货', '实物黄金ETF持仓', '稀土氧化镨钕价格', '锑/钨战略小金属报价'] }
  ],
  '电力行业': [
    { name: '发电量与利用小时', indicators: ['全国全社会用电量同比', '火电利用小时数', '风电/光伏弃风弃光率', '水电来水偏丰偏枯'] },
    { name: '成本与电价', indicators: ['秦皇岛港动力煤长协价', '电力现货市场交易价', '容量电价机制补贴落地'] }
  ]
}

// 模糊匹配产业链图谱
const chainNodes = computed(() => {
  const name = sectorName.value
  if (SECTOR_CHAINS[name]) return SECTOR_CHAINS[name]
  for (const [k, v] of Object.entries(SECTOR_CHAINS)) {
    if (name.includes(k) || k.includes(name)) {
      return v
    }
  }
  // 默认通用产业链
  return [
    { name: '宏观政策与行业监管', indicators: ['产业扶持政策', '行业准入标准', '监管法规动态'] },
    { name: '供需基本面与产能', indicators: ['行业供需平衡表', '龙头企业扩产计划', '产品销售价格指数'] },
    { name: '核心标的与财务', indicators: ['龙头营收与净利增速', '毛利率走势', '研发投入与研发人员占比'] }
  ]
})

// 情绪与今日统计
const isItemToday = (item) => {
  if (item.is_today === true) return true
  const t = item.publish_time || item.processed_at || item.crawled_at
  if (!t) return false
  const d = dayjs(t)
  return d.isSame(dayjs(), 'day')
}

const todayCount = computed(() => items.value.filter(isItemToday).length)
const bullishCount = computed(() => items.value.filter((i) => i.sentiment === '看多').length)
const bearishCount = computed(() => items.value.filter((i) => i.sentiment === '看空').length)
const neutralCount = computed(() => items.value.filter((i) => i.sentiment === '中性' || !i.sentiment).length)

async function load() {
  loading.value = true
  try {
    const res = await fetchSectorNews(sectorName.value, 0)
    const list = res?.data || []
    // 严格按时间倒序排列 (最新新闻置顶)
    list.sort((a, b) => {
      const ta = new Date(a.publish_time || a.processed_at || a.crawled_at || 0).getTime()
      const tb = new Date(b.publish_time || b.processed_at || b.crawled_at || 0).getTime()
      return tb - ta
    })
    items.value = list
  } catch (err) {
    console.error('加载板块资讯失败:', err)
  } finally {
    loading.value = false
  }
}

watch(() => route.params.name, () => {
  load()
})

onMounted(load)

function fmtTime(t) {
  if (!t) return '近期'
  const d = dayjs(t)
  return d.format('YYYY-MM-DD HH:mm')
}

function timeLabel(t) {
  if (!t) return '最新'
  const d = dayjs(t)
  if (d.isAfter(dayjs().startOf('day'))) return '今日'
  if (d.isAfter(dayjs().startOf('day').subtract(1, 'day'))) return '昨日'
  return d.format('MM-DD')
}

function sentColor(s) {
  if (s === '看多') return 'green'
  if (s === '看空') return 'red'
  return 'default'
}
</script>

<template>
  <div class="sector-detail-container">
    <!-- 顶部面包屑与导航 -->
    <div class="top-nav-bar">
      <Breadcrumb>
        <BreadcrumbItem><a @click="router.push('/sectors')">资讯情报中心</a></BreadcrumbItem>
        <BreadcrumbItem>{{ sectorName }}</BreadcrumbItem>
      </Breadcrumb>
      <Button type="default" size="small" @click="router.push('/sectors')">
        <ArrowLeftOutlined /> 返回板块总览
      </Button>
    </div>

    <!-- 板块标题与统计概览 Header -->
    <div class="sector-header-card">
      <div class="header-main">
        <div class="title-row">
          <h2 style="margin: 0; color: #111827; font-weight: 700; display: flex; align-items: center; gap: 10px">
            <ApartmentOutlined style="color: #1890ff" />
            {{ sectorName }} · 专属情报流
            <Badge
              v-if="todayCount > 0"
              :count="`今日新增 +${todayCount} 条`"
              :number-style="{ backgroundColor: '#ff4d4f', fontWeight: 'bold', fontSize: '12px', padding: '0 8px' }"
            />
          </h2>
          <Tag color="blue" style="font-size: 13px; padding: 2px 8px">数据库实时直连 · 倒序排列</Tag>
        </div>
        <div style="color: #6b7280; font-size: 13px; margin-top: 6px">
          实时汇聚来自新浪财经、东方财富、财联社、36氪、行业深度公告及权威数据库的结构化情报卡片，最新资讯自动置顶
        </div>
      </div>

      <div class="header-stats">
        <Row :gutter="12">
          <Col :span="6">
            <div class="stat-mini-box">
              <span class="stat-mini-title">资讯总量</span>
              <span class="stat-mini-num" style="color: #1890ff">{{ items.length }} 条</span>
            </div>
          </Col>
          <Col :span="6">
            <div class="stat-mini-box" :class="{ 'stat-today-active': todayCount > 0 }">
              <span class="stat-mini-title"><FireOutlined style="color: #ff4d4f" /> 今日新增</span>
              <span class="stat-mini-num" style="color: #cf1322">+{{ todayCount }}</span>
            </div>
          </Col>
          <Col :span="6">
            <div class="stat-mini-box">
              <span class="stat-mini-title"><RiseOutlined /> 看多资讯</span>
              <span class="stat-mini-num" style="color: #52c41a">{{ bullishCount }}</span>
            </div>
          </Col>
          <Col :span="6">
            <div class="stat-mini-box">
              <span class="stat-mini-title"><FallOutlined /> 看空资讯</span>
              <span class="stat-mini-num" style="color: #ff4d4f">{{ bearishCount }}</span>
            </div>
          </Col>
        </Row>
      </div>
    </div>

    <!-- 产业链图谱与监控指标 -->
    <Card
      title="核心产业链图谱与关键高频监控指标"
      class="chain-card"
      :bordered="false"
      v-if="chainNodes.length"
    >
      <div class="chain-grid">
        <div v-for="item in chainNodes" :key="item.name" class="chain-box">
          <div class="chain-box-title">{{ item.name }}</div>
          <div class="chain-tags">
            <Tag v-for="indicator in item.indicators" :key="indicator" color="blue" class="indicator-tag">
              {{ indicator }}
            </Tag>
          </div>
        </div>
      </div>
    </Card>

    <!-- 资讯列表卡片 -->
    <Card
      :title="`资讯明细列表 (${items.length} 条)`"
      class="news-list-card"
      :bordered="false"
      :loading="loading"
    >
      <template #extra>
        <span style="color: #6b7280; font-size: 13px">
          按时间<strong>由新到旧</strong>倒序排列 | 
          <span style="color: #cf1322; font-weight: 600">红色卡片为今日最新资讯</span>
        </span>
      </template>

      <Spin :spinning="loading">
        <List
          v-if="items.length"
          :data-source="items"
          item-layout="vertical"
          :pagination="{ pageSize: 15, showSizeChanger: true, showTotal: (t) => `共 ${t} 条实时资讯 (最新新闻放前面)` }"
        >
          <template #renderItem="{ item }">
            <div
              class="news-item-box"
              :class="{ 'today-news-box': isItemToday(item) }"
            >
              <div class="news-item-top">
                <Space size="small">
                  <Tag
                    v-if="isItemToday(item)"
                    color="error"
                    class="today-flash-tag"
                  >
                    <FireOutlined /> 今日最新
                  </Tag>
                  <Tag v-else color="default">
                    {{ timeLabel(item.publish_time || item.processed_at) }}
                  </Tag>
                  <Tag v-if="item.sentiment" :color="sentColor(item.sentiment)">
                    {{ item.sentiment }}
                  </Tag>
                  <Tag v-if="item.event_type" color="purple">{{ item.event_type }}</Tag>
                  <span class="news-source">{{ item.source }}</span>
                </Space>
                <span class="news-time" :class="{ 'today-time-highlight': isItemToday(item) }">
                  <CalendarOutlined style="margin-right: 4px" />
                  {{ fmtTime(item.publish_time || item.processed_at) }}
                </span>
              </div>

              <div class="news-item-title" :class="{ 'today-title-highlight': isItemToday(item) }">
                <span v-if="isItemToday(item)" class="today-title-prefix">[今日]</span>
                {{ item.title }}
              </div>

              <div v-if="item.core_facts && item.core_facts.length" class="news-facts-box" :class="{ 'today-facts-box': isItemToday(item) }">
                <div v-for="(fact, idx) in item.core_facts" :key="idx" class="fact-row">
                  <span class="fact-dot" :class="{ 'today-dot': isItemToday(item) }">●</span>
                  <span>{{ fact }}</span>
                </div>
              </div>

              <!-- 量化指标 Tags -->
              <div
                v-if="item.key_metrics && Object.keys(item.key_metrics).length"
                class="metrics-row"
              >
                <Tag
                  v-for="(val, key) in item.key_metrics"
                  :key="key"
                  color="geekblue"
                  class="metric-tag"
                >
                  <ThunderboltOutlined /> {{ key }}: <strong>{{ val }}</strong>
                </Tag>
              </div>
            </div>
          </template>
        </List>
        <Empty v-else description="该板块暂无匹配的资讯数据" style="margin: 48px 0" />
      </Spin>
    </Card>
  </div>
</template>

<style scoped>
.sector-detail-container {
  padding: 4px 0 24px 0;
}

.top-nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.sector-header-card {
  background: #ffffff;
  border-radius: 10px;
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  margin-bottom: 16px;
}

.stat-mini-box {
  background: #f9fafb;
  border-radius: 6px;
  padding: 8px 10px;
  text-align: center;
  border: 1px solid #f0f0f0;
}

.stat-mini-box.stat-today-active {
  background: #fff1f0;
  border-color: #ffa39e;
}

.stat-mini-title {
  font-size: 11px;
  color: #6b7280;
  display: block;
  margin-bottom: 2px;
}

.stat-mini-num {
  font-size: 16px;
  font-weight: 700;
}

.chain-card,
.news-list-card {
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  margin-bottom: 16px;
}

.chain-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.chain-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 14px;
}

.chain-box-title {
  font-weight: 600;
  font-size: 14px;
  color: #1e293b;
  margin-bottom: 8px;
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 4px;
}

.chain-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.indicator-tag {
  margin: 0;
  font-size: 12px;
}

/* 资讯卡片基础样式 */
.news-item-box {
  background: #fcfcfc;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
  transition: all 0.2s ease;
}

.news-item-box:hover {
  background: #ffffff;
  border-color: #1890ff;
  box-shadow: 0 4px 12px rgba(24, 144, 255, 0.08);
}

/* 当天新闻特殊高亮标记样式 */
.news-item-box.today-news-box {
  background: linear-gradient(135deg, #fffcfb 0%, #fff7f5 100%);
  border-color: #ffccc7;
  border-left: 4px solid #ff4d4f;
  box-shadow: 0 2px 8px rgba(255, 77, 79, 0.08);
}

.news-item-box.today-news-box:hover {
  background: #ffffff;
  border-color: #ff4d4f;
  box-shadow: 0 6px 18px rgba(255, 77, 79, 0.16);
}

.today-flash-tag {
  font-weight: 700;
  background: #ff4d4f !important;
  color: #ffffff !important;
  border: none;
  border-radius: 4px;
}

.today-time-highlight {
  color: #cf1322 !important;
  font-weight: 600;
}

.today-title-highlight {
  color: #991b1b !important;
  font-weight: 700 !important;
}

.today-title-prefix {
  color: #ff4d4f;
  font-weight: 800;
  margin-right: 4px;
}

.today-facts-box {
  background: #fff5f5 !important;
  border: 1px solid #ffe8e8;
}

.fact-dot.today-dot {
  color: #ff4d4f;
}

.news-item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.news-source {
  color: #4b5563;
  font-size: 12px;
  font-weight: 500;
}

.news-time {
  color: #9ca3af;
  font-size: 12px;
}

.news-item-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 8px;
  line-height: 1.4;
}

.news-facts-box {
  background: #f9fafb;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 8px;
}

.fact-row {
  color: #374151;
  font-size: 13px;
  line-height: 1.6;
  display: flex;
  gap: 6px;
}

.fact-dot {
  color: #1890ff;
  font-size: 10px;
  margin-top: 2px;
}

.metrics-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.metric-tag {
  margin: 0;
}
</style>
