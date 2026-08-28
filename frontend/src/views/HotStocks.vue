<script setup>
import { reactive, ref, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { hotStocks } from '../api/index.js'

const params = reactive({
  trade_date: '',
  sort_by: 'pct_chg',
  top_n: 30,
  filter_keyword: '',
  use_cache: true,
})
const rows = ref([])
const loading = ref(false)
const sortState = reactive({ key: '', order: 'desc' })

const chartRef = shallowRef(null)
let ch = null
let resizeHandler = null

async function load() {
  loading.value = true
  try {
    const r = await hotStocks({ ...params })
    rows.value = r.rows || []
    renderChart()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

// X = 涨幅(%)  Y = 成交量(手)  点大小 = 成交额(万元)
function renderChart() {
  if (!ch) return
  const data = rows.value.map((r) => ({
    name: r.name,
    code: r.code,
    industry: r.industry,
    close: Number(r.close) || 0,
    value: [
      Number(r['pct_chg(%)']) || 0,      // X 涨幅
      Number(r['vol(手)']) || 0,          // Y 成交量
      Number(r['amount(万元)']) || 0,     // Z 成交额 → 映射为符号大小
    ],
  }))
  const opts = {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const d = p.data
        return `<div style="font-size:12px;line-height:1.6">
          <b>${d.name}</b> (${d.code})<br/>
          板块: ${d.industry || '-'}<br/>
          涨幅: ${d.value[0]}%<br/>
          成交量: ${(d.value[1] / 10000).toFixed(2)} 万手<br/>
          成交额: ${(d.value[2] / 10000).toFixed(2)} 亿元<br/>
          收盘价: ${d.close}
        </div>`
      },
    },
    grid: { left: 60, right: 24, top: 24, bottom: 44 },
    xAxis: {
      type: 'value',
      name: '涨幅 (%)',
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { formatter: '{value}%' },
      splitLine: { show: true },
    },
    yAxis: {
      type: 'value',
      name: '成交量 (手)',
      nameLocation: 'middle',
      nameGap: 56,
      axisLabel: {
        formatter: (v) => {
          if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
          if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
          return v
        },
      },
      splitLine: { show: true },
    },
    series: [{
      type: 'scatter',
      data: data,
      symbolSize: (val) => {
        // 成交额 0~300 亿 映射到 6~50 像素
        const amtYi = (val[2] || 0) / 10000
        return Math.max(6, Math.min(50, Math.sqrt(amtYi) * 6))
      },
      itemStyle: {
        color: (p) => {
          // 涨幅正红负绿
          return p.value[0] >= 0 ? 'rgba(245,34,45,0.7)' : 'rgba(82,196,26,0.7)'
        },
        borderColor: '#fff',
        borderWidth: 1,
        shadowBlur: 4,
        shadowColor: 'rgba(0,0,0,0.15)',
      },
      emphasis: {
        itemStyle: { borderColor: '#1677FF', borderWidth: 2 },
        label: {
          show: true,
          formatter: '{b}',
          fontSize: 11,
        },
      },
      label: {
        show: false,
        formatter: '{b}',
      },
    }],
  }
  ch.setOption(opts, true)
}

function sortChange({ prop, order }) {
  if (!order) { sortState.key = ''; return }
  sortState.key = prop
  sortState.order = order
}

function onResize() { if (ch) ch.resize() }

onMounted(() => {
  ch = echarts.init(chartRef.value)
  resizeHandler = onResize
  window.addEventListener('resize', resizeHandler)
  load()
})

onBeforeUnmount(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  if (ch) { ch.dispose(); ch = null }
})
</script>

<template>
  <div>
    <h2 class="page-title">热门股票 TOP 30</h2>
    <p class="page-desc">散点图：X=涨幅(%) Y=成交量(手) 点大小=成交额(万元) · 红=上涨 绿=下跌 · 下方为明细表格</p>

    <div class="card">
      <el-form :inline="true" :model="params">
        <el-form-item label="交易日">
          <el-input v-model="params.trade_date" placeholder="YYYYMMDD 或空" style="width:160px" />
        </el-form-item>
        <el-form-item label="排序方式">
          <el-select v-model="params.sort_by" style="width:130px">
            <el-option label="按涨幅" value="pct_chg" />
            <el-option label="按成交额" value="amount" />
            <el-option label="按成交量" value="vol" />
          </el-select>
        </el-form-item>
        <el-form-item label="TOP N">
          <el-input-number v-model="params.top_n" :min="10" :max="500" :step="10" style="width:120px" />
        </el-form-item>
        <el-form-item label="筛选">
          <el-input v-model="params.filter_keyword" placeholder="代码 / 名称" clearable style="width:160px" />
        </el-form-item>
        <el-form-item label="缓存">
          <el-switch v-model="params.use_cache" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">加载</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="card" style="margin-bottom:12px">
      <div style="display:flex; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px">
        <div style="font-weight:600">散点图（涨幅 vs 成交量）</div>
        <div style="flex:1"></div>
        <div style="display:flex; gap:12px; align-items:center; font-size:12px; color:#86909c">
          <span><i style="display:inline-block;width:10px;height:10px;background:rgba(245,34,45,.7);border-radius:50%;vertical-align:middle;margin-right:4px"></i>上涨</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:rgba(82,196,26,.7);border-radius:50%;vertical-align:middle;margin-right:4px"></i>下跌</span>
          <span>·</span>
          <span>点数=成交额</span>
        </div>
      </div>
      <div ref="chartRef" style="width:100%;height:420px"></div>
    </div>

    <div class="card">
      <el-table :data="rows" stripe border size="small" max-height="70vh" :loading="loading"
        :default-sort="{ prop: params.sort_by, order: 'descending' }"
        @sort-change="sortChange">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
        <el-table-column prop="code" label="代码" min-width="120" />
        <el-table-column prop="industry" label="板块" min-width="90" show-overflow-tooltip />
        <el-table-column prop="close" label="收盘价" min-width="80" sortable :sort-method="(a,b)=>a.close-b.close" />
        <el-table-column prop="pct_chg(%)" label="涨幅(%)" min-width="90" sortable />
        <el-table-column prop="vol(手)" label="成交量(手)" min-width="110" sortable />
        <el-table-column prop="amount(万元)" label="成交额(万元)" min-width="110" sortable />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
/* 移动端 ≤768px：散点图高度自适应、表单换行 */
@media (max-width: 768px) {
  :deep(.el-form) { display: block; }
  :deep(.el-form-item) { display: flex; margin-bottom: 10px; flex-wrap: wrap; }
  :deep(.el-form-item__label) {
    display: block;
    width: auto !important;
    margin-bottom: 4px;
    font-size: 12px;
    color: #4e5969;
    font-weight: 600;
  }
  :deep(.el-form-item__content) { margin-left: 0 !important; }
  :deep(.el-form-item .el-input),
  :deep(.el-form-item .el-select),
  :deep(.el-form-item .el-input-number) {
    width: 100%;
  }
  .chart-container { height: 320px !important; }
}
</style>
