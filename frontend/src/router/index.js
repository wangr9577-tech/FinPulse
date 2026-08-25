import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/hexagon', name: 'hexagon', component: () => import('../views/HexagonView.vue') },
  { path: '/sectors', name: 'sectors', component: () => import('../views/SectorsView.vue') },
  { path: '/sectors/:name', name: 'sector-detail', component: () => import('../views/SectorDetailView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
