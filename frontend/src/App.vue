<script setup>
import { ref, watch } from 'vue'
import { Layout, Menu } from 'ant-design-vue'
import { DashboardOutlined, RadarChartOutlined, ReadOutlined } from '@ant-design/icons-vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const selectedKeys = ref(['/'])

watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/hexagon')) {
      selectedKeys.value = ['/hexagon']
    } else if (path.startsWith('/sectors')) {
      selectedKeys.value = ['/sectors']
    } else {
      selectedKeys.value = ['/']
    }
  },
  { immediate: true }
)

function onMenuClick({ key }) {
  router.push(key)
}
</script>

<template>
  <Layout style="min-height: 100vh">
    <Layout.Sider theme="dark" width="220" :collapsible="true">
      <div class="logo">
        <div class="logo-title">FinPulse</div>
        <div class="logo-sub">智能投研引擎</div>
      </div>
      <Menu
        theme="dark"
        mode="inline"
        :selectedKeys="selectedKeys"
        @click="onMenuClick"
      >
        <Menu.Item key="/">
          <template #icon><DashboardOutlined /></template>
          总览
        </Menu.Item>
        <Menu.Item key="/hexagon">
          <template #icon><RadarChartOutlined /></template>
          择时六面图
        </Menu.Item>
        <Menu.Item key="/sectors">
          <template #icon><ReadOutlined /></template>
          板块资讯
        </Menu.Item>
      </Menu>
    </Layout.Sider>
    <Layout>
      <Layout.Content style="padding: 24px; overflow: auto">
        <router-view />
      </Layout.Content>
    </Layout>
  </Layout>
</template>

<style scoped>
.logo {
  height: 64px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 0 20px;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.logo-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}
.logo-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  margin-top: 2px;
}
</style>
