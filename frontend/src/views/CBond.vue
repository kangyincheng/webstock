<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cbondSubscribe, cbondListing, cbondReview } from '../api/index.js'

const tab = ref('subscribe')
const rows = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const fn = { subscribe: cbondSubscribe, listing: cbondListing, review: cbondReview }[tab.value]
    const r = await fn({})
    rows.value = r.rows || []
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

import { watch, onMounted } from 'vue'
watch(tab, load)
onMounted(load)
</script>

<template>
  <div>
    <h2 class="page-title">可转债</h2>
    <p class="page-desc">申购（打新）· 当日上市 · 发审进度；数据源优先 tushare，无 token 返回演示数据。</p>
    <div class="card">
      <el-tabs v-model="tab">
        <el-tab-pane label="🆕 当日可申购" name="subscribe" />
        <el-tab-pane label="🎉 当日上市" name="listing" />
        <el-tab-pane label="📋 发审进度" name="review" />
      </el-tabs>
      <el-button size="small" :loading="loading" @click="load" style="margin-bottom:12px">刷新</el-button>
      <el-table :data="rows" stripe border size="small" max-height="60vh" :loading="loading">
        <el-table-column v-for="(k, i) in Object.keys(rows[0] || {})" :key="i" :prop="k" :label="k" min-width="110" show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>
