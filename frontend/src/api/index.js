import http, { unwrap } from './http'

export const sysHealth = () => http.get('/system/healthz').then(unwrap)
export const sysVersion = () => http.get('/system/version').then(unwrap)

// ---------- 认证 ----------
export const authRegister = (p) => http.post('/auth/register', p).then(unwrap)
export const authLogin = (p) => http.post('/auth/login', p).then(unwrap)
export const authLogout = () => http.post('/auth/logout').then(unwrap)
export const authMe = () => http.get('/auth/me').then(unwrap)
export const authChangePwd = (p) => http.post('/auth/change-password', p).then(unwrap)

// ---------- 审计历史 ----------
export const auditLast = () => http.get('/audit/last').then(unwrap)
export const auditHistory = (p) => http.get('/audit/history', { params: p }).then(unwrap)
export const auditSummary = () => http.get('/audit/summary').then(unwrap)
export const auditDetail = (id) => http.get(`/audit/detail/${id}`).then(unwrap)

export const stScan = (p) => http.post('/market/st/scan', p).then(unwrap)
export const stReinstate = (p) => http.post('/market/st-reinstate/scan', p).then(unwrap)
export const thermometer = () => http.get('/market/thermometer').then(unwrap)
export const sectorHeat = (p) => http.post('/market/sector-heat', p).then(unwrap)
export const hotStocks = (p) => http.post('/market/hot-stocks', p).then(unwrap)

export const predictTrain = (p) => http.post('/predict/train', p).then(unwrap)
export const predictTask = (id) => http.get(`/predict/task/${id}`).then(unwrap)
export const listModels = (framework) =>
  http.get('/predict/models', { params: { framework } }).then(unwrap)
export const deleteModel = (name) => http.delete(`/predict/models/${name}`).then(unwrap)
export const searchStock = (q) =>
  http.get('/predict/search', { params: { q } }).then(unwrap)

export const favList = () => http.get('/favorites').then(unwrap)
export const favAdd = (p) => http.post('/favorites', p).then(unwrap)
export const favUpdate = (id, p) => http.put(`/favorites/${id}`, p).then(unwrap)
export const favDelete = (id) => http.delete(`/favorites/${id}`).then(unwrap)
export const favRefresh = () => http.post('/favorites/refresh-prices').then(unwrap)
export const favCheckEvents = () => http.post('/favorites/check-events').then(unwrap)

export const cbondSubscribe = (p = {}) => http.post('/cbond/subscribe', p).then(unwrap)
export const cbondListing = (p = {}) => http.post('/cbond/listing', p).then(unwrap)
export const cbondReview = (p = {}) => http.post('/cbond/review', p).then(unwrap)
export const tender = (p) => http.post('/cbond/tender', p).then(unwrap)

// ---------- 管理员后台 ----------
export const adminStats = () => http.get('/admin/stats').then(unwrap)
export const adminUsers = (p) => http.get('/admin/users', { params: p }).then(unwrap)
export const adminSetAdmin = (uid, is_admin) => http.put(`/admin/users/${uid}/admin`, { is_admin }).then(unwrap)
export const adminSetActive = (uid, is_active) => http.put(`/admin/users/${uid}/active`, { is_active }).then(unwrap)
export const adminResetPwd = (uid, new_password) => http.post(`/admin/users/${uid}/reset-password`, { new_password }).then(unwrap)
export const adminDeleteUser = (uid) => http.delete(`/admin/users/${uid}`).then(unwrap)
export const adminAuditHistory = (p) => http.get('/admin/audit/history', { params: p }).then(unwrap)
export const adminAuditDetail = (id) => http.get(`/admin/audit/detail/${id}`).then(unwrap)
export const adminAuditFailed = (limit = 20) => http.get('/admin/audit/failed', { params: { limit } }).then(unwrap)
