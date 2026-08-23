import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue'),
    meta: { title: '工作台', icon: '📊' } },
  { path: '/predict', name: 'Predict', component: () => import('../views/Predict.vue'),
    meta: { title: '股票预测', icon: '📈' } },
  { path: '/st', name: 'ST', component: () => import('../views/STPage.vue'),
    meta: { title: 'ST摘帽/恢复', icon: '🏷️' } },
  { path: '/cbond', name: 'CBond', component: () => import('../views/CBond.vue'),
    meta: { title: '可转债', icon: '💴' } },
  { path: '/tender', name: 'Tender', component: () => import('../views/Tender.vue'),
    meta: { title: '要约收购', icon: '📢' } },
  { path: '/sector', name: 'Sector', component: () => import('../views/SectorHeat.vue'),
    meta: { title: '板块热度', icon: '🔥' } },
  { path: '/hot', name: 'Hot', component: () => import('../views/HotStocks.vue'),
    meta: { title: '热门股票', icon: '⭐' } },
  { path: '/favorites', name: 'Favorites', component: () => import('../views/Favorites.vue'),
    meta: { title: '自选股', icon: '💖' } },
]

export default createRouter({
  history: createWebHashHistory(),  // hash 模式，Nginx SPA fallback 最稳
  routes,
})
