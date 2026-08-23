<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authLogin } from '../api/index.js'
import { tokenStore } from '../api/http.js'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })

async function submit() {
  if (!form.username || !form.password) return ElMessage.warning('请输入管理员账号和密码')
  loading.value = true
  try {
    const data = await authLogin(form)
    const tokens = data?.tokens || data
    const access = tokens.access_token
    const refresh = tokens.refresh_token || data?.tokens?.refresh_token
    const user = data?.user
    if (!access) throw new Error('登录响应缺少 token')
    if (!user?.is_admin) {
      ElMessage.error('该账号不是管理员，无法进入后台')
      return
    }
    tokenStore.setTokens({ access_token: access, refresh_token: refresh, user })
    ElMessage.success(`欢迎管理员 ${user.username}`)
    const redirect = route.query.redirect || '/admin'
    router.replace(redirect)
  } catch (e) {
    ElMessage.error(e.message || '管理员登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height:100vh; background: linear-gradient(135deg,#1a1a2e 0%, #16213e 50%, #0f3460 100%); display:flex; align-items:center; justify-content:center; padding:24px">
    <div style="width:100%; max-width:380px; background:rgba(255,255,255,.95); border-radius:16px; box-shadow:0 10px 40px rgba(0,0,0,.35); padding:32px 28px">
      <div style="text-align:center; margin-bottom:24px">
        <div style="font-size:32px">🛡️</div>
        <div style="font-size:18px; font-weight:700; color:#1d2129; margin-top:8px">管理后台</div>
        <div style="font-size:12px; color:#4e5969; margin-top:6px">webstock 管理员入口</div>
      </div>
      <el-form label-position="top" size="large" @submit.prevent="submit">
        <el-form-item label="管理员账号">
          <el-input v-model="form.username" placeholder="admin" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码"
                    autocomplete="current-password" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" native-type="submit" style="width:100%" :loading="loading">管理员登录</el-button>
        <div style="margin-top:12px; font-size:12px; color:#86909c; text-align:center">
          <a @click="$router.push('/login')" style="color:#4080ff; cursor:pointer">← 返回普通登录</a>
        </div>
      </el-form>
    </div>
  </div>
</template>
