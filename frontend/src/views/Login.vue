<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authLogin, authRegister } from '../api/index.js'
import { tokenStore } from '../api/http.js'

const route = useRoute()
const router = useRouter()

const mode = ref('login') // login | register
const loading = ref(false)

const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({ username: '', email: '', password: '', confirm: '' })

async function submitLogin() {
  if (!loginForm.username || !loginForm.password) return ElMessage.warning('请输入账号密码')
  loading.value = true
  try {
    const data = await authLogin(loginForm)
    // 后端返回 { tokens, user, last_action }
    const tokens = data?.tokens || data
    const access = tokens.access_token
    const refresh = tokens.refresh_token || data?.tokens?.refresh_token
    const user = data?.user
    if (!access) throw new Error('登录响应缺少 token')
    tokenStore.setTokens({ access_token: access, refresh_token: refresh, user })
    ElMessage.success(`欢迎 ${user?.username || loginForm.username}`)
    if (data?.last_action?.action) {
      ElMessage({
        type: 'info',
        duration: 4000,
        showClose: true,
        message: `上次操作：${data.last_action.action}（${data.last_action.created_at}）`,
      })
    }
    const redirect = route.query.redirect || '/dashboard'
    router.replace(redirect)
  } catch (e) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  if (!regForm.username || !regForm.password) return ElMessage.warning('请填写账号密码')
  if (regForm.password !== regForm.confirm) return ElMessage.warning('两次密码不一致')
  if (regForm.password.length < 6) return ElMessage.warning('密码至少 6 位')
  loading.value = true
  try {
    await authRegister({
      username: regForm.username,
      email: regForm.email || undefined,
      password: regForm.password,
    })
    ElMessage.success('注册成功，自动登录中…')
    const data = await authLogin({ username: regForm.username, password: regForm.password })
    const tokens = data?.tokens || data
    const access = tokens.access_token
    const refresh = tokens.refresh_token || data?.tokens?.refresh_token
    const user = data?.user
    if (!access) throw new Error('登录响应缺少 token')
    tokenStore.setTokens({ access_token: access, refresh_token: refresh, user })
    const redirect = route.query.redirect || '/dashboard'
    router.replace(redirect)
  } catch (e) {
    ElMessage.error(e.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height:100vh; background: linear-gradient(135deg,#161a23 0%, #213547 50%, #2e5f7a 100%); display:flex; align-items:center; justify-content:center; padding:24px">
    <div style="width: 100%; max-width: 420px; background: rgba(255,255,255,.96); border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,.25); padding: 32px 28px">
      <div style="text-align:center; margin-bottom: 24px">
        <div style="font-size: 22px; font-weight:700; color:#1d2129">🚀 webstock</div>
        <div style="font-size: 13px; color:#4e5969; margin-top: 8px">
          登录后，你的所有操作结果会被保存，<br>下次登录可看到上次操作记录。
        </div>
      </div>

      <el-tabs v-model="mode" type="card" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" size="large" @submit.prevent="submitLogin">
            <el-form-item label="用户名 / 邮箱">
              <el-input v-model="loginForm.username" placeholder="请输入" autocomplete="username" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="loginForm.password" type="password" show-password
                        placeholder="请输入密码" autocomplete="current-password"
                        @keyup.enter="submitLogin" />
            </el-form-item>
            <el-button type="primary" native-type="submit" style="width:100%" :loading="loading">登 录</el-button>
            <div style="margin-top:12px; font-size:12px; color:#86909c">
              没账号？ <a @click="mode='register'" style="color:#4080ff; cursor:pointer">立即注册</a>
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form label-position="top" size="large" @submit.prevent="submitRegister">
            <el-form-item label="用户名（3~32 位）">
              <el-input v-model="regForm.username" placeholder="请设置用户名" autocomplete="username" />
            </el-form-item>
            <el-form-item label="邮箱（可选）">
              <el-input v-model="regForm.email" placeholder="example@jeoj.com" autocomplete="email" />
            </el-form-item>
            <el-form-item label="密码（至少 6 位）">
              <el-input v-model="regForm.password" type="password" show-password placeholder="请设置密码" autocomplete="new-password" />
            </el-form-item>
            <el-form-item label="确认密码">
              <el-input v-model="regForm.confirm" type="password" show-password placeholder="再次输入密码"
                        autocomplete="new-password" @keyup.enter="submitRegister" />
            </el-form-item>
            <el-button type="primary" native-type="submit" style="width:100%" :loading="loading">注 册 并 登 录</el-button>
            <div style="margin-top:12px; font-size:12px; color:#86909c">
              已有账号？ <a @click="mode='login'" style="color:#4080ff; cursor:pointer">返回登录</a>
            </div>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>
