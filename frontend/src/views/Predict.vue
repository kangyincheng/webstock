<script setup>
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { predictTrain, listModels, deleteModel } from '../api/index.js'

const form = reactive({
  framework: 'pytorch',
  stock_code: 'sh.600036',
  start_date: '2019-01-01',
  end_date: '',
  adjustflag: '2',
  frequency: 'd',
  feature_cols: 'open,high,low,close,volume,amount,turn',
  target_col: 'close',
  seq_len: 60,
  train_ratio: 0.8,
  model_type: 'LSTM',
  hidden_size: 128,
  num_layers: 2,
  dropout: 0.2,
  bidirectional: false,
  d_model: 128,
  nhead: 4,
  dim_feedforward: 256,
  epochs: 80,
  batch_size: 32,
  learning_rate: 0.001,
  optimizer_type: 'Adam',
  loss_type: 'MSE',
  early_stopping_patience: 15,
  model_name: '',
})

const running = ref(false)
const logs = ref([])
const progress = reactive({ epoch: 0, total_epochs: 0, train_loss: 0, val_loss: 0 })
const result = ref(null)

const chartRef = shallowRef(null)
const lossRef = shallowRef(null)
let ch = null, cl = null
let ws = null
let currentTaskId = null

function pushLog(msg) { logs.value.push(msg) }

function ws_connect(task_id) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/ws/train/${task_id}`
  try {
    ws = new WebSocket(url)
    ws.onmessage = (ev) => {
      const d = JSON.parse(ev.data)
      if (d.epoch) progress.epoch = d.epoch
      if (d.total_epochs) progress.total_epochs = d.total_epochs
      if (typeof d.train_loss === 'number') progress.train_loss = d.train_loss
      if (typeof d.val_loss === 'number') progress.val_loss = d.val_loss
      if (d.message) pushLog(`[${d.stage || ''}] ${d.message}`)
    }
  } catch (e) { pushLog('WebSocket 连接失败，改用轮询') }
}

function ws_close() {
  try { ws && ws.close() } catch {}
  ws = null
}

const pct = computed(() =>
  progress.total_epochs ? Math.round((progress.epoch / progress.total_epochs) * 100) : 0)

async function start() {
  running.value = true
  logs.value = []
  result.value = null
  progress.epoch = 0
  try {
    const r = await predictTrain({ ...form })
    currentTaskId = r.task_id
    ws_connect(r.task_id)
    result.value = r
    render()
    ElMessage.success(r.status === 'success' ? '训练完成' : '训练异常，请查看日志')
  } catch (e) {
    ElMessage.error(e.message)
    pushLog(String(e.message || e))
  } finally {
    running.value = false
    ws_close()
  }
}

function render() {
  const r = result.value
  if (!r) return
  if (ch) {
    const dates = r.dates || []
    const actual = r.actual || []
    const predicted = r.predicted || []
    const k = Math.min(dates.length, actual.length, predicted.length)
    const xBase = dates.slice(-k)
    const actBase = actual.slice(-k)
    const predBase = predicted.slice(-k)
    // 追加下一交易日预测点：实际值留空，预测线延伸一格
    const hasNext = r.next_day_pred != null
    const xData = hasNext ? [...xBase, r.next_day_date || '下一交易日'] : xBase
    const actData = hasNext ? [...actBase, null] : actBase
    const predData = hasNext ? [...predBase, r.next_day_pred] : predBase
    ch.setOption({
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['实际', '预测'] },
      grid: { left: 48, right: 24, top: 32, bottom: 48 },
      xAxis: { type: 'category', data: xData, axisLabel: { rotate: 40 } },
      yAxis: { type: 'value', scale: true },
      series: [
        { name: '实际', type: 'line', showSymbol: false, data: actData, itemStyle: { color: '#1677FF' } },
        {
          name: '预测', type: 'line', showSymbol: false, data: predData, itemStyle: { color: '#F5222D' },
          markPoint: hasNext ? {
            symbol: 'pin', symbolSize: 46,
            data: [{ name: '下一交易日', coord: [r.next_day_date || '下一交易日', r.next_day_pred], value: r.next_day_pred }],
            itemStyle: { color: '#FAAD14' }, label: { color: '#fff', formatter: '{c}' }
          } : { data: [] },
        },
      ],
    }, true)
  }
  if (cl) {
    const tl = r.train_losses || []
    const vl = r.val_losses || []
    const xs = tl.map((_, i) => i + 1)
    cl.setOption({
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['Train', 'Val'] },
      grid: { left: 48, right: 24, top: 32, bottom: 32 },
      xAxis: { type: 'category', data: xs },
      yAxis: { type: 'value', scale: true },
      series: [
        { name: 'Train', type: 'line', showSymbol: false, smooth: true, data: tl, itemStyle: { color: '#1677FF' } },
        { name: 'Val',   type: 'line', showSymbol: false, smooth: true, data: vl, itemStyle: { color: '#F5222D' } },
      ],
    }, true)
  }
}

// ---------- 模型管理 ----------
const modelList = ref([])
const modelFw = ref('')
async function refreshModels() {
  const r = await listModels(modelFw.value || undefined)
  modelList.value = r.models || []
}
watch(modelFw, refreshModels)

async function del(m) {
  await deleteModel(m)
  ElMessage.success('已删除')
  refreshModels()
}

import { onMounted } from 'vue'
onMounted(async () => {
  ch = echarts.init(chartRef.value)
  cl = echarts.init(lossRef.value)
  const r = () => { ch?.resize(); cl?.resize() }
  window.addEventListener('resize', r)
  window.__ws_resize_charts = r
  refreshModels()
})
onBeforeUnmount(() => { ws_close(); ch?.dispose(); cl?.dispose() })
</script>

<template>
  <div>
    <!-- 移动端浮动启动按钮：小屏永远可见，避免滚动/布局把启动按钮挤出视口 -->
    <button class="predict-fab" :class="{ 'is-loading': running }" @click="start" :disabled="running">
      <span v-if="running">执行中…</span>
      <span v-else>{{ result ? '重新预测' : '开始预测' }}</span>
    </button>

    <h2 class="page-title">股票预测（PyTorch / TensorFlow 双框架）</h2>
    <p class="page-desc">训练过程通过 WebSocket 实时推送 epoch/Loss；完成后展示 实际 vs 预测 曲线与评估指标。</p>

    <el-row :gutter="16">
      <el-col :span="8">
        <div class="card">
          <div style="font-weight:600; margin-bottom:12px">参数</div>
          <el-form :model="form" label-width="130px" size="default" label-position="right">
            <el-form-item label="框架">
              <el-radio-group v-model="form.framework">
                <el-radio-button label="pytorch" />
                <el-radio-button label="tensorflow" />
              </el-radio-group>
            </el-form-item>
            <el-form-item label="模型">
              <el-select v-model="form.model_type">
                <el-option label="LSTM" value="LSTM" />
                <el-option label="GRU" value="GRU" />
                <el-option label="Transformer" value="Transformer" />
              </el-select>
            </el-form-item>
            <el-form-item label="股票代码">
              <el-input v-model="form.stock_code" placeholder="sh.600036 / sz.000001" />
            </el-form-item>
            <el-form-item label="开始日期">
              <el-input v-model="form.start_date" />
            </el-form-item>
            <el-form-item label="结束日期">
              <el-input v-model="form.end_date" placeholder="空 = 最新" />
            </el-form-item>
            <el-form-item label="复权">
              <el-select v-model="form.adjustflag">
                <el-option label="后复权" value="1" />
                <el-option label="前复权" value="2" />
                <el-option label="不复权" value="3" />
              </el-select>
            </el-form-item>
            <el-form-item label="频率">
              <el-select v-model="form.frequency">
                <el-option label="日K" value="d" />
                <el-option label="周K" value="w" />
                <el-option label="月K" value="m" />
                <el-option label="5分钟" value="5" />
                <el-option label="30分钟" value="30" />
                <el-option label="60分钟" value="60" />
              </el-select>
            </el-form-item>
            <el-form-item label="特征列">
              <el-input v-model="form.feature_cols" />
            </el-form-item>
            <el-form-item label="目标列">
              <el-input v-model="form.target_col" />
            </el-form-item>
            <el-form-item label="序列长度">
              <el-input-number v-model="form.seq_len" :min="5" :max="240" />
            </el-form-item>
            <el-form-item label="训练集比例">
              <el-input-number v-model="form.train_ratio" :min="0.5" :max="0.95" :step="0.05" />
            </el-form-item>
            <el-form-item label="隐藏层">
              <el-input-number v-model="form.hidden_size" :min="16" :max="1024" :step="16" />
            </el-form-item>
            <el-form-item label="层数">
              <el-input-number v-model="form.num_layers" :min="1" :max="6" />
            </el-form-item>
            <el-form-item label="Dropout">
              <el-input-number v-model="form.dropout" :min="0" :max="0.9" :step="0.05" />
            </el-form-item>
            <el-form-item label="双向" v-if="form.model_type !== 'Transformer'">
              <el-switch v-model="form.bidirectional" />
            </el-form-item>
            <el-form-item label="d_model" v-if="form.model_type === 'Transformer'">
              <el-input-number v-model="form.d_model" :min="32" :max="1024" :step="32" />
            </el-form-item>
            <el-form-item label="注意力头" v-if="form.model_type === 'Transformer'">
              <el-input-number v-model="form.nhead" :min="1" :max="16" />
            </el-form-item>
            <el-form-item label="前馈维度" v-if="form.model_type === 'Transformer'">
              <el-input-number v-model="form.dim_feedforward" :min="64" :max="4096" :step="64" />
            </el-form-item>
            <el-form-item label="Epochs">
              <el-input-number v-model="form.epochs" :min="1" :max="1000" />
            </el-form-item>
            <el-form-item label="Batch size">
              <el-input-number v-model="form.batch_size" :min="8" :max="1024" />
            </el-form-item>
            <el-form-item label="学习率">
              <el-input v-model.number="form.learning_rate" />
            </el-form-item>
            <el-form-item label="优化器">
              <el-select v-model="form.optimizer_type">
                <el-option label="Adam" value="Adam" />
                <el-option label="SGD" value="SGD" />
                <el-option label="AdamW" value="AdamW" />
              </el-select>
            </el-form-item>
            <el-form-item label="损失">
              <el-select v-model="form.loss_type">
                <el-option label="MSE" value="MSE" />
                <el-option label="MAE" value="MAE" />
                <el-option label="Huber" value="Huber" />
              </el-select>
            </el-form-item>
            <el-form-item label="早停耐心">
              <el-input-number v-model="form.early_stopping_patience" :min="1" :max="100" />
            </el-form-item>
            <el-form-item label="保存名">
              <el-input v-model="form.model_name" placeholder="空=自动生成" />
            </el-form-item>
            <el-form-item class="predict-submit-item">
              <el-button type="primary" size="large" :loading="running" @click="start" class="predict-submit-btn">开始训练 / 执行预测</el-button>
            </el-form-item>
          </el-form>
        </div>

        <div class="card">
          <div style="display:flex; align-items:center; margin-bottom:12px">
            <div style="font-weight:600">已保存模型</div>
            <div style="flex:1"></div>
            <el-radio-group v-model="modelFw" size="small">
              <el-radio-button label="">全部</el-radio-button>
              <el-radio-button label="pytorch">PT</el-radio-button>
              <el-radio-button label="tensorflow">TF</el-radio-button>
            </el-radio-group>
            <el-button size="small" style="margin-left:8px" @click="refreshModels">刷新</el-button>
          </div>
          <el-table :data="modelList" size="small" stripe max-height="240">
            <el-table-column prop="$key" label="名称" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" type="danger" link @click="del(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>

      <el-col :span="16">
        <div class="card">
          <div style="display:flex; align-items:center">
            <div style="font-weight:600">训练进度</div>
            <div style="flex:1"></div>
            <div style="color:#86909c; font-size:12px">
              Epoch {{ progress.epoch }} / {{ progress.total_epochs }} ·
              TrainLoss {{ progress.train_loss }} · ValLoss {{ progress.val_loss }}
            </div>
          </div>
          <el-progress :percentage="pct" :stroke-width="12" style="margin:8px 0 12px" />
          <div ref="lossRef" style="height:240px"></div>
        </div>

        <div class="card">
          <div style="font-weight:600; margin-bottom:8px">实际值 vs 预测值（测试集）</div>
          <div v-if="result?.metrics" style="margin-bottom:8px; color:#4e5969; font-size:13px">
            <el-tag type="info">MAE {{ result.metrics.MAE }}</el-tag>
            <el-tag type="info" style="margin-left:8px">RMSE {{ result.metrics.RMSE }}</el-tag>
            <el-tag type="info" style="margin-left:8px">MAPE {{ result.metrics['MAPE%'] }}%</el-tag>
            <el-tag v-if="result?.next_day_pred != null" type="warning" style="margin-left:8px">
              下一交易日 {{ result.next_day_date }} 预测：{{ result.next_day_pred }}
            </el-tag>
            <el-tag v-if="result?.save_path" type="success" style="margin-left:8px">
              已保存 {{ result.save_path.split('/').pop() }}
            </el-tag>
          </div>
          <div ref="chartRef" style="height:360px"></div>
        </div>

        <div class="card">
          <div style="font-weight:600; margin-bottom:8px">日志</div>
          <el-scrollbar style="height:180px; background:#0e1116; color:#e5e6eb; padding:8px 12px; border-radius:6px; font-family: ui-monospace,Menlo,Consolas,monospace; font-size:12px">
            <div v-for="(l,i) in logs" :key="i">{{ l }}</div>
            <div v-if="!logs.length">（暂无）</div>
          </el-scrollbar>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
/* ============ 移动端浮动 FAB 启动按钮：仅 ≤768px 显示，桌面隐藏 ============ */
.predict-fab {
  display: none;  /* 桌面端不显示 */
}
@media (max-width: 768px) {
  .predict-fab {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    position: fixed;
    right: 16px;
    bottom: calc(18px + env(safe-area-inset-bottom, 0px));
    z-index: 1000;
    padding: 12px 20px;
    min-width: 128px;
    height: 48px;
    border-radius: 24px;
    border: none;
    background: linear-gradient(135deg, #1677FF 0%, #4096FF 100%);
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    box-shadow: 0 6px 18px rgba(22, 119, 255, 0.35);
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease, box-shadow 0.15s ease;
  }
  .predict-fab:active { transform: scale(0.97); }
  .predict-fab:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }
  .predict-fab.is-loading {
    background: linear-gradient(135deg, #86909c 0%, #4e5969 100%);
    box-shadow: 0 6px 18px rgba(78, 89, 105, 0.35);
  }
}

/* ============ 移动端 ≤768px：拆成单列、标签上移、避免重叠 ============ */
@media (max-width: 768px) {
  :deep(.el-row) { flex-direction: column; row-gap: 12px; }
  :deep(.el-col) { width: 100% !important; max-width: 100% !important; flex: none !important; }

  :deep(.el-form) {
    --el-form-label-width: 72px;
    --el-form-inline-label-width: 72px;
  }
  :deep(.el-form-item) {
    display: block;
    margin-bottom: 10px;
  }
  :deep(.el-form-item__label) {
    display: block;
    width: auto !important;
    text-align: left;
    margin-bottom: 4px;
    font-size: 12px;
    color: #4e5969;
    font-weight: 600;
  }
  :deep(.el-form-item__content) {
    margin-left: 0 !important;
    line-height: normal;
  }
  :deep(.el-form-item .el-select),
  :deep(.el-form-item .el-input),
  :deep(.el-form-item .el-input-number),
  :deep(.el-form-item .el-radio-group),
  :deep(.el-form-item .el-switch) {
    width: 100%;
  }
  :deep(.el-input-number) { width: 100% !important; }

  /* -------- 提交按钮（predict-submit-item：无 label 的那一项）：移动端强制可见 --------
     根因：没有 label 的 el-form-item 在 Element Plus label-position="right" + 移动端 display:block
     的样式下，__label 仍是空的块级元素（高度=0但影响 flex 对齐），按钮可能被 __content 的高度坍塌挤出或被父容器覆盖。
     处理：1. 空 label 显式隐藏/高度=0；2. content 占满整行；3. 按钮全宽、块级、足够内边距；4. 容器加足够 padding 避免被上面元素遮挡。 */
  :deep(.predict-submit-item) {
    display: block;
    margin-top: 16px;
    margin-bottom: 20px;
    padding: 12px 0 4px 0;
    border-top: 1px dashed #e5e6eb;
    visibility: visible !important;
    opacity: 1 !important;
  }
  :deep(.predict-submit-item .el-form-item__label) {
    display: none !important;
    height: 0;
    padding: 0;
    margin: 0;
  }
  :deep(.predict-submit-item .el-form-item__content) {
    display: block;
    width: 100%;
    margin-left: 0 !important;
    line-height: normal;
    min-height: 48px;
    visibility: visible !important;
  }
  :deep(.predict-submit-item .el-form-item__content > .el-form-item__content-wrap) {
    display: block;
    width: 100%;
  }
  :deep(.predict-submit-btn) {
    display: block !important;
    width: 100% !important;
    height: 48px !important;
    min-height: 48px !important;
    line-height: 46px !important;
    font-size: 16px !important;
    font-weight: 600 !important;
    visibility: visible !important;
    opacity: 1 !important;
    box-sizing: border-box !important;
  }

  :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 6px; }

  :deep(.el-table) { min-width: 100%; }

  :deep(.chart-card, .el-card) { margin-bottom: 12px; }

  .el-progress, :deep(.el-progress) { margin: 6px 0 10px; }

  :deep(.el-scrollbar) { padding: 6px 8px !important; }
}
</style>
