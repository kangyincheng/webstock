<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { stScan, stReinstate } from '../api/index.js'

const params = reactive({ months_back: 10, before_days: 30, after_days: 30 })
const reinstateParams = reactive({ months_back: 6 })
const rows = ref([])
const r2 = ref([])
const loading = ref(false)
const loading2 = ref(false)
const filter = ref('')
const sortState = reactive({ key: '', order: 'desc' })

function cellClass(r, c) {
  if (c.property === '摘帽后涨幅' || c.property === '摘帽前涨幅') {
    const v = Number(r[c.property])
    if (!v && v !== 0) return ''
    return v >= 0 ? 'cell-up' : 'cell-down'
  }
  return ''
}
function sortChange({ prop, order }) {
  if (!order) { sortState.key = ''; return }
  sortState.key = prop
  sortState.order = order
  rows.value.sort((a, b) => {
    let x = a[prop], y = b[prop]
    const nx = Number(x), ny = Number(y)
    if (!isNaN(nx) && !isNaN(ny)) { x = nx; y = ny }
    if (x < y) return order === 'ascending' ? -1 : 1
    if (x > y) return order === 'ascending' ?  1 : -1
    return 0
  })
}

async function runScan() {
  loading.value = true
  try {
    const r = await stScan(params)
    rows.value = r.records || []
    ElMessage.success(`完成：${rows.value.length} 条`)
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}
async function runReinstate() {
  loading2.value = true
  try {
    const r = await stReinstate(reinstateParams)
    r2.value = r.records || []
  } catch (e) { ElMessage.error(e.message) }
  finally { loading2.value = false }
}

const filtered = ref([])
import { computed, watch } from 'vue'
watch([rows, filter], () => {
  const kw = filter.value.trim()
  filtered.value = !kw ? rows.value : rows.value.filter(r =>
    JSON.stringify(r).toLowerCase().includes(kw.toLowerCase()))
}, { immediate: true, deep: true })
</script>

<template>
  <div>
    <h2 class="page-title">ST 摘帽 / ST 恢复上市</h2>
    <p class="page-desc">扫描 baostock 全市场 A 股 isST 转折点；摘帽前/后 N 天涨跌幅。恢复上市单独扫描。</p>

    <div class="card">
      <el-form :inline="true" :model="params">
        <el-form-item label="最近月数"><el-input-number v-model="params.months_back" :min="1" :max="60" /></el-form-item>
        <el-form-item label="摘帽前天数"><el-input-number v-model="params.before_days" :min="1" :max="120" /></el-form-item>
        <el-form-item label="摘帽后天数"><el-input-number v-model="params.after_days" :min="1" :max="240" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="loading" @click="runScan">扫描摘帽</el-button></el-form-item>
        <el-form-item label="筛选">
          <el-input v-model="filter" placeholder="代码 / 名称 / 日期" clearable style="width:240px" />
        </el-form-item>
      </el-form>
      <el-table :data="filtered" stripe border @sort-change="sortChange"
        :row-class-name="({row}) => Number(row['摘帽后涨幅']) >= 0 ? 'row-up' : 'row-down'">
        <el-table-column prop="股票名称" label="股票名称" min-width="110" sortable />
        <el-table-column prop="代码" label="代码" min-width="130" sortable />
        <el-table-column prop="开始ST日期" label="开始ST" min-width="120" sortable />
        <el-table-column prop="结束ST日期" label="摘帽日" min-width="120" sortable />
        <el-table-column prop="摘帽前涨幅" label="摘帽前(%)" min-width="110" sortable
          :cell-class-name="cellClass" />
        <el-table-column prop="摘帽后涨幅" label="摘帽后(%)" min-width="110" sortable
          :cell-class-name="cellClass" />
        <el-table-column prop="市盈率" label="PE" min-width="90" sortable />
        <el-table-column prop="市净率" label="PB" min-width="90" sortable />
        <el-table-column prop="收盘价" label="收盘价" min-width="100" sortable />
      </el-table>
    </div>

    <div class="card">
      <el-form :inline="true" :model="reinstateParams">
        <el-form-item label="最近月数"><el-input-number v-model="reinstateParams.months_back" :min="1" :max="36" /></el-form-item>
        <el-form-item><el-button :loading="loading2" @click="runReinstate">扫描恢复上市</el-button></el-form-item>
      </el-form>
      <el-table :data="r2" stripe border>
        <el-table-column v-for="(k, i) in Object.keys(r2[0] || {})" :key="i" :prop="k" :label="k" min-width="110" show-overflow-tooltip />
        <template #empty><el-empty description="暂无数据" /></template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
:deep(.cell-up) { color: #F5222D !important; font-weight: 600; }
:deep(.cell-down) { color: #52C41A !important; font-weight: 600; }
:deep(.row-up td) { background: #fff6f6 !important; }
:deep(.row-down td) { background: #f2fff4 !important; }
</style>
