<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick, defineComponent, h } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { stScan } from '../api/index.js'
import { tokenStore } from '../api/http.js'

const N_OPTIONS = [5, 10, 15, 20]
const beforeSel = ref(15)
const afterSel = ref(15)

const rows1Raw = ref([])
const loading1 = ref(true)

const isAdmin = computed(() => !!tokenStore.user?.is_admin)

const preColKey = computed(() => `前${beforeSel.value}`)
const postColKey = computed(() => `后${afterSel.value}`)
const preColLabel = computed(() => `摘帽前${beforeSel.value}日(%)`)
const postColLabel = computed(() => `摘帽后${afterSel.value}日(%)`)

// ---- 统计卡 ----
const stats1 = computed(() => {
  const rows = rows1Raw.value
  const n = rows.length
  if (!n) return null
  let up = 0, down = 0, flat = 0
  let preSum = 0, preN = 0, postSum = 0, postN = 0
  const upList = []
  for (const r of rows) {
    const pre = Number(r[preColKey.value])
    const post = Number(r[postColKey.value])
    if (isFinite(post)) {
      postSum += post; postN++
      if (post > 0) up++
      else if (post < 0) down++
      else flat++
      if (post > 0) upList.push({ name: r['股票名称'], v: post })
    }
    if (isFinite(pre)) { preSum += pre; preN++ }
  }
  upList.sort((a, b) => b.v - a.v)
  const median = (arr) => {
    if (!arr.length) return null
    const s = [...arr].sort((a, b) => a - b)
    const m = Math.floor(s.length / 2)
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
  }
  const postAll = rows.map(r => Number(r[postColKey.value])).filter(isFinite)
  return {
    n, up, down, flat,
    upRate: postN ? (up / postN * 100).toFixed(1) : '0',
    preAvg: preN ? (preSum / preN).toFixed(2) : null,
    postAvg: postN ? (postSum / postN).toFixed(2) : null,
    postMedian: postN ? median(postAll).toFixed(2) : null,
    upBest: upList.length ? upList[0] : null,
    upList: upList.slice(0, 15),
  }
})

// ---- 图表 ----
const chartRef = ref(null)
let chartInst = null
let resizeHandler = null

function renderChart() {
  const el = chartRef.value
  if (!el) return
  if (!chartInst) chartInst = echarts.init(el)
  const rows = rows1Raw.value
    .filter(r => isFinite(Number(r[postColKey.value])))
    .sort((a, b) => Number(b[postColKey.value]) - Number(a[postColKey.value]))
    .slice(0, 15)
  if (!rows.length) { chartInst.clear(); return }
  const names = rows.map(r => r['股票名称'])
  const pre = rows.map(r => { const v = Number(r[preColKey.value]); return isFinite(v) ? v : null })
  const post = rows.map(r => Number(r[postColKey.value]))
  chartInst.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      valueFormatter: v => (v === null || v === undefined ? '-' : v + '%') },
    legend: { data: [preColLabel.value, postColLabel.value], top: 0 },
    grid: { left: 10, right: 20, top: 34, bottom: 6, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    yAxis: { type: 'category',
      data: names.map(n => n.length > 8 ? n.slice(0, 8) + '…' : n) },
    series: [
      { name: preColLabel.value, type: 'bar', data: pre, barGap: '-100%', itemStyle: { color: '#C0C4CC' } },
      { name: postColLabel.value, type: 'bar', data: post, itemStyle: { color: p => p.value >= 0 ? '#F5222D' : '#52C41A' } },
    ],
  })
}
function onChartResize() { if (chartInst) chartInst.resize() }

watch([rows1Raw, preColKey, postColKey], () => { nextTick(renderChart) }, { deep: true })

onMounted(async () => {
  nextTick(() => { renderChart(); window.addEventListener('resize', onChartResize) })
  loading1.value = true
  try {
    const d = await stScan({ months_back: 24, before_days: 20, after_days: 20 })
    rows1Raw.value = Array.isArray(d?.records) ? d.records : Array.isArray(d) ? d : []
  } catch (e) { ElMessage.error(e?.message || '加载失败') }
  finally { loading1.value = false }
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onChartResize)
  if (chartInst) { chartInst.dispose(); chartInst = null }
})
</script>

<template>
  <div>
    <h2 class="page-title">ST 股个股表现 · 统计概览</h2>
    <p class="page-desc">
      640 只已摘帽股票：整体摘帽前/后涨幅统计 + 摘帽后涨幅 TOP15 图表。
      可切换摘帽前/后统计的交易日数。
      <router-link v-if="isAdmin" to="/admin/st" class="admin-link">管理员维护 →</router-link>
    </p>

    <div class="card" v-loading="loading1">
      <div class="card-title-row">
        <h3 class="card-title">数据概览</h3>
        <span class="card-sub">共 {{ stats1?.n || 0 }} 条</span>
      </div>

      <!-- 统计卡片 -->
      <div v-if="stats1" class="stat-grid">
        <div class="stat-card">
          <div class="stat-num">{{ stats1.n }}</div>
          <div class="stat-label">摘帽股总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" :style="{ color: (stats1.upRate >= 50 ? '#F5222D' : '#52C41A') }">{{ stats1.upRate }}%</div>
          <div class="stat-label">摘帽后盈利占比（{{ stats1.up }}/{{ stats1.up + stats1.down + stats1.flat }}）</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ stats1.preAvg !== null ? stats1.preAvg + '%' : '-' }}</div>
          <div class="stat-label">{{ preColLabel }} 平均</div>
        </div>
        <div class="stat-card">
          <div class="stat-num" :style="{ color: (Number(stats1.postAvg) >= 0 ? '#F5222D' : '#52C41A') }">{{ stats1.postAvg !== null ? stats1.postAvg + '%' : '-' }}</div>
          <div class="stat-label">{{ postColLabel }} 平均</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ stats1.postMedian !== null ? stats1.postMedian + '%' : '-' }}</div>
          <div class="stat-label">{{ postColLabel }} 中位数</div>
        </div>
      </div>

      <!-- 下拉选择器 -->
      <div class="selector-bar">
        <div class="selector">
          <span class="selector-label">摘帽前</span>
          <el-select v-model="beforeSel" size="default" style="width: 100px">
            <el-option v-for="n in N_OPTIONS" :key="n" :label="n + '日'" :value="n" />
          </el-select>
          <span class="selector-label">摘帽后</span>
          <el-select v-model="afterSel" size="default" style="width: 100px">
            <el-option v-for="n in N_OPTIONS" :key="n" :label="n + '日'" :value="n" />
          </el-select>
        </div>
      </div>

      <!-- 图表 -->
      <div v-if="stats1" class="chart-box">
        <div class="chart-title">摘帽后涨幅 TOP15（红色=上涨 绿色=下跌，灰色=摘帽前）</div>
        <div ref="chartRef" style="width:100%;height:380px"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-link { margin-left: 6px; color: var(--el-color-primary); font-weight: 500; text-decoration: none; }
.admin-link:hover { text-decoration: underline; }

.card-title-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0 4px 12px 4px; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 16px;
}
.card-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
.card-sub { color: var(--el-text-color-secondary); font-size: 12px; }

.selector-bar {
  display: flex; align-items: center; gap: 16px;
  padding: 0 0 12px 0;
}
.selector { display: flex; align-items: center; gap: 6px; }
.selector-label { font-size: 13px; color: var(--el-text-color-regular); font-weight: 500; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 16px;
}
.stat-card {
  background: var(--el-fill-color-light, #f5f7fa);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px; padding: 14px 16px; text-align: center;
}
.stat-num { font-size: 24px; font-weight: 700; color: var(--el-text-color-primary); line-height: 1.2; }
.stat-label { margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); }

.chart-box {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px; padding: 12px; margin-bottom: 16px;
}
.chart-title {
  font-size: 13px; color: var(--el-text-color-regular);
  margin-bottom: 8px; font-weight: 500;
}
</style>
