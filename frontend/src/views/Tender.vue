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
      <el-button size="small" :loading="loading" @click="load" style="margin-left:12px">刷新</el-button>
      <el-table :data="rows" stripe border size="small" max-height="65vh" :loading="loading">
        <el-table-column v-for="(k, i) in Object.keys(rows[0] || {})" :key="i" :prop="k" :label="k" min-width="110" show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>
