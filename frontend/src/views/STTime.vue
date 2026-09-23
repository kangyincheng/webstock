<script setup>
import { reactive, ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/http.js'

const rowsRaw = ref([])
const loading = ref(true)
const logLines = ref([])

const PAGE_SIZES = [20, 50, 100]
const pager = reactive({ page: 1, size: 50 })
const sort = reactive({ prop: '', order: '' })
const filterText = ref('')

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

const rowsFiltered = computed(() => {
  const kw = filterText.value.trim().toLowerCase()
  if (!kw) return [...rowsRaw.value]
  return rowsRaw.value.filter(r =>
    (r['股票名称'] || '').toLowerCase().includes(kw) ||
    (r['代码'] || '').toLowerCase().includes(kw))
})

const rowsSorted = computed(() => {
  const arr = [...rowsFiltered.value]
  if (sort.prop && sort.order) {
    const sgn = sort.order === 'ascending' ? 1 : -1
    arr.sort((a, b) => cmpFn(a, b, sort.prop) * sgn)
  }
  return arr
})
const total = computed(() => rowsSorted.value.length)
const pageRows = computed(() => {
  const a = (pager.page - 1) * pager.size
  return rowsSorted.value.slice(a, a + pager.size)
})
watch(filterText, () => { pager.page = 1 })
watch(rowsSorted, () => { pager.page = 1 })

const today = new Date().toISOString().slice(0, 10)

async function runLoad() {
  loading.value = true
  try {
    const r = await http.get('/market/st/time')
    const body = r.data
    if (!body?.success) { ElMessage.error(body?.message || '加载失败'); return }
    const d = body.data || {}
    rowsRaw.value = d.records || []
    logLines.value = d.logs || []
  } catch (e) { ElMessage.error(e?.message || '加载失败') }
  finally { loading.value = false }
}

function onSortChange({ prop, order }) {
  sort.prop = prop || ''
  sort.order = order || ''
}

onMounted(() => runLoad())
</script>

<template>
  <div>
    <h2 class="page-title">ST 股摘帽时间</h2>

    <div class="card" v-loading="loading">
      <div class="card-title-row">
        <h3 class="card-title">当前 ST 股票 {{ total ? `（${total} 只）` : '' }}</h3>
        <el-input v-model="filterText" placeholder="搜索 名称/代码" size="small"
                  style="width: 200px" clearable />
      </div>

      <el-table :data="pageRows" stripe border height="540" style="width: 100%"
                :default-sort="{ prop: '距可申请天数', order: 'ascending' }"
                @sort-change="onSortChange">
        <el-table-column prop="股票名称" label="股票名称" width="120" fixed="left" />
        <el-table-column prop="代码" label="代码" width="110" />
        <el-table-column prop="ST开始日期" label="ST开始日" width="120" sortable="custom" />
        <el-table-column prop="可申请摘帽日" label="可申请摘帽日" width="130" sortable="custom" />
        <el-table-column prop="距可申请天数" label="距可申请(天)" width="120" sortable="custom">
          <template #default="{ row }">
            <span v-if="row['距可申请天数'] !== null"
                  :style="{ color: row['距可申请天数'] <= 30 ? '#F5222D' : '#52C41A', fontWeight: 600 }">
              {{ row['距可申请天数'] }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="最新价" label="最新价" width="90" align="center" />
        <el-table-column prop="市盈率" label="PE" width="90" align="center" />
        <el-table-column prop="市净率" label="PB" width="90" align="center" />
        <el-table-column prop="换手率" label="换手(%)" width="95" align="center" />
        <el-table-column prop="市值亿" label="市值(亿)" width="100" align="center" />
        <template #empty><el-empty description="暂无当前 ST 股票（市场已清理完毕）" /></template>
      </el-table>

      <div class="pager-row">
        <el-pagination
          v-model:current-page="pager.page"
          v-model:page-size="pager.size"
          :page-sizes="PAGE_SIZES"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          background small />
      </div>

      <div v-if="logLines.length" class="log-box">
        <div class="log-title">扫描日志</div>
        <div v-for="(l, i) in logLines" :key="i" class="log-line">{{ l }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card-title-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 0 4px 12px 4px; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 12px; flex-wrap: wrap;
}
.card-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
.card-actions { display: flex; gap: 8px; align-items: center; }
.pager-row { display: flex; justify-content: flex-end; margin-top: 12px; }

.log-box {
  margin-top: 12px; padding: 10px 12px;
  background: var(--el-fill-color-light); border-radius: 6px;
  font-size: 12px; color: var(--el-text-color-secondary);
}
.log-title { font-weight: 600; margin-bottom: 4px; }
.log-line { line-height: 1.6; }
</style>
