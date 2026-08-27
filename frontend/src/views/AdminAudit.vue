<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminAuditHistory, adminAuditDetail } from '../api/index.js'

const q = reactive({ user_id: '', category: '', only_errors: false, page: 1, page_size: 20 })
const total = ref(0)
const rows = ref([])
const loading = ref(false)
const currentPage = ref(1)

const categories = [
  { label: '全部', value: '' },
  { label: '登录/账号', value: 'auth.login' },
  { label: '自选股', value: 'favorites.add' },
  { label: '预测/训练', value: 'predict.train' },
  { label: '市场/ST', value: 'market.st_scan' },
  { label: '可转债/要约', value: 'cbond.query' },
  { label: '管理员操作', value: 'admin.user' },
]

async function load() {
  loading.value = true
  try {
    const data = await adminAuditHistory({ ...q, page: currentPage.value, page_size: q.page_size })
    rows.value = data?.rows || []
    total.value = data?.total || 0
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

function onSearch() { currentPage.value = 1; load() }
function onPageChange(p) { currentPage.value = p; load() }
onMounted(load)

const detail = ref(null)
const detailDialog = ref(false)
async function showDetail(id) {
  try {
    detail.value = await adminAuditDetail(id)
    detailDialog.value = true
  } catch (e) { ElMessage.warning(e.message) }
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap">
        <div style="font-weight:600">📋 全局审计日志</div>
        <div style="flex:1"></div>
        <el-input v-model="q.user_id" placeholder="用户ID" style="width:100px" clearable @keyup.enter="onSearch" />
        <el-select v-model="q.category" placeholder="按分类" style="width:150px" clearable>
          <el-option v-for="c in categories" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-checkbox v-model="q.only_errors" border @change="onSearch">只看失败</el-checkbox>
        <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
      </div>
    </template>

    <el-table :data="rows" v-loading="loading" stripe size="default">
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column label="用户" width="140">
        <template #default="{ row }">
          <span v-if="row.user_id">{{ row.username }} ({{ row.user_id }})</span>
          <span v-else style="color:#86909c">匿名</span>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="分类" width="150">
        <template #default="{ row }"><el-tag size="small">{{ row.category }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="action" label="操作描述" min-width="300" show-overflow-tooltip />
      <el-table-column prop="target_key" label="目标" width="160" show-overflow-tooltip />
      <el-table-column label="结果" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? '成功' : '失败' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="IP" width="130" />
      <el-table-column label="详情" width="80">
        <template #default="{ row }">
          <el-button size="small" link @click="showDetail(row.id)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top:12px; display:flex; justify-content:flex-end">
      <el-pagination v-model:current-page="currentPage" :page-size="q.page_size" :total="total"
        layout="total, prev, pager, next, jumper" @current-change="onPageChange" />
    </div>
  </el-card>

  <el-dialog v-model="detailDialog" title="操作详情" width="min(720px, 92vw)">
    <el-descriptions v-if="detail?.data" :column="1" border size="small">
      <el-descriptions-item label="时间">{{ detail.data.created_at }}</el-descriptions-item>
      <el-descriptions-item label="用户">{{ detail.data.username || '匿名' }} (ID: {{ detail.data.user_id || '-' }})</el-descriptions-item>
      <el-descriptions-item label="分类 / 操作">{{ detail.data.category }} · {{ detail.data.action }}</el-descriptions-item>
      <el-descriptions-item label="目标 key">{{ detail.data.target_key || '—' }}</el-descriptions-item>
      <el-descriptions-item label="结果">{{ detail.data.ok ? '成功' : '失败' }}</el-descriptions-item>
      <el-descriptions-item label="IP / UA">{{ detail.data.ip || '—' }}<br>{{ detail.data.ua || '—' }}</el-descriptions-item>
      <el-descriptions-item label="详情 payload / 响应">
        <pre style="max-height:320px; overflow:auto; margin:0; font-size:12px">{{ detail.data.detail ? JSON.stringify(detail.data.detail, null, 2) : '—' }}</pre>
      </el-descriptions-item>
    </el-descriptions>
  </el-dialog>
</template>
