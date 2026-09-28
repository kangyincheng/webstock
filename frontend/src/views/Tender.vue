<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { tender } from '../api/index.js'

const market = ref('cn')
const rows = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await tender({ market: market.value })
    rows.value = r.rows || []
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

watch(market, load)
onMounted(load)

// 列宽映射：短字段按内容最小化，描述列加宽
const colWidthMap = {
  "股票代码": 95,
  "股票名称": 105,
  "当前股价": 80,
  "要约价": 80,
  "安全价": 80,
  "折价率(%)": 95,
  "要约溢价(%)": 95,
  "要约比例(%)": 95,
  "类型": 75,
  "进度": 80,
  "方式": 80,
  "要约人": 100,
  "公告日期": 110,
  "要约开始日期": 120,
  "要约结束日期": 120,
  "描述": 360,
}
function colWidth(k) {
  return colWidthMap[k] ?? 110
}
</script>

<template>
  <div>
    <h2 class="page-title">要约收购（A 股 / 港股）</h2>
    <p class="page-desc">要约价 / 溢价 / 进度 / 公告日期；数据源：集思录实时抓取（A股 astock / 港股 hk）。</p>
    <div class="card">
      <el-radio-group v-model="market" style="margin-bottom:12px">
        <el-radio-button label="cn">A股</el-radio-button>
        <el-radio-button label="hk">港股</el-radio-button>
      </el-radio-group>
      <el-table :data="rows" stripe border size="small" max-height="65vh" :loading="loading">
        <el-table-column
          v-for="(k, i) in Object.keys(rows[0] || {})"
          :key="i" :prop="k" :label="k"
          :width="colWidth(k)"
          show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>
