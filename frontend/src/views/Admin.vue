<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminStats } from '../api/index.js'

const router = useRouter()
const stats = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    stats.value = await adminStats()
  } catch (e) {
    ElMessage.error(e.message)
  } finally { loading.value = false }
}
onMounted(load)

const navCards = [
  { title: '用户管理', desc: '查看/启用/停用/删除用户、重置密码、设置管理员', icon: '👥', path: '/admin/users' },
  { title: '全局审计', desc: '查看所有用户操作日志、失败记录、详情', icon: '📋', path: '/admin/audit' },
]
</script>

<template>
  <div v-loading="loading">
    <!-- 统计卡片 -->
    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom:20px">
      <el-card shadow="hover" body-style="padding:20px">
        <div style="font-size:13px; color:#86909c">总用户数</div>
        <div style="font-size:28px; font-weight:700; color:#1d2129; margin-top:4px">{{ stats?.users?.total ?? '-' }}</div>
        <div style="font-size:12px; color:#4e5969; margin-top:4px">管理员 {{ stats?.users?.admins ?? 0 }} · 活跃 {{ stats?.users?.active ?? 0 }}</div>
      </el-card>
      <el-card shadow="hover" body-style="padding:20px">
        <div style="font-size:13px; color:#86909c">操作总数</div>
        <div style="font-size:28px; font-weight:700; color:#1d2129; margin-top:4px">{{ stats?.operations?.total ?? '-' }}</div>
        <div style="font-size:12px; color:#f53f3f; margin-top:4px">失败 {{ stats?.operations?.failed ?? 0 }}</div>
      </el-card>
      <el-card shadow="hover" body-style="padding:20px">
        <div style="font-size:13px; color:#86909c">今日登录</div>
        <div style="font-size:28px; font-weight:700; color:#1d2129; margin-top:4px">{{ stats?.operations?.today_login ?? '-' }}</div>
      </el-card>
      <el-card shadow="hover" body-style="padding:20px">
        <div style="font-size:13px; color:#86909c">近 7 天操作</div>
        <el-table v-if="stats?.last_7_days?.length" :data="stats.last_7_days" size="small" style="margin-top:4px" max-height="80">
          <el-table-column prop="d" label="日期" width="100" />
          <el-table-column prop="n" label="总数" width="50" />
          <el-table-column prop="ok_n" label="成功" width="50" />
        </el-table>
        <div v-else style="font-size:12px; color:#86909c; margin-top:8px">暂无数据</div>
      </el-card>
    </div>

    <!-- 快捷入口 -->
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px">
      <el-card v-for="c in navCards" :key="c.path" shadow="hover" body-style="padding:24px; cursor:pointer"
               @click="router.push(c.path)">
        <div style="display:flex; align-items:center; gap:16px">
          <div style="font-size:36px">{{ c.icon }}</div>
          <div>
            <div style="font-size:18px; font-weight:600">{{ c.title }}</div>
            <div style="font-size:13px; color:#86909c; margin-top:4px">{{ c.desc }}</div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 操作分类分布 -->
    <el-card v-if="stats?.category_top?.length" shadow="never" style="margin-top:20px">
      <template #header><div style="font-weight:600">操作分类 Top 10</div></template>
      <el-table :data="stats.category_top" size="default">
        <el-table-column prop="category" label="分类" />
        <el-table-column prop="n" label="操作次数" width="160">
          <template #default="{ row }">
            <el-progress :percentage="Math.round(row.n / (stats.operations.total || 1) * 100)" :format="() => row.n" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
