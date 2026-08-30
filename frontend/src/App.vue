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
    /* 关键：桌面端 overflow:hidden 会锁死手机整页滚动，必须放开 */
    overflow: visible;
    height: auto;
    min-height: 100vh;
    min-height: 100dvh; /* 兼容移动端动态地址栏 */
  }
  html, body {
    /* 解锁 body 层面潜在的 overflow/弹性回弹锁 */
    overflow-x: hidden;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-y: contain;
  }
  /* 所有按钮：移动端确保触控目标 ≥36px（覆盖 el-button--small 的 24px 默认值） */
  .el-button,
  .el-button--small {
    min-height: 36px;
    font-size: 14px;
    padding: 6px 14px;
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
    /* desktop: overflow:hidden → 移动端必须允许溢出滚动；同时 header=fixed 用 padding-top 占位 */
    padding-top: 56px;
    overflow: visible;
    min-height: 100vh;
    min-height: 100dvh;
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
    padding: 12px 10px 100px; /* 底部留足 100px 安全区 + 安全区适配 */
    padding-bottom: calc(100px + env(safe-area-inset-bottom, 0px));
    /* 关键：取消固定高度 calc(100vh - 52px)，改为自然高度 + 真正可滚动容器 */
    height: auto;
    min-height: calc(100vh - 52px);
    min-height: calc(100dvh - 52px);
    overflow: visible;
    overflow-y: visible;
    -webkit-overflow-scrolling: touch;
  }

  /* 卡片紧凑化 */
  .card { padding: 12px 10px; margin-bottom: 12px; }
  .page-title { font-size: 16px !important; }
  .page-desc { font-size: 12px !important; margin-bottom: 12px !important; }

  /* Element Plus 表格：取消硬编码固定 height，改为 max-height + 允许横向滚动 */
  .el-table { width: 100%; min-width: 600px; }
  .el-table[style*="height:"] {
    height: auto !important;
    max-height: 60vh !important;
  }
  .el-table__body-wrapper {
    overflow-x: auto !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  /* =========================================================
     内联表单（STPage / SectorHeat / HotStocks / CBond / History header 等）
     窄屏每个表单项占据整行，防止按钮被挤在窄列里看不见
     ========================================================= */
  .el-form--inline {
    display: flex !important;
    flex-direction: column !important;
    align-items: stretch !important;
  }
  .el-form--inline .el-form-item {
    display: flex;
    flex-direction: column;
    margin-right: 0 !important;
    margin-bottom: 12px;
    width: 100%;
  }
  .el-form--inline .el-form-item__content {
    width: 100% !important;
    display: block;
  }
  .el-form--inline .el-form-item__label {
    width: auto !important;
    text-align: left;
    margin-bottom: 4px;
    display: block;
  }
  /* 无 label 的 el-form-item（通常放提交按钮）：隐藏空 label 避免占位 */
  .el-form--inline .el-form-item .el-form-item__label:empty {
    display: none !important;
    height: 0;
    padding: 0;
    margin: 0;
  }
  .el-form--inline .el-form-item .el-form-item__label:empty + .el-form-item__content {
    margin-left: 0 !important;
  }
  /* 内联表单里的所有 primary 按钮：移动端确保独占一行 + 全宽 + 高可见
     不依赖 :last-child，避免 STPage 那种「筛选在按钮之后」的场景失效 */
  .el-form--inline .el-button[type="primary"],
  .el-form--inline .el-button--primary,
  .el-form--inline > .el-form-item .el-button[type="primary"],
  .el-form--inline > .el-form-item .el-button--primary {
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    width: 100% !important;
    height: 44px !important;
    min-height: 44px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    margin-top: 4px;
  }
  /* 内联表单所有输入控件占满宽度 */
  .el-form--inline .el-input,
  .el-form--inline .el-select,
  .el-form--inline .el-input-number {
    width: 100% !important;
  }

  /* =========================================================
     Element Plus 的 Row/Col 多列布局：窄屏强制单列
     （Dashboard 温度 + 板块；Predict 参数 + 结果 等）
     ⚠️ App.vue <style> 为非 scoped，:deep() 会被 Vue SFC 编译器剥离，
        此处必须用原生选择器；且 Element Plus 用 .el-col-6 / .el-col-18 等
        span 类控制宽度（同为单一 class 特异性），所以我们用
        「base class + attribute contains」复合选择器（2× specificity）
        确保覆盖 span 类的 width/flex-basis。
     ========================================================= */
  .el-row {
    flex-direction: column !important;
    row-gap: 12px !important;
    margin: 0 !important;
    display: block !important;
  }
  .el-col,
  .el-col[class*="el-col-"],
  .el-col[class*="el-col-xs-"],
  .el-col[class*="el-col-sm-"],
  .el-col[class*="el-col-md-"] {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    flex: 0 0 100% !important;
    flex-basis: 100% !important;
    padding: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    display: block !important;
  }

  /* =========================================================
     Dialog 底部按钮：手机键盘弹出时 footer 可能位于屏外，强制在视口内可见；
     并允许对话框在移动端滚动
     ========================================================= */
  .el-dialog {
    width: 92vw !important;
    max-width: 92vw !important;
    max-height: 86vh;
    max-height: 86dvh;
    display: flex;
    flex-direction: column;
    margin: 4vh auto !important;
  }
  .el-dialog__body {
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
    flex: 1;
  }
  .el-dialog__footer {
    padding-top: 12px;
    padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
    border-top: 1px solid #f2f3f5;
    background: #fff;
    position: sticky;
    bottom: 0;
    z-index: 2;
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 8px;
  }
  .el-dialog__footer .el-button {
    min-height: 40px;
    min-width: 88px;
    flex: 1 1 auto;
  }

  /* Dialog 内部的水平排列项（Favorites 事件行 等）自动换行 */
  .el-dialog__body [style*="display:flex"][style*="gap:"][style*="margin-bottom:"] {
    flex-wrap: wrap;
  }
  .el-dialog__body [style*="display:flex"][style*="gap:8px"] {
    flex-wrap: wrap;
  }
  .el-dialog__body [style*="display:flex"][style*="gap:8px"] > .el-input,
  .el-dialog__body [style*="display:flex"][style*="gap:8px"] > [style*="flex:1"],
  .el-dialog__body [style*="display:flex"][style*="gap:8px"] > [style*="width:180px"] {
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0;
  }
  .el-dialog__body [style*="display:flex"][style*="gap:8px"] > .el-button {
    flex: 1 1 auto;
    min-width: 44%;
  }

  /* =========================================================
     普通表单（Profile 改密碼、Favorites Dialog、Login 等）
     提交按钮全宽 + 高度足够
     ========================================================= */
  .el-form:not(.el-form--inline) .el-button[type="primary"],
  .el-form:not(.el-form--inline) .el-button--primary,
  .el-form[label-position="top"] .el-button[type="primary"],
  .el-form[label-position="top"] .el-button--primary {
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    width: 100% !important;
    height: 44px !important;
    min-height: 44px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
  }
  .el-form:not(.el-form--inline) .el-input,
  .el-form:not(.el-form--inline) .el-select,
  .el-form:not(.el-form--inline) .el-input-number {
    width: 100% !important;
  }

  /* 表单、按钮紧凑 */
  .el-form-item { margin-bottom: 12px; }
  .el-row { flex-wrap: wrap; row-gap: 8px; }

  /* =========================================================
     卡片 Header 里的水平工具栏（History / AdminUsers / AdminAudit / Favorites 顶部）
     窄屏自动换行 + 控件占满宽度
     ========================================================= */
  .el-card__header [style*="display:flex"][style*="align-items:"],
  .el-card > :first-child [style*="display:flex"][style*="gap:12px"],
  .el-card > :first-child [style*="display:flex"][style*="align-items:center; gap:12px"] {
    flex-wrap: wrap !important;
    row-gap: 8px;
  }
  .el-card__header .el-input,
  .el-card__header .el-select,
  .el-card > :first-child .el-input,
  .el-card > :first-child .el-select {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0;
    flex: 1 1 160px;
  }
  .el-card__header .el-checkbox,
  .el-card > :first-child .el-checkbox {
    flex: 1 1 auto;
  }
  .el-card__header .el-button[type="primary"],
  .el-card > :first-child .el-button--primary {
    flex: 1 1 100%;
    width: 100%;
    min-height: 40px;
    font-size: 14px;
    font-weight: 600;
  }
  /* 卡片头部非 primary 按钮（刷新/导出等）：移动端确保触控目标够大 */
  .el-card__header .el-button:not(.el-button--primary),
  .el-card > :first-child .el-button:not(.el-button--primary) {
    min-height: 36px;
    min-width: 72px;
    font-size: 14px;
    padding: 6px 14px;
  }

  /* Favorites / History 顶部 el-space 操作按钮：每行最多 2 个，全宽高可见。
     ⚠️ 关键点：Element Plus 的 <el-space> 会把每个 button 包在 .el-space__item 容器里，
        真正的 flex 子项是 __item，不是 button；所以先让 __item grow，再让内中 button 撑满。 */
  .el-space {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    width: 100% !important;
    row-gap: 8px;
    column-gap: 8px;
  }
  .el-space__item {
    flex: 1 1 calc(50% - 8px) !important;
    display: block !important;
    max-width: 100% !important;
    min-width: 0 !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
  }
  .el-space__item > .el-button,
  .el-space > .el-button {
    width: 100% !important;
    max-width: 100% !important;
    min-height: 42px !important;
    font-size: 14px !important;
    white-space: normal !important;
    line-height: 1.2;
    padding: 8px 12px !important;
  }

  /* =========================================================
     Grid 多列布局的：窄屏改为单列/双列
     （Profile 左右 1.2fr 1fr；Admin 统计卡片 repeat(4, 1fr) 等）
     ========================================================= */
  [style*="grid-template-columns:"] {
    grid-template-columns: 1fr !important;
  }
  [style*="grid-template-columns: 1.2fr"] {
    grid-template-columns: 1fr !important;
  }
  [style*="grid-template-columns: repeat(4"] {
    grid-template-columns: repeat(2, 1fr) !important;
  }
  [style*="grid-template-columns: repeat(2"] {
    grid-template-columns: repeat(2, 1fr) !important;
  }
  [style*="grid-template-columns: repeat(3"] {
    grid-template-columns: repeat(2, 1fr) !important;
  }

  /* ECharts 图表容器：高度自适应。
     ⚠️ 不使用 [ref="chartRef"] — Vue 模板里的 ref 属性不渲染到真实 DOM。
     改用所有图表常见内联 height 值匹配：420/380/360/340/240px。 */
  [style*="height:420px"],
  [style*="height:380px"],
  [style*="height:360px"],
  [style*="height:340px"],
  [style*="height:240px"],
  [style*="height:500px"] {
    height: 280px !important;
  }

  /* 分页组件：窄屏自适应布局，允许折行 */
  .el-pagination {
    flex-wrap: wrap;
    justify-content: flex-start !important;
    row-gap: 6px;
  }

  /* Login 页：取消卡片 padding 最小值，按钮始终可触达 */
  [style*="min-height:100vh"][style*="linear-gradient"] {
    min-height: 100dvh !important;
    padding: 16px !important;
  }
}

/* 动画 */
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
