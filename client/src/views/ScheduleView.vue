<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>定时任务（APScheduler 持久化调度，重启不丢；失败自动重试 1 次）</span>
          <div>
            <el-button @click="load">刷新</el-button>
            <el-button type="primary" @click="openEdit(null)">新建定时任务</el-button>
          </div>
        </div>
      </template>
      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="name" label="任务名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="模块" width="70">
          <template #default="{ row }">{{ row.module.toUpperCase() }}</template>
        </el-table-column>
        <el-table-column label="取数" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.fetch_mode === 'db' ? 'warning' : 'info'">
              {{ row.fetch_mode === 'db' ? '数据库' : '文件' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="cron_expr" label="cron 表达式" width="140" />
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="最近执行" width="200">
          <template #default="{ row }">
            <div v-if="row.last_status">
              <el-tag :type="statusType(row.last_status)" size="small">{{ statusName(row.last_status) }}</el-tag>
              <span class="last-time">{{ row.last_run_at }}</span>
            </div>
            <span v-else class="last-time">（未执行）</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text type="primary" size="small" @click="runNow(row)">立即执行</el-button>
            <el-button text type="primary" size="small" @click="openHistory(row)">执行历史</el-button>
            <el-popconfirm title="确认删除该定时任务？" @confirm="remove(row)">
              <template #reference>
                <el-button text type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>暂无定时任务（定时自动任务不预置，请自行创建）</template>
      </el-table>
      <div v-if="lastError" class="error-tip">最近失败：{{ lastError }}</div>
    </el-card>

    <!-- 新建/编辑 -->
    <el-dialog v-model="editVisible" :title="editForm.id ? '编辑定时任务' : '新建定时任务'" width="720px" destroy-on-close>
      <el-form label-width="130px">
        <el-form-item label="任务名称" required>
          <el-input v-model="editForm.name" placeholder="如：每日M1核对（db 取数）" />
        </el-form-item>
        <el-form-item label="模块" required>
          <el-radio-group v-model="editForm.module">
            <el-radio-button value="m1">M1 基金资产与净值核对</el-radio-button>
            <el-radio-button value="m2">M2 估值价格核对</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="取数模式" required>
          <el-radio-group v-model="editForm.fetch_mode">
            <el-radio-button value="file">文件监测目录</el-radio-button>
            <el-radio-button value="db">数据库查询</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="editForm.fetch_mode === 'file'">
          <el-form-item label="监测目录" required>
            <el-input v-model="editForm.file_dir" placeholder="绝对路径，如 D:\O32\每日导出（执行时检查一次）" />
          </el-form-item>
        </template>
        <template v-else-if="editForm.module === 'm1'">
          <el-form-item label="基金资产模板" required>
            <el-select v-model="editForm.fund_template_id" filterable class="tpl-select" :loading="tplLoading">
              <el-option v-for="t in templates.m1_fund" :key="t.id" :value="t.id"
                         :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
            </el-select>
          </el-form-item>
          <el-form-item label="净值查询模板" required>
            <el-select v-model="editForm.netvalue_template_id" filterable class="tpl-select" :loading="tplLoading">
              <el-option v-for="t in templates.m1_netvalue" :key="t.id" :value="t.id"
                         :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item v-for="(g, i) in editGroups" :key="i" :label="`产品组 ${i + 1}`" required>
            <div class="db-group-row">
              <el-input v-model="g.product" class="grp-product" clearable
                        placeholder="产品标识（可空，从系统端模板名派生）" />
              <el-select v-model="g.system_template_id" filterable class="grp-tpl" :loading="tplLoading"
                         placeholder="系统端模板（m2_system）">
                <el-option v-for="t in templates.m2_system" :key="t.id" :value="t.id"
                           :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
              </el-select>
              <el-select v-model="g.valuation_template_id" filterable class="grp-tpl" :loading="tplLoading"
                         placeholder="估值表模板（m2_valuation）">
                <el-option v-for="t in templates.m2_valuation" :key="t.id" :value="t.id"
                           :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
              </el-select>
              <el-button text type="danger" :disabled="editGroups.length === 1" @click="editGroups.splice(i, 1)">删除</el-button>
            </div>
          </el-form-item>
          <el-form-item label=" ">
            <el-button @click="editGroups.push({ product: '', system_template_id: null, valuation_template_id: null })">添加产品组</el-button>
          </el-form-item>
        </template>

        <el-form-item label="执行时间" required>
          <el-select v-model="cronQuick" class="cron-quick" placeholder="常用时间快捷选项" @change="onCronQuick">
            <el-option label="工作日 17:47（数据就绪缓冲后）" value="47 17 * * 1-5" />
            <el-option label="工作日 18:07" value="7 18 * * 1-5" />
            <el-option label="工作日 18:23" value="23 18 * * 1-5" />
            <el-option label="每日 18:37" value="37 18 * * *" />
            <el-option label="自定义 cron" value="" />
          </el-select>
          <el-input v-model="editForm.cron_expr" class="cron-input"
                    placeholder="5 段 cron：分 时 日 月 周（建议避开整点/半点）" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 执行历史抽屉 -->
    <el-drawer v-model="historyVisible" :title="`执行历史${historyRow ? '：' + historyRow.name : ''}`" size="760px">
      <el-table :data="executions" v-loading="historyLoading" stripe size="small">
        <el-table-column prop="job_id" label="任务ID" width="140" />
        <el-table-column prop="module" label="模块" width="60" />
        <el-table-column prop="biz_date" label="业务日期" width="100" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusName(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果/错误" min-width="240">
          <template #default="{ row }">
            <span v-if="row.status === 'success'">{{ statsText(row.stats) }}</span>
            <span v-else class="err-text">{{ row.error || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="finished_at" label="完成时间" width="150" />
        <template #empty>暂无定时执行记录</template>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const loading = ref(false)
const rows = ref([])
const templates = reactive({ m1_fund: [], m1_netvalue: [], m2_system: [], m2_valuation: [] })
const tplLoading = ref(false)

const editVisible = ref(false)
const saving = ref(false)
const cronQuick = ref('')
const editForm = reactive({
  id: null, name: '', module: 'm1', fetch_mode: 'db',
  fund_template_id: null, netvalue_template_id: null,
  file_dir: '', cron_expr: '7 18 * * 1-5', enabled: true,
})
const editGroups = ref([{ product: '', system_template_id: null, valuation_template_id: null }])

const historyVisible = ref(false)
const historyLoading = ref(false)
const historyRow = ref(null)
const executions = ref([])

const lastError = computed(() => {
  const row = rows.value.find((r) => r.last_status === 'failed' && r.last_error)
  return row ? `${row.name}：${row.last_error}` : ''
})

const canSave = computed(() => {
  const f = editForm
  if (!f.name.trim() || !f.cron_expr.trim()) return false
  if (f.fetch_mode === 'file') return Boolean(f.file_dir.trim())
  if (f.module === 'm1') return Boolean(f.fund_template_id && f.netvalue_template_id)
  return editGroups.value.length > 0
    && editGroups.value.every((g) => g.system_template_id && g.valuation_template_id)
})

function statusType(s) {
  return { success: 'success', failed: 'danger', running: 'warning', pending: 'info', wait_file: 'warning', retrying: 'warning' }[s] || 'info'
}
function statusName(s) {
  return { success: '成功', failed: '失败', running: '执行中', pending: '排队中', wait_file: '待文件', retrying: '重试中' }[s] || s
}
function statsText(stats) {
  if (!stats) return '成功'
  return Object.entries(stats).map(([k, v]) => `${k} ${v}`).join('，')
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/schedule/jobs')
    rows.value = data
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  tplLoading.value = true
  try {
    const [f, n, s, v] = await Promise.all([
      api.get('/query-templates', { params: { module: 'm1_fund' } }),
      api.get('/query-templates', { params: { module: 'm1_netvalue' } }),
      api.get('/query-templates', { params: { module: 'm2_system' } }),
      api.get('/query-templates', { params: { module: 'm2_valuation' } }),
    ])
    templates.m1_fund = f.data
    templates.m1_netvalue = n.data
    templates.m2_system = s.data
    templates.m2_valuation = v.data
  } finally {
    tplLoading.value = false
  }
}

function onCronQuick(v) {
  if (v) editForm.cron_expr = v
}

function openEdit(row) {
  if (row) {
    Object.assign(editForm, {
      id: row.id, name: row.name, module: row.module, fetch_mode: row.fetch_mode,
      fund_template_id: row.fund_template_id, netvalue_template_id: row.netvalue_template_id,
      file_dir: row.file_dir || '', cron_expr: row.cron_expr, enabled: row.enabled,
    })
    try {
      const groups = JSON.parse(row.groups_json || '[]')
      editGroups.value = groups.length
        ? groups.map((g) => ({ product: g.product || '', system_template_id: g.system_template_id, valuation_template_id: g.valuation_template_id }))
        : [{ product: '', system_template_id: null, valuation_template_id: null }]
    } catch {
      editGroups.value = [{ product: '', system_template_id: null, valuation_template_id: null }]
    }
  } else {
    Object.assign(editForm, {
      id: null, name: '', module: 'm1', fetch_mode: 'db',
      fund_template_id: null, netvalue_template_id: null,
      file_dir: '', cron_expr: '7 18 * * 1-5', enabled: true,
    })
    editGroups.value = [{ product: '', system_template_id: null, valuation_template_id: null }]
  }
  cronQuick.value = ''
  editVisible.value = true
}

async function save() {
  saving.value = true
  try {
    const f = editForm
    const body = {
      name: f.name.trim(), module: f.module, fetch_mode: f.fetch_mode,
      cron_expr: f.cron_expr.trim(), enabled: f.enabled,
      fund_template_id: f.fund_template_id, netvalue_template_id: f.netvalue_template_id,
      file_dir: f.file_dir.trim() || null,
      groups_json: null,
    }
    if (f.fetch_mode === 'db' && f.module === 'm2') {
      body.groups_json = JSON.stringify(editGroups.value.map((g) => ({
        ...((g.product || '').trim() ? { product: g.product.trim() } : {}),
        system_template_id: g.system_template_id,
        valuation_template_id: g.valuation_template_id,
      })))
    }
    if (f.id) {
      await api.put(`/schedule/jobs/${f.id}`, body)
      ElMessage.success('定时任务已更新')
    } else {
      await api.post('/schedule/jobs', body)
      ElMessage.success('定时任务已创建')
    }
    editVisible.value = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggle(row) {
  try {
    const { data } = await api.post(`/schedule/jobs/${row.id}/toggle`)
    row.enabled = data.enabled
    ElMessage.success(`「${row.name}」已${data.enabled ? '启用' : '停用'}`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function runNow(row) {
  try {
    const { data } = await api.post(`/schedule/jobs/${row.id}/run-now`)
    ElMessage.success(data.message || '已触发立即执行')
    setTimeout(load, 3000)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}

async function remove(row) {
  try {
    await api.delete(`/schedule/jobs/${row.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function openHistory(row) {
  historyRow.value = row
  historyVisible.value = true
  historyLoading.value = true
  try {
    const { data } = await api.get('/schedule/executions', {
      params: row ? { schedule_id: row.id } : {},
    })
    executions.value = data
  } finally {
    historyLoading.value = false
  }
}

onMounted(() => {
  load()
  loadTemplates()
})
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.last-time { margin-left: 8px; color: #909399; font-size: 12px; }
.tpl-select { width: 460px; }
.db-group-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.grp-product { width: 230px; }
.grp-tpl { width: 300px; }
.cron-quick { width: 260px; margin-right: 8px; }
.cron-input { width: 260px; }
.error-tip { margin-top: 10px; color: #c53030; font-size: 12px; }
.err-text { color: #c53030; }
</style>
