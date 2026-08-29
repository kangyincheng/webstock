<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authChangePwd, authMe, auditLast, auditSummary } from '../api/index.js'
import { tokenStore } from '../api/http.js'

const user = ref(null)
const lastAction = ref(null)
const summary = ref(null)

async function loadAll() {
  try {
    const meResp = await authMe()
    // /auth/me 后端返回 { auth, user, last_action, recent_history }，需取 .user
    user.value = meResp?.user || meResp
    lastAction.value = meResp?.last_action || null
  } catch (e) { ElMessage.warning(e.message) }
  if (!lastAction.value) {
    try { lastAction.value = (await auditLast())?.last || null } catch {}
  }
  try { summary.value = await auditSummary() } catch {}
}
onMounted(loadAll)

const pwdForm = reactive({ old: '', next: '', confirm: '' })
const pwdLoading = ref(false)
async function changePwd() {
  if (!pwdForm.old || !pwdForm.next) return ElMessage.warning('请填写密码')
  if (pwdForm.next !== pwdForm.confirm) return ElMessage.warning('两次新密码不一致')
  if (pwdForm.next.length < 6) return ElMessage.warning('新密码至少 6 位')
  pwdLoading.value = true
  try {
    await authChangePwd({ old_password: pwdForm.old, new_password: pwdForm.next })
    ElMessage.success('密码修改成功，请用新密码重新登录')
    tokenStore.clear()
    setTimeout(() => { location.hash = '#/login' }, 600)
  } catch (e) {
    ElMessage.error(e.message || '修改失败')
  } finally { pwdLoading.value = false }
}

const createdAgo = computed(() => {
  const t = user.value?.created_at
  if (!t) return '-'
  try {
    const d = new Date(t)
    const days = Math.floor((Date.now() - d.getTime()) / 86400000)
    if (days <= 0) return '今天'
    if (days < 365) return `${days} 天前`
    return `${Math.floor(days / 365)} 年 ${days % 365} 天前`
  } catch { return t }
})
</script>

<template>
  <div style="display:grid; grid-template-columns: 1.2fr 1fr; gap: 20px">
    <!-- 左：个人信息 + 上次操作 -->
    <div>
      <el-card shadow="never">
        <template #header>
          <div style="display:flex; align-items:center; gap:12px">
            <el-avatar :size="44" style="background:#4e83fd; font-size:20px">{{ (user?.username || 'U').charAt(0).toUpperCase() }}</el-avatar>
            <div>
              <div style="font-size:18px; font-weight:600">{{ user?.username || '加载中…' }}</div>
              <div style="font-size:12px; color:#86909c">UID: {{ user?.id ?? '-' }} · 注册于 {{ createdAgo }}</div>
            </div>
          </div>
        </template>
        <el-descriptions :column="1" border size="default">
          <el-descriptions-item label="邮箱">{{ user?.email || '—' }}</el-descriptions-item>
          <el-descriptions-item label="登录次数">{{ user?.login_count ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="上次登录">{{ user?.last_login_at || '首次登录' }}</el-descriptions-item>
          <el-descriptions-item label="上次登录 IP / UA">{{ user?.last_login_ip || '—' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" style="margin-top:16px">
        <template #header><div style="font-weight:600">⏱️ 上次操作（再次登录显示用）</div></template>
        <div v-if="lastAction" style="display:flex; flex-direction:column; gap:8px">
          <div style="font-size:14px; font-weight:500">{{ lastAction.action }}</div>
          <el-tag size="small" :type="lastAction.ok ? 'success' : 'danger'" style="width:fit-content">
            {{ lastAction.ok ? '操作成功' : '操作失败' }}
          </el-tag>
          <div style="font-size:12px; color:#4e5969">
            时间：{{ lastAction.created_at }}<br>
            分类：{{ lastAction.category }}
            <span v-if="lastAction.target_key"> · 目标：{{ lastAction.target_key }}</span>
          </div>
        </div>
        <div v-else style="color:#86909c; font-size:13px">暂无操作记录，去自选股 / 预测页操作一次试试～</div>
      </el-card>
    </div>

    <!-- 右：概览 + 改密码 -->
    <div>
      <el-card shadow="never">
        <template #header><div style="font-weight:600">📊 操作概览</div></template>
        <div style="display:grid; grid-template-columns: repeat(2,1fr); gap:12px">
          <el-statistic title="总操作" :value="summary?.totals?.total_cnt || 0" />
          <el-statistic title="成功" :value="summary?.totals?.ok_cnt || 0" />
          <el-statistic title="失败" :value="summary?.totals?.err_cnt || 0" />
          <el-statistic title="活跃天数" :value="summary?.totals?.active_days || 0" />
        </div>
        <el-table v-if="summary?.last_7_days?.length" :data="summary.last_7_days" size="small" style="margin-top:16px">
          <el-table-column prop="d" label="日期" />
          <el-table-column prop="n" label="操作数" />
          <el-table-column prop="ok_n" label="成功数" />
        </el-table>
      </el-card>

      <el-card shadow="never" style="margin-top:16px">
        <template #header><div style="font-weight:600">🔐 修改密码</div></template>
        <el-form label-position="top" @submit.prevent="changePwd">
          <el-form-item label="当前密码"><el-input v-model="pwdForm.old" type="password" show-password /></el-form-item>
          <el-form-item label="新密码（至少 6 位）"><el-input v-model="pwdForm.next" type="password" show-password /></el-form-item>
          <el-form-item label="确认新密码"><el-input v-model="pwdForm.confirm" type="password" show-password /></el-form-item>
          <el-button type="primary" native-type="submit" :loading="pwdLoading">确认修改</el-button>
        </el-form>
      </el-card>
    </div>
  </div>
</template>
