<script setup>
import { reactive, ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { stScan } from '../api/index.js'
import { tokenStore } from '../api/http.js'

// ============= 参数 =============
const N_OPTIONS = [5, 10, 15, 20]
const beforeSel = ref(15)
const afterSel = ref(15)

// ============= 数据 =============
const rows1Raw = ref([])
const loading1 = ref(true)

// ============= 筛选 + 排序 + 分页 =============
const filterText = ref('')   // 名称/代码 搜索
const filterUp = ref('')     // 摘帽后: 全部 | 盈利 | 亏损
const sort1 = reactive({ prop: '', order: '' })
const PAGE_SIZES = [20, 50, 100, 200]
const pager1 = reactive({ page: 1, size: 50 })

const isAdmin = computed(() => !!tokenStore.user?.is_admin)

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

const preColKey = computed(() => `前${beforeSel.value}`)
const postColKey = computed(() => `后${afterSel.value}`)
const preColLabel = computed(() => `摘帽前${beforeSel.value}日(%)`)
const postColLabel = computed(() => `摘帽后${afterSel.value}日(%)`)

// 筛选 → 排序 → 分页
const rows1Filtered = computed(() => {
  const kw = filterText.value.trim().toLowerCase()
  let arr = [...rows1Raw.value]
  if (kw) {
    arr = arr.filter(r =>
      (r['股票名称'] || '').toLowerCase().includes(kw) ||
      (r['代码'] || '').toLowerCase().includes(kw))
  }
  if (filterUp.value === 'win') {
    arr = arr.filter(r => Number(r[postColKey.value]) > 0)
  } else if (filterUp.value === 'loss') {
    arr = arr.filter(r => Number(r[postColKey.value]) < 0)
  }
  return arr
})

const rows1Sorted = computed(() => {
  const arr = [...rows1Filtered.value]
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
watch([filterText, filterUp, beforeSel, afterSel], () => { pager1.page = 1 })
watch(rows1Sorted, () => { pager1.page = 1 })

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

async function runLoad() {
  loading1.value = true
  try {
    const d = await stScan({ months_back: 24, before_days: 20, after_days: 20 })
    rows1Raw.value = Array.isArray(d?.records) ? d.records : Array.isArray(d) ? d : []
  } catch (e) { ElMessage.error(e?.message || '加载失败') }
  finally { loading1.value = false }
}

function onSortChange1({ prop, order }) {
  sort1.prop = prop || ''
  sort1.order = order || ''
}

onMounted(runLoad)
</script>

<template>
  <div>
    <h2 class="page-title">ST 股统计分析</h2>
    <p class="page-desc">
      640 只已摘帽股票完整数据：名称、代码、摘帽日、摘帽前/后 [5,10,15,20] 交易日涨幅、收盘价、PE/PB。
      支持搜索筛选、排序、分页。
      <router-link v-if="isAdmin" to="/admin/st" class="admin-link">管理员维护 →</router-link>
    </p>

    <div class="card">
      <div class="card-title-row">
        <h3 class="card-title">摘帽股票列表</h3>
        <span class="card-sub">
          共 {{ pager1Total }} 条
          <span v-if="loading1">· 加载中…</span>
        </span>
      </div>

      <!-- 工具栏：搜索 + 筛选 + N 下拉 -->
      <div class="filter-bar">
        <el-input v-model="filterText" placeholder="搜索 名称 / 代码" size="default"
                  style="width: 220px" clearable />
        <el-select v-model="filterUp" placeholder="摘帽后" size="default" style="width: 110px" clearable>
          <el-option label="盈利" value="win" />
          <el-option label="亏损" value="loss" />
        </el-select>
        <el-select v-model="beforeSel" size="default" style="width: 100px">
          <el-option v-for="n in N_OPTIONS" :key="n" :label="'前 ' + n + '日'" :value="n" />
        </el-select>
        <el-select v-model="afterSel" size="default" style="width: 100px">
          <el-option v-for="n in N_OPTIONS" :key="n" :label="'后 ' + n + '日'" :value="n" />
        </el-select>
      </div>

      <!-- 表格：固定高度 + 横向滚动 -->
      <el-table
        :data="rows1Page"
        stripe border height="560"
        style="width: 100%"
        :row-class-name="rowTone1"
        :default-sort="{ prop: '结束ST日期', order: 'descending' }"
        @sort-change="onSortChange1"
      >
        <el-table-column
          v-for="c in COLS1"
          :key="c.prop"
          :prop="c.prop" :label="c.label"
          :width="c.w" :min-width="c.w"
          :fixed="c.fixed"
          sortable="custom" show-overflow-tooltip align="center"
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

.admin-link { margin-left: 6px; color: var(--el-color-primary); font-weight: 500; text-decoration: none; }
.admin-link:hover { text-decoration: underline; }

.card-title-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0 4px 12px 4px; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 12px;
}
.card-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
.card-sub { color: var(--el-text-color-secondary); font-size: 12px; }
.pager-row { display: flex; justify-content: flex-end; margin-top: 12px; }

.filter-bar {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  padding: 0 0 12px 0;
}
</style>
