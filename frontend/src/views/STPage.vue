<script setup>
import { reactive, ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { stScan } from '../api/index.js'

// ============= 参数 =============
const N_OPTIONS = [5, 10, 15, 20]
const beforeSel = ref(15)   // 摘帽前选哪个
const afterSel = ref(15)    // 摘帽后选哪个

// ============= 数据 =============
const rows1Raw = ref([])
const loading1 = ref(true)

// ============= 排序 + 分页 =============
const sort1 = reactive({ prop: '', order: '' })
const PAGE_SIZES = [20, 50, 100, 200]
const pager1 = reactive({ page: 1, size: 50 })

function cmpFn(a, b, prop) {
  let x = a?.[prop], y = b?.[prop]
  const xNil = x === null || x === undefined || x === ''
  const yNil = y === null || y === undefined || y === ''
  if (xNil && yNil) return 0
  if (xNil) return 1
  if (yNil) return -1
  const nx = Number(x), ny = Number(y)
  if (!isNaN(nx) && !isNaN(ny)) return nx - ny
  return String(x).localeCompare(String(y), 'zh-CN', { numeric: true })
}

// 表1：按选中的 N 列排序
const rows1Sorted = computed(() => {
  const arr = [...rows1Raw.value]
  if (sort1.prop && sort1.order) {
    const sgn = sort1.order === 'ascending' ? 1 : -1
    arr.sort((a, b) => cmpFn(a, b, sort1.prop) * sgn)
  }
  return arr
})
const pager1Total = computed(() => rows1Sorted.value.length)
const rows1Page = computed(() => {
  const a = (pager1.page - 1) * pager1.size
  return rows1Sorted.value.slice(a, a + pager1.size)
})
watch(rows1Sorted, () => { pager1.page = 1 })

// ============= 动态列 =============
const preColKey = computed(() => `前${beforeSel.value}`)
const postColKey = computed(() => `后${afterSel.value}`)
const preColLabel = computed(() => `摘帽前${beforeSel.value}日(%)`)
const postColLabel = computed(() => `摘帽后${afterSel.value}日(%)`)

const COLS1 = computed(() => [
  { prop: '股票名称', label: '股票名称', w: 110, fixed: 'left' },
  { prop: '代码', label: '代码', w: 120 },
  { prop: '最新价', label: '最新价', w: 90, numeric: true },
  { prop: '结束ST日期', label: '摘帽日期', w: 120 },
  { prop: preColKey.value, label: preColLabel.value, w: 120, numeric: true, tone: true },
  { prop: postColKey.value, label: postColLabel.value, w: 120, numeric: true, tone: true },
  { prop: '市盈率', label: 'PE', w: 80, numeric: true },
  { prop: '市净率', label: 'PB', w: 80, numeric: true },
  { prop: '摘帽日收盘价', label: '摘帽日收盘价', w: 110, numeric: true },
])

// ============= 样式回调 =============
function cellTone({ row, column }) {
  const p = column.property
  if (p !== preColKey.value && p !== postColKey.value) return ''
  const v = Number(row[p])
  if (!isFinite(v)) return ''
  return v >= 0 ? 'cell-up' : 'cell-down'
}
function rowTone1({ row }) {
  const v = Number(row[postColKey.value])
  if (!isFinite(v)) return ''
  return v >= 0 ? 'row-up' : 'row-down'
}

// ============= 统计（基于选中的 N）=============
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

// ============= 图表 =============
const chartRef = ref(null)
let chartInst = null, resizeHandler = null

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
  await runScan()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onChartResize)
  if (chartInst) { chartInst.dispose(); chartInst = null }
})

// ============= 动作 =============
async function runScan() {
  loading1.value = true
  try {
    const d = await stScan({ months_back: 24, before_days: 20, after_days: 20 })
    rows1Raw.value = Array.isArray(d?.records) ? d.records : Array.isArray(d) ? d : []
    const msg = d?.message || `完成：${rows1Raw.value.length} 条`
    if (d?.cache_hit) ElMessage.success(`${msg}（缓存）`)
    else ElMessage.success(msg)
  } catch (e) { ElMessage.error(e?.message || '加载失败') }
  finally { loading1.value = false }
}

function onSortChange1({ prop, order }) {
  sort1.prop = prop || ''
  sort1.order = order || ''
}
</script>

<template>
  <div>
    <h2 class="page-title">ST 摘帽 / ST 恢复上市</h2>
    <p class="page-desc">
      已摘帽股行情表现（数据源：巨潮资讯公告 + 新浪财经历史K线 + 实时行情）。
      数据已预计算，后台更新时直接替换 <code>backend/data/st_scan_results.json</code> 即可。
    </p>

    <!-- ========== 表 1 ========== -->
    <div class="card">
      <div class="card-title-row">
        <h3 class="card-title">ST股摘帽前后表现</h3>
        <span class="card-sub">
          共 {{ pager1Total }} 条
          <span v-if="loading1">· 加载中…</span>
        </span>
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

      <!-- 图表 -->
      <div v-if="stats1" class="chart-box">
        <div class="chart-title">摘帽后涨幅 TOP15（红色=上涨 绿色=下跌，灰色=摘帽前）</div>
        <div ref="chartRef" style="width:100%;height:340px"></div>
      </div>

      <!-- 下拉选择器：控制表格显示哪个 N 值 -->
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
        <el-button size="small" @click="runScan" :loading="loading1">重新加载</el-button>
      </div>

      <!-- 表格：固定高度 + 横向滚动 -->
      <el-table
        :data="rows1Page"
        stripe
        border
        height="560"
        style="width: 100%"
        :row-class-name="rowTone1"
        :default-sort="{ prop: '结束ST日期', order: 'descending' }"
        @sort-change="onSortChange1">
        <el-table-column
          v-for="c in COLS1"
          :key="c.prop"
          :prop="c.prop"
          :label="c.label"
          :width="c.w"
          :min-width="c.w"
          :fixed="c.fixed"
          sortable="custom"
          show-overflow-tooltip
          align="center"
          :cell-class-name="cellTone" />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>

      <div class="pager-row">
        <el-pagination
          v-model:current-page="pager1.page"
          v-model:page-size="pager1.size"
          :page-sizes="PAGE_SIZES"
          layout="total, sizes, prev, pager, next, jumper"
          :total="pager1Total"
          background small />
      </div>
    </div>
  </div>
</template>

<style scoped>
:deep(.cell-up) { color: #F5222D !important; font-weight: 600; }
:deep(.cell-down) { color: #52C41A !important; font-weight: 600; }
:deep(.row-up td) { background: #fff6f6 !important; }
:deep(.row-down td) { background: #f2fff4 !important; }

.card-title-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0 4px 12px 4px; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 16px;
}
.card-title {
  margin: 0; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary);
  letter-spacing: 0.5px;
}
.card-sub { color: var(--el-text-color-secondary); font-size: 12px; }
.pager-row { display: flex; justify-content: flex-end; margin-top: 12px; }

.selector-bar {
  display: flex; align-items: center; gap: 16px;
  padding: 12px 0; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 12px;
}
.selector { display: flex; align-items: center; gap: 6px; }
.selector-label {
  font-size: 13px; color: var(--el-text-color-regular); font-weight: 500;
}

/* 统计卡片 */
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
