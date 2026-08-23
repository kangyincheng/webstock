<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { sectorHeat } from '../api/index.js'

const tradeDate = ref('')
const rows = ref([])
const loading = ref(false)
const cache = ref(true)

async function load() {
  loading.value = true
  try {
    const r = await sectorHeat({ trade_date: tradeDate.value, use_cache: cache.value })
    rows.value = r.rows || []
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div>
    <h2 class="page-title">板块热度（行业分组）</h2>
    <p class="page-desc">按行业聚合：平均涨幅 / 中位数涨幅 / 总成交额 / 上涨 / 下跌 / 涨停家数。</p>
    <div class="card">
      <el-form :inline="true">
        <el-form-item label="交易日">
          <el-input v-model="tradeDate" placeholder="YYYYMMDD 或空=最近" style="width:180px" />
        </el-form-item>
        <el-form-item label="缓存">
          <el-switch v-model="cache" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">加载</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="rows" stripe border size="small" max-height="70vh" :loading="loading"
        :default-sort="{ prop: 'avg_chg', order: 'descending' }">
        <el-table-column v-for="(k, i) in Object.keys(rows[0] || {})" :key="i" :prop="k" :label="k" min-width="110" sortable show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>
