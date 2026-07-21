<template>
  <div>
    <!-- 生效规则摘要 -->
    <el-alert v-if="ruleSummary" type="info" :closable="false" class="rule-bar">
      <template #title>
        当前生效规则：映射 {{ ruleSummary.mappings }} 条，特殊产品 {{ ruleSummary.bulk }} 个，
        差异阈值 {{ ruleSummary.diff_pct }}%，相似度阈值 {{ ruleSummary.fuzzy_sim }}
        <span class="rule-tip">（规则热生效：本任务按提交时刻规则库执行）</span>
      </template>
    </el-alert>

    <!-- 新建任务 -->
    <el-card v-if="phase === 'upload'" shadow="never">
      <template #header><span>新建 M1 核对任务</span></template>
      <el-form label-width="130px">
        <el-form-item label="取数模式">
          <el-radio-group v-model="fetchMode">
            <el-radio-button value="file">文件上传</el-radio-button>
            <el-radio-button value="db">数据库查询</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="fetchMode === 'file'">
          <el-form-item label="基金资产表" required>
            <el-upload drag :auto-upload="false" :limit="1" accept=".xls,.xlsx"
                       :on-change="(f) => onFile('fund', f)" :on-remove="() => (files.fund = null)">
              <el-icon size="40"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em>（.xls/.xlsx）</div>
            </el-upload>
          </el-form-item>
          <el-form-item label="净值查询表" required>
            <el-upload drag :auto-upload="false" :limit="1" accept=".xls,.xlsx"
                       :on-change="(f) => onFile('netvalue', f)" :on-remove="() => (files.netvalue = null)">
              <el-icon size="40"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em>（.xls/.xlsx）</div>
            </el-upload>
          </el-form-item>
          <el-form-item label="业务日期">
            <el-date-picker v-model="bizDate" type="date" value-format="YYYYMMDD" placeholder="默认当天" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="基金资产模板" required>
            <el-select v-model="dbForm.fundTemplateId" filterable placeholder="选择 m1_fund 查询模板"
                       class="tpl-select" :loading="tplLoading">
              <el-option v-for="t in templates.m1_fund" :key="t.id" :value="t.id"
                         :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
            </el-select>
          </el-form-item>
          <el-form-item label="净值查询模板" required>
            <el-select v-model="dbForm.netvalueTemplateId" filterable placeholder="选择 m1_netvalue 查询模板"
                       class="tpl-select" :loading="tplLoading">
              <el-option v-for="t in templates.m1_netvalue" :key="t.id" :value="t.id"
                         :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
            </el-select>
          </el-form-item>
          <el-form-item label="业务日期" required>
            <el-date-picker v-model="bizDate" type="date" value-format="YYYYMMDD" placeholder="必选（注入 :biz_date）" />
          </el-form-item>
          <el-alert v-if="dbSummary.length" type="info" :closable="false" class="db-summary">
            <template #title>将执行以下查询（结果落查询快照后进同一核对引擎）</template>
            <div v-for="(s, i) in dbSummary" :key="i" class="db-summary-line">
              {{ s.label }}：{{ s.name }}（数据源: {{ s.ds }}）— {{ s.sql }}
            </div>
          </el-alert>
        </template>

        <el-form-item>
          <el-button type="primary" size="large" :disabled="!canSubmit" :loading="submitting" @click="submit">
            开始核对
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 执行中 -->
    <el-card v-if="phase === 'running'" shadow="never">
      <template #header><span>任务执行中（{{ job?.job_id }}）</span></template>
      <el-progress :percentage="job?.progress || 0" :status="job?.status === 'failed' ? 'exception' : undefined" />
      <div class="log-box" ref="logBox">
        <div v-for="(line, i) in job?.log_tail || []" :key="i" class="log-line">{{ line }}</div>
      </div>
    </el-card>

    <!-- 结果 -->
    <template v-if="phase === 'done' && job">
      <el-alert v-if="job.status === 'failed'" type="error" :closable="false" class="error-bar">
        <template #title>任务执行失败</template>
        <pre class="error-text">{{ job.error }}</pre>
      </el-alert>
      <el-card v-if="job.status === 'success'" shadow="never">
        <template #header>
          <div class="result-header">
            <span>核对结果（{{ job.result_filename }}）</span>
            <div>
              <el-button type="primary" @click="download">下载结果 Excel</el-button>
              <el-button @click="reset">新建任务</el-button>
            </div>
          </div>
        </template>
        <el-row :gutter="12">
          <el-col :span="4" v-for="(v, k) in job.stats" :key="k">
            <div class="stat-box" :class="statClass(k, v)">
              <div class="stat-num">{{ v }}</div>
              <div class="stat-name">{{ k }}</div>
            </div>
          </el-col>
        </el-row>
      </el-card>
      <el-button v-if="job.status === 'failed'" type="primary" @click="reset">重新上传</el-button>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import api, { downloadFile } from '../api'
import { useJobPolling } from '../utils/useJobPolling'

const phase = ref('upload')   // upload | running | done
const files = reactive({ fund: null, netvalue: null })
const bizDate = ref('')
const submitting = ref(false)
const ruleSummary = ref(null)
const logBox = ref(null)

/* DS-F4 取数模式：file 文件上传（默认）/ db 数据库查询（模板 + 数据源，同步取数落快照） */
const fetchMode = ref('file')
const dbForm = reactive({ fundTemplateId: null, netvalueTemplateId: null })
const templates = reactive({ m1_fund: [], m1_netvalue: [] })
const tplLoading = ref(false)

const canSubmit = computed(() => {
  if (submitting.value) return false
  if (fetchMode.value === 'db') {
    return Boolean(dbForm.fundTemplateId && dbForm.netvalueTemplateId && bizDate.value)
  }
  return Boolean(files.fund && files.netvalue)
})

const { job, start } = useJobPolling(2000)

function onFile(kind, uploadFile) {
  files[kind] = uploadFile.raw
}

async function loadTemplates() {
  tplLoading.value = true
  try {
    const [fund, netvalue] = await Promise.all([
      api.get('/query-templates', { params: { module: 'm1_fund' } }),
      api.get('/query-templates', { params: { module: 'm1_netvalue' } }),
    ])
    templates.m1_fund = fund.data
    templates.m1_netvalue = netvalue.data
  } catch {
    templates.m1_fund = []
    templates.m1_netvalue = []
  } finally {
    tplLoading.value = false
  }
}

/* 提交前回显所选模板与 SQL 摘要，便于复核 */
const dbSummary = computed(() => {
  if (fetchMode.value !== 'db') return []
  const pick = (list, id) => list.find((t) => t.id === id)
  const fund = pick(templates.m1_fund, dbForm.fundTemplateId)
  const netvalue = pick(templates.m1_netvalue, dbForm.netvalueTemplateId)
  if (!fund || !netvalue) return []
  const cut = (s) => (s && s.length > 100 ? `${s.slice(0, 100)}…` : s)
  return [
    { label: '基金资产表模板', name: fund.name, ds: fund.ds_name || '?', sql: cut(fund.sql_text) },
    { label: '净值查询表模板', name: netvalue.name, ds: netvalue.ds_name || '?', sql: cut(netvalue.sql_text) },
  ]
})

async function loadRules() {
  try {
    const [m, b, t] = await Promise.all([
      api.get('/rules/mappings'),
      api.get('/rules/bulk-products'),
      api.get('/rules/thresholds'),
    ])
    const tmap = Object.fromEntries(t.data.map((x) => [x.param_key, x.param_value]))
    ruleSummary.value = {
      mappings: m.data.length,
      bulk: b.data.length,
      diff_pct: tmap.diff_pct ?? '-',
      fuzzy_sim: tmap.fuzzy_sim ?? '-',
    }
  } catch {
    ruleSummary.value = null   // 无权限查看规则时不阻塞建任务
  }
}

async function submit() {
  if (fetchMode.value === 'db' && !bizDate.value) {
    ElMessage.warning('数据库查询模式必须选择业务日期（注入 :biz_date）')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    if (fetchMode.value === 'db') {
      fd.append('fetch_mode', 'db')
      fd.append('fund_template_id', dbForm.fundTemplateId)
      fd.append('netvalue_template_id', dbForm.netvalueTemplateId)
      fd.append('biz_date', bizDate.value)
    } else {
      fd.append('fund_file', files.fund)
      fd.append('netvalue_file', files.netvalue)
      if (bizDate.value) fd.append('biz_date', bizDate.value)
    }
    const resp = await api.post('/recon/m1/jobs', fd)
    ElMessage.success(resp.data.message || '任务已创建')
    phase.value = 'running'
    start(resp.data.job_id)
  } finally {
    submitting.value = false
  }
}

watch(
  () => job.value?.status,
  async (s) => {
    if (s === 'success' || s === 'failed') phase.value = 'done'
    await nextTick()
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  },
)

function statClass(k, v) {
  if (k.includes('未匹配') && v > 0) return 'warn'
  if (k.includes('差异') && v > 0) return 'danger'
  return ''
}

function download() {
  downloadFile(`/recon/jobs/${job.value.job_id}/download`, job.value.result_filename || 'result.xlsx')
}

function reset() {
  files.fund = null
  files.netvalue = null
  dbForm.fundTemplateId = null
  dbForm.netvalueTemplateId = null
  bizDate.value = ''
  phase.value = 'upload'
}

onMounted(() => {
  loadRules()
  loadTemplates()
})
</script>

<style scoped>
.rule-bar { margin-bottom: 16px; }
.rule-tip { color: #909399; font-size: 12px; }
.log-box {
  margin-top: 16px; height: 320px; overflow-y: auto;
  background: #1e1e1e; color: #d4d4d4; padding: 12px;
  border-radius: 4px; font-family: Consolas, monospace; font-size: 12px;
}
.log-line { white-space: pre-wrap; line-height: 1.6; }
.result-header { display: flex; justify-content: space-between; align-items: center; }
.stat-box { text-align: center; padding: 14px 0; background: #f7f9fc; border-radius: 6px; }
.stat-box.warn { background: #fdf6ec; }
.stat-box.danger { background: #fef0f0; }
.stat-num { font-size: 22px; font-weight: 700; color: #2c5282; }
.stat-box.warn .stat-num { color: #b7791f; }
.stat-box.danger .stat-num { color: #c53030; }
.stat-name { font-size: 12px; color: #909399; margin-top: 4px; }
.error-bar { margin-bottom: 16px; }
.error-text { white-space: pre-wrap; margin: 8px 0 0; font-size: 13px; }
.tpl-select { width: 460px; }
.db-summary { margin: 0 0 18px 130px; }
.db-summary-line { font-size: 12px; color: #606266; line-height: 1.7; word-break: break-all; }
</style>
