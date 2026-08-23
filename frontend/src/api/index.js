import http, { unwrap } from './http'

export const sysHealth = () => http.get('/system/healthz').then(unwrap)
export const sysVersion = () => http.get('/system/version').then(unwrap)

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
