<script setup>
import { onMounted, onUnmounted, ref, markRaw, shallowRef } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { thermometer, sectorHeat, hotStocks } from '../api/index.js'

const therm = ref({ percent: 0, level: 'idle', above_count: 0, total: 0, date: '-' })
const thermColor = () => ({
  hot: '#F5222D', cold: '#52C41A', normal: '#1677FF', idle: '#C8CCD2',
}[therm.value.level] || '#C8CCD2')

const chart1 = shallowRef(null)
let c1 = null
const chart2 = shallowRef(null)
let c2 = null

const sectorRows = ref([])
const hotRows = ref([])
const loading = ref(false)

async function loadTherm() {
  try {
    const t = await thermometer()
    if (t) Object.assign(therm.value, t)
  } catch (e) { ElMessage.error('温度计加载失败：' + e.message) }
}

function renderSectorChart() {
  if (!sectorRows.value.length) return
  const rows = [...sectorRows.value].slice(0, 20).reverse()
  const option = {
    grid: { left: 120, right: 24, top: 16, bottom: 16 },
    xAxis: { type: 'value', name: '平均涨幅%' },
    yAxis: { type: 'category', data: rows.map(r => r.industry || r['板块名称'] || r.rank) },
    series: [{
      type: 'bar',
      data: rows.map(r => Number(r.avg_chg ?? r['平均涨幅(%)'] ?? 0)),
      itemStyle: { color: p => p.value >= 0 ? '#F5222D' : '#52C41A' }
    }]
  }
  c1.setOption(option)
}

function renderHotChart() {
  if (!hotRows.value.length) return
  const rows = [...hotRows.value].slice(0, 30)
  const option = {
    grid: { left: 48, right: 48, top: 48, bottom: 36 },
    tooltip: {
      formatter: (p) => {
        const r = rows[p.dataIndex]
        const name = r.name || r['股票名称']
        const amt = (Number(r.amount ?? r['成交额(万元)'] ?? 0) / 10000).toFixed(2)
        return `${name}<br/>涨幅: ${p.value[0]}%<br/>成交额(亿): ${amt}`
      }
    },
    xAxis: { type: 'value', name: '涨跌幅%' },
    yAxis: { type: 'value', name: '成交量(手)' },
    series: [{
      type: 'scatter',
      symbolSize: (d) => Math.min(60, Math.sqrt(Number(d[2] || 1)) * 4 + 6),
      data: rows.map(r => [Number(r.pct_chg ?? r['涨跌幅(%)'] ?? 0),
                           Number(r.vol ?? r['成交量(手)'] ?? 0),
                           Number(r.amount ?? r['成交额(万元)'] ?? 0)])
    }]
  }
  c2.setOption(option)
}

async function loadAll() {
  loading.value = true
  try {
    const [sec, hot] = await Promise.all([
      sectorHeat({ trade_date: '', use_cache: true }),
      hotStocks({ trade_date: '', sort_by: 'amount', top_n: 50, filter_keyword: '', use_cache: true }),
    ])
    sectorRows.value = sec?.rows || []
    hotRows.value = hot?.rows || []
    renderSectorChart()
    renderHotChart()
  } catch (e) { ElMessage.error('板块/热门加载失败：' + e.message) }
  finally { loading.value = false }
}

const ticker = ref(0)
let timer = null

onMounted(() => {
  c1 = echarts.init(chart1.value)
  c2 = echarts.init(chart2.value)
  const resize = () => { c1?.resize(); c2?.resize() }
  window.addEventListener('resize', resize)
  window.__ws_resize = resize

  loadTherm()
  loadAll()

  timer = setInterval(async () => {
    ticker.value++
    if (ticker.value % 20 === 0) await loadTherm().catch(() => {})
  }, 3_000)
})
onUnmounted(() => {
  clearInterval(timer)
  c1?.dispose()
  c2?.dispose()
})
</script>

<template>
  <div>
    <h2 class="page-title">数据看板</h2>
    <p class="page-desc">市场温度计（20日均线占比）· 板块涨幅 Top 20 · 热门股票 TOP 30 散点。</p>

    <el-row :gutter="16">
      <el-col :span="6">
        <div class="card" style="text-align:center">
          <div style="color:var(--text-secondary); font-size:13px">市场温度</div>
          <div style="font-size:48px; font-weight:700; color:v-bind('thermColor()'); margin:8px 0">
            {{ therm.percent }}%
          </div>
          <div style="font-size:12px; color:var(--text-secondary)">
            {{ therm.above_count }} / {{ therm.total }} 只在均线上方 · {{ therm.date }}
          </div>
          <el-progress
            :percentage="therm.percent"
            :color="[{pct:20,color:'#52C41A'},{pct:80,color:'#1677FF'},{pct:100,color:'#F5222D'}]"
            :stroke-width="14"
            style="margin-top:12px"
          />
          <el-button size="small" style="margin-top:12px" @click="loadTherm">刷新</el-button>
        </div>
      </el-col>
      <el-col :span="18">
        <div class="card">
          <div style="display:flex; align-items:center; margin-bottom:12px">
            <div style="font-weight:600">板块涨幅 Top 20（行业平均涨幅）</div>
            <div style="flex:1"></div>
            <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
          </div>
          <div ref="chart1" style="height:340px"></div>
        </div>
      </el-col>
    </el-row>

    <div class="card">
      <div style="font-weight:600; margin-bottom:12px">热门股票 TOP 30 散点（X=涨幅 Y=成交量，点大小=成交额）</div>
      <div ref="chart2" style="height:380px"></div>
    </div>
  </div>
</template>
