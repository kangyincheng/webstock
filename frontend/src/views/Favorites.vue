<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { favList, favAdd, favUpdate, favDelete, favRefresh, favCheckEvents } from '../api/index.js'

const rows = ref([])
const loading = ref(false)

const dialog = ref(false)
const mode = ref('add')
const form = reactive({
  id: null,
  code: '', name: '', buy_date: '', buy_price: null,
  current_price: null, note: '',
  events: [],
})
function resetForm() {
  Object.assign(form, { id: null, code: '', name: '', buy_date: '', buy_price: null, current_price: null, note: '', events: [] })
}
function openAdd() {
  mode.value = 'add'
  resetForm()
  dialog.value = true
}
function openEdit(row) {
  mode.value = 'edit'
  Object.assign(form, {
    id: row.id, code: row.code, name: row.name, buy_date: row.buy_date || '',
    buy_price: row.buy_price ?? null, current_price: row.current_price ?? null,
    note: row.note || '', events: (row.events || []).map(e => ({ ...e })),
  })
  dialog.value = true
}
function addEvent() { form.events.push({ title: '', due_date: '' }) }
function delEvent(i) { form.events.splice(i, 1) }

async function submit() {
  try {
    if (mode.value === 'add') await favAdd({ ...form })
    else await favUpdate(form.id, { ...form })
    ElMessage.success('已保存')
    dialog.value = false
    reload()
  } catch (e) { ElMessage.error(e.message) }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 ${row.name}？`, '提示', { type: 'warning' })
  await favDelete(row.id)
  ElMessage.success('已删除')
  reload()
}

async function reload() {
  loading.value = true
  try { rows.value = (await favList()).rows || [] }
  catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

async function refresh() {
  try {
    await favRefresh()
    ElMessage.success('后台已提交刷新，请稍后查看')
    setTimeout(reload, 2000)
  } catch (e) { ElMessage.error(e.message) }
}

async function checkEvents() {
  try {
    const r = await favCheckEvents()
    const list = r.due_events || []
    if (!list.length) { ElMessage.info('无到期事件'); return }
    ElMessageBox.alert(
      list.map(e => `📌 ${e.name}(${e.code}) - ${e.title} · ${e.due_date}`).join('<br/>'),
      `到期事件 ${list.length} 条`,
      { dangerouslyUseHTMLString: true }
    )
    reload()
  } catch (e) { ElMessage.error(e.message) }
}

function gainClass(v) {
  if (v === null || v === undefined) return ''
  return Number(v) >= 0 ? 'gain-up' : 'gain-down'
}

onMounted(reload)
</script>

<template>
  <div>
    <h2 class="page-title">自选股</h2>
    <p class="page-desc">事件到期自动标红。支持批量刷新当前价（baostock 最新收盘价）。</p>

    <div class="card">
      <el-space wrap style="margin-bottom:12px">
        <el-button type="primary" @click="openAdd">➕ 添加自选</el-button>
        <el-button :loading="loading" @click="reload">🔄 列表刷新</el-button>
        <el-button type="success" @click="refresh">💹 刷新行情（后台）</el-button>
        <el-button type="warning" @click="checkEvents">⏰ 检查到期事件</el-button>
      </el-space>

      <el-table :data="rows" stripe border :loading="loading" max-height="72vh"
        :row-class-name="({row}) => row.event_overdue ? 'row-due' : ''">
        <el-table-column label="#" width="60" type="index" />
        <el-table-column prop="name" label="股票名称" min-width="120" />
        <el-table-column prop="code" label="代码" min-width="140" />
        <el-table-column prop="buy_date" label="买入日期" min-width="120" />
        <el-table-column prop="buy_price" label="买入价" min-width="100" align="right" />
        <el-table-column prop="current_price" label="当前价" min-width="100" align="right" />
        <el-table-column prop="gain_pct" label="收益(%)" min-width="100" align="right"
          :cell-class-name="({row}) => gainClass(row.gain_pct)" />
        <el-table-column prop="nearest_event" label="最近事件" min-width="140" />
        <el-table-column prop="nearest_due" label="到期日" min-width="120" />
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link @click="openEdit(row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="mode==='add' ? '添加自选' : '编辑自选'" width="640px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="股票代码"><el-input v-model="form.code" placeholder="sh.600036" /></el-form-item>
        <el-form-item label="股票名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="买入日期"><el-input v-model="form.buy_date" placeholder="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="买入价"><el-input-number v-model="form.buy_price" :precision="3" :step="0.1" :min="0" /></el-form-item>
        <el-form-item label="当前价"><el-input-number v-model="form.current_price" :precision="3" :step="0.1" :min="0" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="事件列表">
          <div>
            <div v-for="(e,i) in form.events" :key="i" style="display:flex; gap:8px; margin-bottom:6px">
              <el-input v-model="e.title" placeholder="事件标题，如：业绩预告披露" style="flex:1" />
              <el-input v-model="e.due_date" placeholder="YYYY-MM-DD" style="width:180px" />
              <el-button size="small" type="danger" plain @click="delEvent(i)">移除</el-button>
            </div>
            <el-button size="small" @click="addEvent">➕ 新增事件</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
:deep(.row-due td) { background: #fff1f0 !important; color: #cf1322; font-weight: 600; }
:deep(.gain-up) { color: #F5222D !important; font-weight: 600; }
:deep(.gain-down) { color: #52C41A !important; font-weight: 600; }
</style>
