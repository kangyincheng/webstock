<script setup>
import { reactive, ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { stScan, stReinstate } from '../api/index.js'

// ============= 参数 / 原始数据 / 加载态 =============
const params = reactive({ months_back: 10, before_days: 30, after_days: 30 })
const reinstateParams = reactive({ months_back: 24 })

const rows1Raw = ref([]) // 表1 原始数据
const rows2Raw = ref([]) // 表2 原始数据
const loading1 = ref(false)
const loading2 = ref(false)
const filter1 = ref('')

// ============= 表1 排序状态（表2同理）=============
const sort1 = reactive({ prop: '', order: '' })
const sort2 = reactive({ prop: '', order: '' })

// ============= 分页状态 =============
const PAGE_SIZES = [20, 50, 100]
const pager1 = reactive({ page: 1, size: 50 })
const pager2 = reactive({ page: 1, size: 50 })

// ============= 工具：通用排序（兼容数字/日期/文本）=============
function cmpFn(a, b, prop) {
  let x = a?.[prop]
  let y = b?.[prop]
  // null/undefined 统一压到末尾
  const xNil = x === null || x === undefined || x === ''
  const yNil = y === null || y === undefined || y === ''
  if (xNil && yNil) return 0
  if (xNil) return 1
  if (yNil) return -1
  const nx = Number(x)
  const ny = Number(y)
  if (!isNaN(nx) && !isNaN(ny)) {
    return nx - ny
  }
  const xs = String(x)
  const ys = String(y)
  // YYYY-MM-DD 类日期按字典序比即可
  return xs.localeCompare(ys, 'zh-CN', { numeric: true })
}

// 表1：先排序 + 再筛选（筛选会作用于排序后的列表）
const rows1Sorted = computed(() => {
  const arr = [...rows1Raw.value]
  if (sort1.prop && sort1.order) {
    const sgn = sort1.order === 'ascending' ? 1 : -1
    arr.sort((a, b) => cmpFn(a, b, sort1.prop) * sgn)
  }
  return arr
})
const rows1Filtered = computed(() => {
  const kw = filter1.value.trim().toLowerCase()
  if (!kw) return rows1Sorted.value
  return rows1Sorted.value.filter((r) =>
    JSON.stringify(r).toLowerCase().includes(kw),
  )
})
const pager1Total = computed(() => rows1Filtered.value.length)
const rows1Page = computed(() => {
  const a = (pager1.page - 1) * pager1.size
  return rows1Filtered.value.slice(a, a + pager1.size)
})
// 数据变了重置到第 1 页
watch(rows1Filtered, () => { pager1.page = 1 })

// 表2：排序 + 分页（用户要求的：第二表单命名为【ST股摘帽时间】，即 ST 起始/转正时间汇总）
const rows2Sorted = computed(() => {
  const arr = [...rows2Raw.value]
  if (sort2.prop && sort2.order) {
    const sgn = sort2.order === 'ascending' ? 1 : -1
    arr.sort((a, b) => cmpFn(a, b, sort2.prop) * sgn)
  }
  return arr
})
const pager2Total = computed(() => rows2Sorted.value.length)
const rows2Page = computed(() => {
  const a = (pager2.page - 1) * pager2.size
  return rows2Sorted.value.slice(a, a + pager2.size)
})
watch(rows2Sorted, () => { pager2.page = 1 })

// ============= 列配置 =============
// 表1：ST股摘帽前后表现（对应 stScan）
const COLS1 = [
  { prop: '股票名称', label: '股票名称', min: 110 },
  { prop: '代码', label: '代码', min: 120 },
  { prop: '开始ST日期', label: '开始ST', min: 120 },
  { prop: '结束ST日期', label: '摘帽日', min: 120 },
  { prop: '摘帽前涨幅', label: '摘帽前(%)', min: 110, numeric: true, tone: true },
  { prop: '摘帽后涨幅', label: '摘帽后(%)', min: 110, numeric: true, tone: true },
  { prop: '市盈率', label: 'PE', min: 90, numeric: true },
  { prop: '市净率', label: 'PB', min: 90, numeric: true },
  { prop: '收盘价', label: '收盘价', min: 100, numeric: true },
]

// 表2：ST股摘帽时间（对应 stReinstate — 当前 ST 股的起始日 + 预计可申请摘帽日）
const COLS2 = [
  { prop: '股票名称', label: '股票名称', min: 110 },
  { prop: '代码', label: '代码', min: 120 },
  { prop: 'ST开始日期', label: 'ST 起始日', min: 120 },
  { prop: '可申请摘帽日', label: '可申请摘帽日', min: 150 },
  { prop: '股价', label: '最新价', min: 100, numeric: true },
  { prop: '净资产', label: '每股净资产', min: 110, numeric: true },
  { prop: '市盈率', label: 'PE', min: 90, numeric: true },
  { prop: '市净率', label: 'PB', min: 90, numeric: true },
  { prop: '量比', label: '量比', min: 90, numeric: true },
  { prop: '换手', label: '换手率(%)', min: 110, numeric: true },
]

// ============= 样式回调 =============
function cellTone({ row, column }) {
  const toneProps = ['摘帽前涨幅', '摘帽后涨幅']
  if (!toneProps.includes(column.property)) return ''
  const v = Number(row[column.property])
  if (!isFinite(v)) return ''
  return v >= 0 ? 'cell-up' : 'cell-down'
}
function rowTone1({ row }) {
  const v = Number(row['摘帽后涨幅'])
  if (!isFinite(v)) return ''
  return v >= 0 ? 'row-up' : 'row-down'
}

// ============= 动作 =============
async function runScan() {
  loading1.value = true
  try {
    const d = await stScan(params)
    // 后端 unwrap 后直接拿到 data = { records: [], logs: [] }
    rows1Raw.value = Array.isArray(d?.records) ? d.records : Array.isArray(d) ? d : []
    const msg = d?.message || `完成：${rows1Raw.value.length} 条`
    if (d?.cache_hit) ElMessage.success(`${msg}（缓存）`)
    else ElMessage.success(msg)
  } catch (e) { ElMessage.error(e?.message || '扫描失败') }
  finally { loading1.value = false }
}
async function runReinstate() {
  loading2.value = true
  try {
    const d = await stReinstate(reinstateParams)
    rows2Raw.value = Array.isArray(d?.records) ? d.records : Array.isArray(d) ? d : []
    const msg = d?.message || `完成：${rows2Raw.value.length} 条`
    if (d?.cache_hit) ElMessage.success(`${msg}（缓存）`)
    else ElMessage.success(msg)
  } catch (e) { ElMessage.error(e?.message || '扫描失败') }
  finally { loading2.value = false }
}

// 排序变化回调（兼容 Element Plus 的 sort-change）
function onSortChange1({ prop, order }) {
  sort1.prop = prop || ''
  sort1.order = order || ''
}
function onSortChange2({ prop, order }) {
  sort2.prop = prop || ''
  sort2.order = order || ''
}
</script>

<template>
  <div>
    <h2 class="page-title">ST 摘帽 / ST 恢复上市</h2>
    <p class="page-desc">
      表 1 通过名称比对识别已摘帽 ST 股，计算摘帽前/后 N 天涨跌幅；
      表 2 列出当前 ST 股的起始日及预计可申请摘帽日（起始日 + 1 个日历年，遇节假日顺延至下一交易日）。
    </p>

    <!-- ========== 表 1：ST股摘帽前后表现 ========== -->
    <div class="card">
      <div class="card-title-row">
        <h3 class="card-title">ST股摘帽前后表现</h3>
        <span class="card-sub">
          共 {{ pager1Total }} 条
          <span v-if="loading1">· 扫描中…</span>
        </span>
      </div>

      <el-form :inline="true" :model="params">
        <el-form-item label="最近月数"><el-input-number v-model="params.months_back" :min="1" :max="120" /></el-form-item>
        <el-form-item label="摘帽前天数"><el-input-number v-model="params.before_days" :min="1" :max="240" /></el-form-item>
        <el-form-item label="摘帽后天数"><el-input-number v-model="params.after_days" :min="1" :max="480" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="loading1" @click="runScan">扫描摘帽</el-button></el-form-item>
        <el-form-item label="筛选">
          <el-input v-model="filter1" placeholder="代码 / 名称 / 日期" clearable style="width:240px" />
        </el-form-item>
      </el-form>

      <el-table :data="rows1Page" stripe border height="520"
        :row-class-name="rowTone1"
        :default-sort="{ prop: '结束ST日期', order: 'descending' }"
        @sort-change="onSortChange1">
        <el-table-column
          v-for="c in COLS1"
          :key="c.prop"
          :prop="c.prop"
          :label="c.label"
          :min-width="c.min"
          sortable="custom"
          show-overflow-tooltip
          align="center"
          :cell-class-name="cellTone" />
        <template #empty><el-empty description="点击「扫描摘帽」加载数据" /></template>
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

    <!-- ========== 表 2：ST股摘帽时间 ========== -->
    <div class="card">
      <div class="card-title-row">
        <h3 class="card-title">ST股摘帽时间</h3>
        <span class="card-sub">
          共 {{ pager2Total }} 条
          <span v-if="loading2">· 扫描中…</span>
        </span>
      </div>

      <el-form :inline="true" :model="reinstateParams">
        <el-form-item label="最近月数"><el-input-number v-model="reinstateParams.months_back" :min="1" :max="120" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="loading2" @click="runReinstate">扫描可摘帽日</el-button></el-form-item>
      </el-form>

      <el-table :data="rows2Page" stripe border height="520"
        :default-sort="{ prop: '可申请摘帽日', order: 'descending' }"
        @sort-change="onSortChange2">
        <el-table-column
          v-for="c in COLS2"
          :key="c.prop"
          :prop="c.prop"
          :label="c.label"
          :min-width="c.min"
          sortable="custom"
          show-overflow-tooltip
          align="center" />
        <template #empty><el-empty description="点击「扫描可摘帽日」加载数据" /></template>
      </el-table>

      <div class="pager-row">
        <el-pagination
          v-model:current-page="pager2.page"
          v-model:page-size="pager2.size"
          :page-sizes="PAGE_SIZES"
          layout="total, sizes, prev, pager, next, jumper"
          :total="pager2Total"
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

.card-title-row {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0 4px 12px 4px; border-bottom: 1px solid var(--el-border-color-lighter);
  margin-bottom: 16px;
}
.card-title {
  margin: 0; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary);
  letter-spacing: 0.5px;
}
.card-sub { color: var(--el-text-color-secondary); font-size: 12px; }
.pager-row { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
