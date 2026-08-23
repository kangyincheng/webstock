<script setup>
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { hotStocks } from '../api/index.js'

const params = reactive({ trade_date: '', sort_by: 'pct_chg', top_n: 50, filter_keyword: '', use_cache: true })
const rows = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await hotStocks({ ...params })
    rows.value = r.rows || []
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div>
    <h2 class="page-title">热门股票 TOP N</h2>
    <p class="page-desc">按涨幅 / 成交额 / 成交量排序。</p>
    <div class="card">
      <el-form :inline="true" :model="params">
        <el-form-item label="交易日"><el-input v-model="params.trade_date" placeholder="YYYYMMDD 或空" style="width:180px" /></el-form-item>
        <el-form-item label="排序方式">
          <el-select v-model="params.sort_by" style="width:140px">
            <el-option label="按涨幅" value="pct_chg" />
            <el-option label="按成交额" value="amount" />
            <el-option label="按成交量" value="vol" />
          </el-select>
        </el-form-item>
        <el-form-item label="TOP N"><el-input-number v-model="params.top_n" :min="10" :max="500" :step="10" /></el-form-item>
        <el-form-item label="筛选"><el-input v-model="params.filter_keyword" placeholder="代码 / 名称" clearable /></el-form-item>
        <el-form-item label="缓存"><el-switch v-model="params.use_cache" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="loading" @click="load">加载</el-button></el-form-item>
      </el-form>
      <el-table :data="rows" stripe border size="small" max-height="70vh" :loading="loading"
        :default-sort="{ prop: params.sort_by, order: 'descending' }">
        <el-table-column v-for="(k, i) in Object.keys(rows[0] || {})" :key="i" :prop="k" :label="k" min-width="100" sortable show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>
