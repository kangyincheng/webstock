import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 600_000, // 训练/扫描接口长
})

http.interceptors.response.use(
  (r) => r,
  (e) => {
    const msg = e?.response?.data?.detail || e.message || '请求失败'
    // 在非组件上下文中不直接弹 UI，让调用方处理
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
