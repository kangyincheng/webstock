import { createRouter, createWebHashHistory } from 'vue-router'
import { tokenStore } from '../api/http.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'),
    meta: { title: '登录 / 注册', public: true } },
  { path: '/admin/login', name: 'AdminLogin', component: () => import('../views/AdminLogin.vue'),
    meta: { title: '管理员登录', public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue'),
    meta: { title: '工作台', icon: '📊' } },
  { path: '/predict', name: 'Predict', component: () => import('../views/Predict.vue'),
    meta: { title: '股票预测', icon: '📈' } },
  { path: '/st', redirect: '/st/analyze' },
  { path: '/st/analyze', name: 'STAnalyze', component: () => import('../views/STAnalyze.vue'),
    meta: { title: 'ST股统计分析', icon: '📊' } },
  { path: '/st/overview', name: 'STOverview', component: () => import('../views/STOverview.vue'),
    meta: { title: 'ST股个股表现', icon: '📈' } },
  { path: '/st/time', name: 'STTime', component: () => import('../views/STTime.vue'),
    meta: { title: 'ST股摘帽时间', icon: '📅' } },
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
  { path: '/admin', name: 'Admin', component: () => import('../views/Admin.vue'),
    meta: { title: '管理后台', icon: '🛡️', requireAuth: true, requireAdmin: true } },
  { path: '/admin/users', name: 'AdminUsers', component: () => import('../views/AdminUsers.vue'),
    meta: { title: '用户管理', icon: '👥', requireAuth: true, requireAdmin: true } },
  { path: '/admin/audit', name: 'AdminAudit', component: () => import('../views/AdminAudit.vue'),
    meta: { title: '全局审计', icon: '📋', requireAuth: true, requireAdmin: true } },
  { path: '/admin/st', name: 'AdminST', component: () => import('../views/AdminST.vue'),
    meta: { title: 'ST摘帽管理', icon: '🏷️', requireAuth: true, requireAdmin: true } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} · webstock`
  }
  if (to.meta?.requireAuth && !tokenStore.isLoggedIn()) {
    return next({ path: to.meta?.requireAdmin ? '/admin/login' : '/login', query: { redirect: to.fullPath } })
  }
  if (to.meta?.requireAdmin && !tokenStore.user?.is_admin) {
    return next({ path: '/admin/login', query: { redirect: to.fullPath } })
  }
  next()
})

export default router
