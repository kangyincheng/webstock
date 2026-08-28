<script setup>
import { computed, onMounted, onUnmounted, ref, markRaw, defineComponent, h, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElDropdown } from 'element-plus'
import { sysHealth, sysVersion, authMe, authLogout, auditLast } from './api/index.js'
import { tokenStore } from './api/http.js'

const router = useRouter()
const route = useRoute()

const navMenu = [
  { key: 'work', title: '工作台', items: [
    { key: '/dashboard', title: '📊 数据看板', sub: false },
    { key: '/predict', title: '📈 股票预测' },
    { key: '/st', title: '🏷️ ST摘帽 / 恢复' },
    { key: '/cbond', title: '💴 可转债' },
    { key: '/tender', title: '📢 要约收购' },
    { key: '/sector', title: '🔥 板块热度' },
    { key: '/hot', title: '⭐ 热门股票' },
    { key: '/favorites', title: '💖 自选股' },
  ]},
  { key: 'mine', title: '我的', items: [
    { key: '/profile', title: '👤 个人中心', requireAuth: true },
    { key: '/history', title: '🧾 操作历史', requireAuth: true },
  ]},
]

const adminMenu = {
  key: 'admin', title: '管理后台', items: [
    { key: '/admin', title: '🛡️ 后台首页' },
    { key: '/admin/users', title: '👥 用户管理' },
    { key: '/admin/audit', title: '📋 全局审计' },
  ],
}

const fullNav = computed(() => {
  if (user.value?.is_admin) {
    return [...navMenu, adminMenu]
  }
  return navMenu
})

const active = computed(() => route.path)
function go(p) { router.push(p) }

const version = ref('')
const user = ref(tokenStore.user)
const lastAction = ref(null)
const welcomeShown = ref(false)

// --- 移动端响应式 ---
const isMobile = ref(false)
const menuOpen = ref(false)

function updateMobile() {
  const m = window.innerWidth < 768
  if (m !== isMobile.value) {
    isMobile.value = m
    // 切回桌面时关闭菜单
    if (!m) menuOpen.value = false
  }
}

function toggleMenu() { menuOpen.value = !menuOpen.value }
function closeMenu() { menuOpen.value = false }
function openMenu() { menuOpen.value = true }

function handleKeydown(e) {
  if (e.key === 'Escape' && isMobile.value && menuOpen.value) closeMenu()
}

onMounted(async () => {
  updateMobile()
  window.addEventListener('resize', updateMobile)
  window.addEventListener('keydown', handleKeydown)
  try {
    const v = await sysVersion()
    version.value = `${v.name} ${v.version}`
  } catch {}
  try { await sysHealth() } catch (e) {
    ElMessage.warning('后端服务未就绪：' + e.message)
  }
  await refreshMe(true)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateMobile)
  window.removeEventListener('keydown', handleKeydown)
})

// 路由变化时关闭移动端抽屉（单向，不会产生循环：只写 menuOpen，不读它）
watch(() => route.path, () => { if (isMobile.value) closeMenu() })

async function refreshMe(showWelcome = false) {
  if (!tokenStore.isLoggedIn()) { user.value = null; return }
  try {
    const meResp = await authMe()
    const me = meResp?.user || meResp
    user.value = me
    tokenStore.setUser(me)
    lastAction.value = meResp?.last_action || null
    if (showWelcome && lastAction.value) {
      ElMessage({
        type: 'info',
        duration: 5000,
        showClose: true,
        message: `欢迎回来 ${me.username || '用户'}，上次操作：${lastAction.value.action}（${lastAction.value.created_at}）`,
      })
      welcomeShown.value = true
    }
  } catch {
    user.value = null; tokenStore.clear()
  }

  if (user.value && !lastAction.value) {
    try {
      const last = await auditLast()
      lastAction.value = last?.last || null
      if (showWelcome && lastAction.value) {
        ElMessage({
          type: 'info',
          duration: 5000,
          showClose: true,
          message: `欢迎回来 ${user.value.username}，上次操作：${lastAction.value.action}（${lastAction.value.created_at}）`,
        })
      }
    } catch {}
  }
}

function handleCommand(cmd) {
  if (cmd === 'profile') router.push('/profile')
  else if (cmd === 'history') router.push('/history')
  else if (cmd === 'admin') router.push('/admin')
  else if (cmd === 'logout') doLogout()
  else if (cmd === 'login') router.push('/login')
}

async function doLogout() {
  try { await authLogout() } catch {}
  tokenStore.clear()
  user.value = null
  lastAction.value = null
  ElMessage.success('已退出登录')
  if (route.meta?.requireAuth) router.push('/dashboard')
}

const CaretBottom = defineComponent({
  name: 'CaretBottom',
  render() {
    return h('svg', { width: '12', height: '12', viewBox: '0 0 12 12' }, [
      h('path', { d: 'M3 5l3 3 3-3z', fill: 'currentColor' })
    ])
  },
})
</script>

<template>
  <router-view v-if="route.path === '/login' || route.path === '/admin/login'"></router-view>

  <div v-else class="app-root" :class="{ 'app-mobile': isMobile }">
    <!-- 移动端遮罩层 -->
    <div v-if="isMobile && menuOpen" class="mobile-backdrop" @click="closeMenu"></div>

    <!-- 侧边栏：桌面端固定宽；移动端抽屉 -->
    <aside class="app-aside" :class="{ 'aside-open': menuOpen }">
      <div class="aside-head">
        <div class="aside-brand">🚀 webstock</div>
        <div class="aside-version">{{ version || '加载中…' }}</div>
      </div>
      <div class="aside-body">
        <div v-for="group in fullNav" :key="group.key" class="nav-group">
          <div class="nav-group-title">{{ group.title }}</div>
          <div
            v-for="m in group.items" :key="m.key"
            class="nav-item"
            :class="{ 'nav-active': active === m.key }"
            @click="() => { go(m.key); if (isMobile) closeMenu() }"
            @mouseenter="e => !active.endsWith(m.key) && (e.currentTarget.style.background = '#3a3c40')"
            @mouseleave="e => !active.endsWith(m.key) && (e.currentTarget.style.background = 'transparent')"
          >
            <span class="nav-label">{{ m.title }}</span>
            <span v-if="m.requireAuth && !user" class="nav-auth-badge">登录</span>
          </div>
        </div>
      </div>
    </aside>

    <div class="app-main-wrap">
      <header class="app-header">
        <button v-if="isMobile" class="hamburger" @click="toggleMenu" aria-label="菜单">
          <span></span><span></span><span></span>
        </button>
        <div class="header-title">{{ route.meta.title || '' }}</div>
        <div class="header-spacer"></div>

        <div v-if="!user" class="header-guest">
          <span class="header-guest-text">登录后操作会被记录</span>
          <el-button type="primary" size="small" @click="$router.push('/login')">登录 / 注册</el-button>
        </div>

        <el-dropdown v-else trigger="click" @command="handleCommand" placement="bottom-end">
          <div class="user-pill"
               @mouseenter="e => e.currentTarget.style.background = '#f2f3f5'"
               @mouseleave="e => e.currentTarget.style.background = 'transparent'">
            <el-avatar :size="30" class="user-avatar">{{ (user.username || 'U').charAt(0).toUpperCase() }}</el-avatar>
            <div class="user-info" :class="{ 'user-info-hidden': isMobile }">
              <div class="user-name">{{ user.username }}</div>
              <div v-if="lastAction" class="user-last">上次：{{ lastAction.action }}</div>
            </div>
            <el-icon :size="12" class="user-caret"><CaretBottom /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile" @click="isMobile && closeMenu()">👤 个人中心</el-dropdown-item>
              <el-dropdown-item command="history" @click="isMobile && closeMenu()">🧾 操作历史</el-dropdown-item>
              <el-dropdown-item v-if="user?.is_admin" command="admin" divided @click="isMobile && closeMenu()">🛡️ 管理后台</el-dropdown-item>
              <el-dropdown-item divided command="logout">🚪 退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style>
/* ========== 桌面端（默认） ========== */
.app-root {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-aside {
  width: 210px;
  min-width: 210px;
  background: var(--nav-bg);
  color: #fff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.aside-head {
  padding: 18px 16px;
  border-bottom: 1px solid #3a3c40;
}
.aside-brand { font-weight: 700; font-size: 16px; }
.aside-version { font-weight: 400; font-size: 12px; color: #86909c; margin-top: 4px; }
.aside-body { flex: 1; overflow: hidden; }
.el-scrollbar { height: 100%; }
.nav-group { margin-top: 12px; }
.nav-group-title { padding: 8px 16px; font-size: 12px; color: #7a7f87; letter-spacing: .5px; }
.nav-item {
  padding: 10px 16px 10px 28px;
  cursor: pointer;
  color: #c8ccd2;
  font-size: 14px;
  border-left: 3px solid transparent;
  display: flex;
  align-items: center;
  gap: 6px;
}
.nav-active {
  background: var(--nav-active);
  color: #fff;
  border-left-color: #fff;
}
.nav-auth-badge { color: #ff9a3c; margin-left: 6px; font-size: 11px; }

.app-main-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.app-header {
  height: 56px;
  min-height: 56px;
  background: #fff;
  border-bottom: 1px solid #e5e6eb;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
}
.header-title { font-weight: 600; font-size: 16px; }
.header-spacer { flex: 1; }
.header-guest { display: flex; gap: 8px; align-items: center; }
.header-guest-text { color: #86909c; font-size: 12px; }
.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
}
.user-avatar { background: #4e83fd; }
.user-info { font-size: 13px; }
.user-name { font-weight: 600; }
.user-last { color: #86909c; font-size: 11px; }

.app-main {
  flex: 1;
  padding: 16px 20px;
  overflow: auto;
  background: var(--content-bg);
}

/* ========== 移动端 ≤768px ========== */
@media (max-width: 768px) {
  .app-root.app-mobile {
    display: block;
    height: 100vh;
  }
  .app-aside {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 260px;
    min-width: 260px;
    z-index: 2000;
    transform: translateX(-100%);
    transition: transform .25s cubic-bezier(.4,0,.2,1);
    box-shadow: none;
  }
  .aside-open {
    transform: translateX(0);
    box-shadow: 4px 0 16px rgba(0,0,0,.18);
  }
  .mobile-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0,0,0,.45);
    z-index: 1999;
  }

  .app-main-wrap {
    padding-top: 56px; /* header 高度 */
  }
  .app-header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 52px;
    min-height: 52px;
    z-index: 1500;
    padding: 0 12px;
    gap: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .hamburger {
    background: none;
    border: none;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 4px;
    padding: 8px;
    border-radius: 6px;
    line-height: 0;
  }
  .hamburger > span {
    display: block;
    width: 18px;
    height: 2px;
    background: var(--text-primary);
    border-radius: 2px;
  }
  .hamburger:active { background: #f2f3f5; }
  .header-title { font-size: 14px; font-weight: 600; }
  .user-info-hidden { display: none; }
  .user-pill { padding: 2px 4px; }
  .header-guest-text { display: none; }

  .app-main {
    padding: 12px 8px;
    height: calc(100vh - 52px);
  }

  /* 卡片紧凑化 */
  .card { padding: 12px 10px; margin-bottom: 12px; }
  .page-title { font-size: 16px !important; }
  .page-desc { font-size: 12px !important; margin-bottom: 12px !important; }

  /* Element Plus 表格：允许横向滚动 */
  .el-table { width: 100%; min-width: 600px; }
  .el-table__body-wrapper { overflow-x: auto; overflow-y: auto; }

  /* 表单、按钮紧凑 */
  .el-form-item { margin-bottom: 12px; }
  .el-row { flex-wrap: wrap; row-gap: 8px; }
}

/* 动画 */
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
