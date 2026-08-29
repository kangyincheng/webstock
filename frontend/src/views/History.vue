<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { auditHistory, auditDetail } from '../api/index.js'

const q = reactive({ category: '', only_errors: false, page: 1, page_size: 20 })
const total = ref(0)
const rows = ref([])
const loading = ref(false)

const currentPage = ref(1)

const categories = [
  { label: '全部', value: '' },
  { label: '登录/账号', value: 'auth' },
  { label: '自选股', value: 'favorites' },
  { label: '预测/训练', value: 'predict' },
  { label: '市场/ST', value: 'market' },
  { label: '可转债/要约', value: 'cbond' },
]

async function load() {
  loading.value = true
  try {
    const data = await auditHistory({ ...q, page: currentPage.value, page_size: q.page_size })
    rows.value = data?.rows || []
    total.value = data?.total || 0
  } catch (e) {
    ElMessage.error(e.message)
  } finally { loading.value = false }
}

function onSearch() {
  currentPage.value = 1
  load()
}
function onPageChange(p) {
  currentPage.value = p
  load()
}

const detail = ref(null)
const detailDialog = ref(false)
async function showDetail(id) {
  try {
    detail.value = await auditDetail(id)
    detailDialog.value = true
  } catch (e) { ElMessage.warning(e.message) }
}

onMounted(load)
</script>

<template>
  <div>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex; align-items:center; gap:12px">
        <div style="font-weight:600">🧾 操作历史（按时间倒序）</div>
        <div style="flex:1"></div>
        <el-select v-model="q.category" placeholder="按分类" style="width:140px" size="default">
          <el-option v-for="c in categories" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-checkbox v-model="q.only_errors" border>只看失败</el-checkbox>
        <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
      </div>
    </template>

    <el-table :data="rows" v-loading="loading" stripe size="default">
      <el-table-column label="时间" prop="created_at" width="180" />
      <el-table-column label="分类" prop="category" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ row.category }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作描述" prop="action" min-width="280" show-overflow-tooltip />
      <el-table-column label="目标" prop="target_key" width="160" show-overflow-tooltip />
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.ok ? 'success' : 'danger'">
            {{ row.ok ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="IP" prop="ip" width="140" />
      <el-table-column label="详情" width="100">
        <template #default="{ row }">
          <el-button size="small" link @click="showDetail(row.id)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top:12px; display:flex; justify-content:flex-end">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="q.page_size"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="onPageChange"
      />
    </div>
  </el-card>

  <el-dialog v-model="detailDialog" title="操作详情" width="min(720px, 92vw)">
    <el-descriptions v-if="detail?.data" :column="1" border size="small">
      <el-descriptions-item label="时间">{{ detail.data.created_at }}</el-descriptions-item>
      <el-descriptions-item label="分类 / 操作">{{ detail.data.category }} · {{ detail.data.action }}</el-descriptions-item>
      <el-descriptions-item label="目标 key">{{ detail.data.target_key || '—' }}</el-descriptions-item>
      <el-descriptions-item label="结果">{{ detail.data.ok ? '成功' : '失败' }}</el-descriptions-item>
      <el-descriptions-item label="IP / UA">{{ detail.data.ip || '—' }}<br>{{ detail.data.ua || '—' }}</el-descriptions-item>
      <el-descriptions-item label="详情 payload / 响应">
        <pre style="max-height:320px; overflow:auto; margin:0; font-size:12px">{{ detail.data.detail ? JSON.stringify(detail.data.detail, null, 2) : '—' }}</pre>
      </el-descriptions-item>
    </el-descriptions>
  </el-dialog>
  </div>
</template>
