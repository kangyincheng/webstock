import { createRouter, createWebHashHistory } from 'vue-router'
import { tokenStore } from '../api/http.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'),
    meta: { title: '登录 / 注册', public: true } },
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
  { path: '/profile', name: 'Profile', component: () => import('../views/Profile.vue'),
    meta: { title: '个人中心', icon: '👤', requireAuth: true } },
  { path: '/history', name: 'History', component: () => import('../views/History.vue'),
    meta: { title: '操作历史', icon: '🧾', requireAuth: true } },
]

const router = createRouter({
  history: createWebHashHistory(),  // hash 模式，Nginx SPA fallback 最稳
  routes,
})

// 简单的路由守卫：requireAuth 页面需要已登录（不强制跳登录，仅跳 dashboard 再由用户点登录）
router.beforeEach((to, _from, next) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} · webstock`
  }
  if (to.meta?.requireAuth && !tokenStore.isLoggedIn()) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  next()
})

export default router
