import axios from 'axios'

const LS_ACCESS = 'webstock.access_token'
const LS_REFRESH = 'webstock.refresh_token'
const LS_USER = 'webstock.current_user'

export const tokenStore = {
  get access() { return localStorage.getItem(LS_ACCESS) || '' },
  get refresh() { return localStorage.getItem(LS_REFRESH) || '' },
  get user() {
    try {
      const raw = localStorage.getItem(LS_USER)
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  },
  setTokens({ access_token, refresh_token, user }) {
    if (access_token) localStorage.setItem(LS_ACCESS, access_token)
    if (refresh_token) localStorage.setItem(LS_REFRESH, refresh_token)
    if (user) localStorage.setItem(LS_USER, JSON.stringify(user))
  },
  setUser(u) {
    if (u) localStorage.setItem(LS_USER, JSON.stringify(u))
    else localStorage.removeItem(LS_USER)
  },
  clear() {
    localStorage.removeItem(LS_ACCESS)
    localStorage.removeItem(LS_REFRESH)
    localStorage.removeItem(LS_USER)
  },
  isLoggedIn() {
    return !!localStorage.getItem(LS_ACCESS)
  },
}

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 600_000, // 训练/扫描接口长
})

// 请求拦截：注入 Bearer token
http.interceptors.request.use((config) => {
  const token = tokenStore.access
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：401 自动尝试 refresh，再失败则清 token 并提示登录
let refreshPromise = null
http.interceptors.response.use(
  (r) => r,
  async (e) => {
    const status = e?.response?.status
    const isAuth = String(e?.config?.url || '').includes('/auth/')
    if (status === 401 && !isAuth && !e.config.__retried && tokenStore.refresh) {
      if (!refreshPromise) {
        refreshPromise = (async () => {
          try {
            const res = await http.post('/auth/refresh', { refresh_token: tokenStore.refresh })
            const body = res.data
            if (body?.success && body?.data) {
              tokenStore.setTokens(body.data)
              return body.data.access_token
            } else {
              throw new Error(body?.message || 'refresh 失败')
            }
          } catch {
            tokenStore.clear()
            throw e
          } finally {
            refreshPromise = null
          }
        })()
      }
      try {
        const newTok = await refreshPromise
        const conf = { ...(e.config || {}) }
        conf.__retried = true
        conf.headers = { ...(conf.headers || {}), Authorization: `Bearer ${newTok}` }
        return http.request(conf)
      } catch {
        // 重试失败仍然抛
      }
    }
    const msg = e?.response?.data?.detail || e?.response?.data?.message || e.message || '请求失败'
    return Promise.reject(new Error(msg))
  },
)

export default http

export function unwrap(r) {
  const body = r?.data
  if (!body) throw new Error('空响应')
  if (body.success === false) throw new Error(body.message || '接口失败')
  return body.data
}
