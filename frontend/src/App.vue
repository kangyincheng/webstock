<script setup>
import { computed, onMounted, ref, markRaw, defineComponent, h } from 'vue'
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

// 管理员菜单（仅 is_admin 用户可见）
const adminMenu = {
  key: 'admin', title: '管理后台', items: [
    { key: '/admin', title: '🛡️ 后台首页' },
    { key: '/admin/users', title: '👥 用户管理' },
    { key: '/admin/audit', title: '📋 全局审计' },
  ],
}

// 合并管理员菜单（仅当前用户 is_admin 时显示）
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

async function refreshMe(showWelcome = false) {
  if (!tokenStore.isLoggedIn()) { user.value = null; return }
  try {
    const meResp = await authMe()
    // /auth/me 格式：{ auth, user, last_action, recent_history }
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

onMounted(async () => {
  try {
    const v = await sysVersion()
    version.value = `${v.name} ${v.version}`
  } catch {}
  try { await sysHealth() } catch (e) {
    ElMessage.warning('后端服务未就绪：' + e.message)
  }
  await refreshMe(true)
})

// --- 全局图标组件（内联注册，setup 作用域自动暴露给模板）---
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
  <!-- 登录页 / 管理员登录页独立布局 -->
  <router-view v-if="route.path === '/login' || route.path === '/admin/login'"></router-view>

  <el-container v-else style="height:100vh">
    <el-aside width="210px" style="background: var(--nav-bg); color:#fff; display:flex; flex-direction:column">
      <div style="padding:18px 16px; font-weight:700; font-size:16px; border-bottom:1px solid #3a3c40">
        🚀 webstock
        <div style="font-weight:400; font-size:12px; color:#86909c; margin-top:4px">{{ version || '加载中…' }}</div>
      </div>
      <el-scrollbar style="flex:1">
        <div v-for="group in fullNav" :key="group.key" style="margin-top:12px">
          <div style="padding:8px 16px; font-size:12px; color:#7a7f87; letter-spacing:.5px">{{ group.title }}</div>
          <div
            v-for="m in group.items" :key="m.key"
            @click="go(m.key)"
            :style="{
              padding:'10px 16px 10px 28px', cursor:'pointer',
              background: active === m.key ? 'var(--nav-active)' : 'transparent',
              color: active === m.key ? '#fff' : '#c8ccd2',
              fontSize: '14px',
              borderLeft: active === m.key ? '3px solid #fff' : '3px solid transparent',
            }"
            :class="{ hoverable: true }"
            @mouseenter="e => !active.endsWith(m.key) && (e.currentTarget.style.background = '#3a3c40')"
            @mouseleave="e => !active.endsWith(m.key) && (e.currentTarget.style.background = 'transparent')"
          >
            {{ m.title }}
            <span v-if="m.requireAuth && !user" style="color:#ff9a3c; margin-left:6px; font-size:11px">登录</span>
          </div>
        </div>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <el-header style="background:#fff; border-bottom:1px solid #e5e6eb; display:flex; align-items:center">
        <div style="font-weight:600; font-size:16px">{{ route.meta.title || '' }}</div>
        <div style="flex:1"></div>

        <div v-if="!user" style="display:flex; gap:8px; align-items:center">
          <div style="color:#86909c; font-size:12px">登录后操作会被记录</div>
          <el-button type="primary" size="small" @click="$router.push('/login')">登录 / 注册</el-button>
        </div>

        <el-dropdown v-else trigger="click" @command="handleCommand">
          <div style="display:flex; align-items:center; gap:8px; cursor:pointer; padding:4px 8px; border-radius:8px"
               @mouseenter="e => e.currentTarget.style.background = '#f2f3f5'"
               @mouseleave="e => e.currentTarget.style.background = 'transparent'">
            <el-avatar :size="30" style="background:#4e83fd">{{ (user.username || 'U').charAt(0).toUpperCase() }}</el-avatar>
            <div style="font-size:13px">
              <div style="font-weight:600">{{ user.username }}</div>
              <div v-if="lastAction" style="color:#86909c; font-size:11px">上次：{{ lastAction.action }}</div>
            </div>
            <el-icon :size="12"><CaretBottom /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">👤 个人中心</el-dropdown-item>
              <el-dropdown-item command="history">🧾 操作历史</el-dropdown-item>
              <el-dropdown-item v-if="user?.is_admin" command="admin" divided>🛡️ 管理后台</el-dropdown-item>
              <el-dropdown-item divided command="logout">🚪 退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main>
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>


<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
