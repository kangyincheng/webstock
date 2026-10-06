<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { limitStats } from '../api/index.js'

const loading = ref(false)
const rows = ref([])
const updatedAt = ref('')
const scannedDays = ref(90)
const total = ref(0)
const filterKeyword = ref('')
const weeklyHint = ref('')

// 表单参数
const nDays = ref(90)
const sortBy = ref('涨停次数')

async function loadData(refresh = false) {
  loading.value = true
  weeklyHint.value = ''
  try {
    const params = { n_days: nDays.value }
    if (refresh) params.refresh = 1
    const d = await limitStats(params)
    rows.value = d.records || []
    total.value = d.total || rows.value.length
    updatedAt.value = d.updated_at || ''
    scannedDays.value = d.scanned_days || nDays.value
    if (d.weekly_update_hint) weeklyHint.value = d.weekly_update_hint
  } catch (e) {
    // 后端 503：数据文件未就绪；429：手动刷新冷却中
    const msg = e?.response?.data?.detail || e.message || '未知错误'
    ElMessage.error('加载失败：' + msg)
  } finally {
    loading.value = false
  }
}

function onRefresh() {
  ElMessageBox.confirm(
    `⚠️ 此操作将触发后端扫描最近 ${nDays.value} 个交易日的涨停+跌停池（约 180+ 次东方财富 API 调用，耗时 2~10 分钟）。\n\n建议每周一只走一次定时刷新即可，频繁扫描会被封 IP。\n\n确定现在就要手动扫描吗？`,
    '手动刷新（谨慎）',
    {
      type: 'error',
      confirmButtonText: '我确定要扫',
      cancelButtonText: '算了，等定时任务',
      confirmButtonClass: 'el-button--danger'
    }
  ).then(() => loadData(true)).catch(() => {})
}

// 筛选 + 默认排序
const filtered = computed(() => {
  let arr = rows.value
  const kw = filterKeyword.value.trim()
  if (kw) {
    arr = arr.filter(r =>
      (r['股票名称'] || '').includes(kw) ||
      (r['股票代码'] || '').includes(kw)
    )
  }
  // 默认按涨停次数降序，其次跌停次数降序
  const sorted = [...arr].sort((a, b) => {
    const ak = a['涨停次数'] || 0
    const bk = b['涨停次数'] || 0
    if (ak !== bk) return bk - ak
    return (b['跌停次数'] || 0) - (a['跌停次数'] || 0)
  })
  return sorted
})

// 颜色：涨幅/跌幅
function limitTagClass(count) {
  if (count >= 10) return 'limit-red-hot'
  if (count >= 5) return 'limit-red'
  if (count > 0) return 'limit-red-light'
  return ''
}

function limitDownTagClass(count) {
  if (count >= 5) return 'limit-green-hot'
  if (count >= 2) return 'limit-green'
  if (count > 0) return 'limit-green-light'
  return ''
}

function fmtMoney(v) {
  if (v == null) return '-'
  const n = Number(v)
  if (!isFinite(n) || n === 0) return '-'
  if (n >= 1e12) return (n / 1e12).toFixed(2) + '万亿'
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

function fmtNum(v) {
  if (v == null) return '-'
  const n = Number(v)
  if (!isFinite(n)) return '-'
  return n.toLocaleString()
}

function fmtPct(v) {
  if (v == null) return '-'
  return Number(v).toFixed(2) + '%'
}

function fmtPrice(v) {
  if (v == null) return '-'
  return Number(v).toFixed(2)
}

onMounted(() => loadData())
</script>

<template>
  <div class="page">
    <h2 class="page-title">📊 历史涨跌停统计</h2>
    <p class="page-desc">
      数据源：akshare（东方财富） · 默认扫描最近 {{ scannedDays }} 个交易日
      <template v-if="updatedAt"> · 数据快照：{{ updatedAt }}</template>
      · 涨跌停幅度按板块判定（主板 10% / 科创·创业 20% / 北交所 30% / ST 5%）
    </p>
    <el-alert
      v-if="weeklyHint"
      :title="weeklyHint"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <div class="page-toolbar">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="扫描天数">
          <el-select v-model="nDays" style="width: 120px" disabled>
            <el-option label="30 天（近 1.5 月）" :value="30" />
            <el-option label="60 天（近 3 月）" :value="60" />
            <el-option label="90 天（近 4.5 月，推荐）" :value="90" />
            <el-option label="120 天（近 6 月）" :value="120" />
            <el-option label="250 天（近 1 年）" :value="250" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input v-model="filterKeyword" placeholder="名称/代码" clearable style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadData(false)">查询快照</el-button>
          <el-tooltip content="⚠️ 180+ 次东方财富 API 调用，12h 内限一次，避免封 IP" placement="top">
            <el-button :loading="loading" @click="onRefresh">🔄 手动刷新（谨慎）</el-button>
          </el-tooltip>
        </el-form-item>
      </el-form>
      <div class="page-toolbar-right">
        共 <b>{{ total }}</b> 只股票 · 当前列表 <b>{{ filtered.length }}</b> 条
      </div>
    </div>

    <el-card class="card">
      <el-table :data="filtered" v-loading="loading" stripe height="calc(100vh - 320px)"
                :default-sort="{ prop: '涨停次数', order: 'descending' }">
        <el-table-column label="#" type="index" width="55" :index="(i) => i + 1" />
        <el-table-column prop="股票名称" label="股票名称" width="110" fixed />
        <el-table-column prop="股票代码" label="股票代码" width="110" />
        <el-table-column prop="板块" label="板块" width="80" />
        <el-table-column prop="涨跌停幅度(%)" label="涨跌停%/板" width="90" align="center">
          <template #default="{ row }">
            <span class="limit-pct-badge">{{ row['涨跌停幅度(%)'] }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="涨停次数" prop="涨停次数" width="100" align="center" sortable>
          <template #default="{ row }">
            <span class="limit-count limit-red-badge" :class="limitTagClass(row['涨停次数'])">
              {{ row['涨停次数'] || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="跌停次数" prop="跌停次数" width="100" align="center" sortable>
          <template #default="{ row }">
            <span class="limit-count limit-green-badge" :class="limitDownTagClass(row['跌停次数'])">
              {{ row['跌停次数'] || 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="收盘价" label="收盘价" width="100" align="right" sortable>
          <template #default="{ row }">{{ fmtPrice(row['收盘价']) }}</template>
        </el-table-column>
        <el-table-column prop="PE" label="PE(动态)" width="100" align="right" sortable>
          <template #default="{ row }">{{ fmtNum(row['PE']) }}</template>
        </el-table-column>
        <el-table-column prop="PB" label="PB" width="90" align="right" sortable>
          <template #default="{ row }">{{ fmtNum(row['PB']) }}</template>
        </el-table-column>
        <el-table-column prop="总股本" label="总股本" width="120" align="right">
          <template #default="{ row }">{{ fmtMoney(row['总股本']) }}</template>
        </el-table-column>
        <el-table-column prop="总市值" label="总市值" width="130" align="right">
          <template #default="{ row }">{{ fmtMoney(row['总市值']) }}</template>
        </el-table-column>
        <el-table-column prop="流通市值" label="流通市值" width="130" align="right">
          <template #default="{ row }">{{ fmtMoney(row['流通市值']) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page { padding: 0; }
.page-title { margin: 0 0 6px; font-size: 18px; }
.page-desc { color: #86909c; font-size: 13px; margin: 0 0 16px; }
.page-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px; margin-bottom: 12px;
}
.page-toolbar-right { color: #86909c; font-size: 13px; }
.card { margin-bottom: 16px; }

.limit-red-badge { color: #f56c6c; font-weight: 700; }
.limit-green-badge { color: #67c23a; font-weight: 700; }
.limit-red-light { background: #fef0f0; }
.limit-red { background: #fde2e2; }
.limit-red-hot { background: #f56c6c; color: #fff; border-radius: 12px; padding: 1px 10px; }
.limit-green-light { background: #f0f9eb; }
.limit-green { background: #e1f3d8; }
.limit-green-hot { background: #67c23a; color: #fff; border-radius: 12px; padding: 1px 10px; }

.limit-count {
  display: inline-block;
  min-width: 48px;
  padding: 2px 8px;
  border-radius: 10px;
}

.limit-pct-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: #ecf5ff;
  color: #409eff;
  font-size: 12px;
}
</style>
