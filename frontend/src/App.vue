<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { sysHealth, sysVersion } from './api/index.js'

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
  { key: 'system', title: '系统', items: [
    { key: '/dashboard', title: '⚙️ 设置（占位）' },
  ]},
]

const active = computed(() => route.path)
function go(p) { router.push(p) }

const version = ref('')
onMounted(async () => {
  try {
    const v = await sysVersion()
    version.value = `${v.name} ${v.version}`
  } catch {}
  try { await sysHealth() } catch (e) {
    ElMessage.warning('后端服务未就绪：' + e.message)
  }
})
</script>

<template>
  <el-container style="height:100vh">
    <el-aside width="210px" style="background: var(--nav-bg); color:#fff; display:flex; flex-direction:column">
      <div style="padding:18px 16px; font-weight:700; font-size:16px; border-bottom:1px solid #3a3c40">
        🚀 webstock
        <div style="font-weight:400; font-size:12px; color:#86909c; margin-top:4px">{{ version || '加载中…' }}</div>
      </div>
      <el-scrollbar style="flex:1">
        <div v-for="group in navMenu" :key="group.key" style="margin-top:12px">
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
          </div>
        </div>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <el-header style="background:#fff; border-bottom:1px solid #e5e6eb; display:flex; align-items:center">
        <div style="font-weight:600; font-size:16px">{{ route.meta.title || '' }}</div>
        <div style="flex:1"></div>
        <div style="color:#86909c; font-size:12px">点击左侧菜单切换模块</div>
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
