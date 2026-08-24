<script setup>
import { computed, onMounted, ref, markRaw } from 'vue'
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

// --- 全局图标组件（内联注册，供模板使用）---
const CaretBottom = defineComponent({
  name: 'CaretBottom',
  render() {
    return h('svg', { width: '12', height: '12', viewBox: '0 0 12 12' }, [
      h('path', { d: 'M3 5l3 3 3-3z', fill: 'currentColor' })
    ])
  },
})

</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
