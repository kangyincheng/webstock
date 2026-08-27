<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminUsers, adminSetAdmin, adminSetActive, adminResetPwd, adminDeleteUser } from '../api/index.js'

const q = reactive({ keyword: '', admin_only: false, page: 1, page_size: 20 })
const total = ref(0)
const rows = ref([])
const loading = ref(false)
const currentPage = ref(1)

async function load() {
  loading.value = true
  try {
    const data = await adminUsers({ ...q, page: currentPage.value, page_size: q.page_size })
    rows.value = data?.rows || []
    total.value = data?.total || 0
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

function onSearch() { currentPage.value = 1; load() }
function onPageChange(p) { currentPage.value = p; load() }
onMounted(load)

async function toggleAdmin(row) {
  try {
    await adminSetAdmin(row.id, !row.is_admin)
    ElMessage.success('已更新管理员状态')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function toggleActive(row) {
  try {
    await adminSetActive(row.id, !row.is_active)
    ElMessage.success(row.is_active ? '已停用' : '已启用')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function resetPwd(row) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新密码（至少 6 位）', `重置 ${row.username} 的密码`, {
      inputType: 'password',
      inputPattern: /^.{6,}$/,
      inputErrorMessage: '密码至少 6 位',
    })
    await adminResetPwd(row.id, value)
    ElMessage.success('密码已重置')
  } catch (e) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function delUser(row) {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${row.username}？此操作不可恢复`, '删除确认', { type: 'warning' })
    await adminDeleteUser(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex; align-items:center; gap:12px">
        <div style="font-weight:600">👥 用户管理</div>
        <div style="flex:1"></div>
        <el-input v-model="q.keyword" placeholder="搜索用户名/邮箱/昵称" style="width:200px" clearable @keyup.enter="onSearch" />
        <el-checkbox v-model="q.admin_only" border @change="onSearch">仅管理员</el-checkbox>
        <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
      </div>
    </template>

    <el-table :data="rows" v-loading="loading" stripe size="default">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="email" label="邮箱" width="200" show-overflow-tooltip />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_admin ? 'danger' : 'info'">{{ row.is_admin ? '管理员' : '普通用户' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_active ? 'success' : 'danger'">{{ row.is_active ? '正常' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="login_count" label="登录次数" width="90" />
      <el-table-column prop="last_login_at" label="上次登录" width="160" />
      <el-table-column prop="last_login_ip" label="上次IP" width="130" />
      <el-table-column prop="created_at" label="注册时间" width="160" />
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :type="row.is_admin ? 'warning' : 'primary'" link @click="toggleAdmin(row)">
            {{ row.is_admin ? '取消管理员' : '设为管理员' }}
          </el-button>
          <el-button size="small" :type="row.is_active ? 'warning' : 'success'" link @click="toggleActive(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" link @click="resetPwd(row)">重置密码</el-button>
          <el-button size="small" type="danger" link @click="delUser(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top:12px; display:flex; justify-content:flex-end">
      <el-pagination v-model:current-page="currentPage" :page-size="q.page_size" :total="total"
        layout="total, prev, pager, next, jumper" @current-change="onPageChange" />
    </div>
  </el-card>
</template>
