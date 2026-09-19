<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { stList, adminStAdd, adminStDelete } from '../api/index.js'

const router = useRouter()

// ---- 添加表单 ----
const addForm = reactive({ code: '' })
const adding = ref(false)

// ---- 列表 ----
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const q = reactive({ page: 1, page_size: 50 })

async function load() {
  loading.value = true
  try {
    const d = await stList()
    rows.value = d?.records || []
    total.value = d?.total || 0
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function onAdd() {
  const code = (addForm.code || '').trim()
  if (!code) { ElMessage.warning('请输入股票代码'); return }
  adding.value = true
  try {
    const rec = await adminStAdd(code)
    ElMessage.success(`已添加 ${rec['股票名称']}(${rec['代码']}) 摘帽日=${rec['结束ST日期']}`)
    addForm.code = ''
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { adding.value = false }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定从展示页删除 ${row['股票名称']}(${row['代码']})？`,
      '删除确认', { type: 'warning' })
    await adminStDelete(row['代码'])
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e === 'cancel') return
    if (e?.message) ElMessage.error(e.message)
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex; align-items:center; gap:12px">
        <div style="font-weight:600">🏷️ ST 摘帽管理</div>
        <div style="flex:1"></div>
        <el-button size="small" @click="router.push('/st')">查看展示页</el-button>
      </div>
    </template>

    <el-alert type="info" :closable="false" style="margin-bottom:16px">
      输入股票代码（如 600744 或 sh.600744），系统会自动从巨潮抓取最新一条「撤销 ST 风险警示」公告作为摘帽日，
      并用新浪历史 K 线计算摘帽前后 [5,10,15,20] 交易日涨幅，加入公开展示页。代码已存在则覆盖更新。
    </el-alert>

    <div class="add-row">
      <el-input
        v-model="addForm.code"
        placeholder="股票代码，如 600744 / sh.600744 / sz000975"
        style="width:320px"
        clearable
        @keyup.enter="onAdd" />
      <el-button type="primary" :loading="adding" @click="onAdd">添加 / 更新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border size="default" height="520" style="width:100%">
      <el-table-column prop="股票名称" label="股票名称" width="140" fixed="left" />
      <el-table-column prop="代码" label="代码" width="130" />
      <el-table-column prop="结束ST日期" label="摘帽日期" width="120" />
      <el-table-column prop="最新价" label="最新价" width="100" />
      <el-table-column prop="摘帽日收盘价" label="摘帽日收盘" width="110" />
      <el-table-column label="摘帽前涨幅(%)" align="center">
        <el-table-column prop="前5"  label="5日"  width="70" align="center" />
        <el-table-column prop="前10" label="10日" width="70" align="center" />
        <el-table-column prop="前15" label="15日" width="70" align="center" />
        <el-table-column prop="前20" label="20日" width="70" align="center" />
      </el-table-column>
      <el-table-column label="摘帽后涨幅(%)" align="center">
        <el-table-column prop="后5"  label="5日"  width="70" align="center" />
        <el-table-column prop="后10" label="10日" width="70" align="center" />
        <el-table-column prop="后15" label="15日" width="70" align="center" />
        <el-table-column prop="后20" label="20日" width="70" align="center" />
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right" align="center">
        <template #default="{ row }">
          <el-button size="small" type="danger" link @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="暂无数据，在上方输入代码添加" /></template>
    </el-table>

    <div class="pager-row">
      <span class="count-tip">共 {{ total }} 条</span>
    </div>
  </el-card>
</template>

<style scoped>
.add-row {
  display: flex; gap: 12px; align-items: center;
  padding: 0 0 16px 0;
}
.pager-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 12px;
}
.count-tip { color: var(--el-text-color-secondary); font-size: 13px; }
</style>
