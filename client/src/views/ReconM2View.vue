<template>
  <div>
    <!-- 新建任务 -->
    <el-card v-if="phase === 'upload'" shadow="never">
      <template #header><span>新建 M2 基金估值价格核对任务（多产品批量，按文件名产品标识自动配对）</span></template>
      <el-form label-width="130px">
        <el-form-item label="取数模式">
          <el-radio-group v-model="fetchMode">
            <el-radio-button value="file">文件上传</el-radio-button>
            <el-radio-button value="db">数据库查询</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="fetchMode === 'file'">
          <el-form-item label="系统端文件" required>
            <el-upload drag multiple :auto-upload="false" accept=".xls,.xlsx"
                       :file-list="fileList.system"
                       :on-change="(f, fl) => onFiles('system', fl)"
                       :on-remove="(f, fl) => onFiles('system', fl)">
              <el-icon size="40"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖拽文件到此处，或 <em>点击选择</em>（新综合信息查询_基金证券-6301.xls，可多选）
              </div>
            </el-upload>
          </el-form-item>
          <el-form-item label="估值表文件" required>
            <el-upload drag multiple :auto-upload="false" accept=".xls,.xlsx"
                       :file-list="fileList.valuation"
                       :on-change="(f, fl) => onFiles('valuation', fl)"
                       :on-remove="(f, fl) => onFiles('valuation', fl)">
              <el-icon size="40"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖拽文件到此处，或 <em>点击选择</em>（证券投资基金估值表_6301-XXXX.xls，可多选）
              </div>
            </el-upload>
          </el-form-item>

          <!-- 配对预览 -->
          <el-form-item v-if="pairRows.length" label="配对预览">
            <el-table :data="pairRows" size="small" border class="pair-table">
              <el-table-column prop="product" label="产品标识" width="110" />
              <el-table-column prop="system" label="系统端文件" min-width="240">
                <template #default="{ row }">{{ row.system || '（缺）' }}</template>
              </el-table-column>
              <el-table-column prop="valuation" label="估值表文件" min-width="240">
                <template #default="{ row }">{{ row.valuation || '（缺）' }}</template>
              </el-table-column>
              <el-table-column label="配对状态" width="110">
                <template #default="{ row }">
                  <el-tag v-if="row.ok" type="success">已配对</el-tag>
                  <el-tag v-else type="danger">落单</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="unpairedNames.length" class="pair-warn">
              以下文件未识别到产品标识（文件名需含 4 位数字，如 6301）：{{ unpairedNames.join('、') }}
            </div>
          </el-form-item>

          <el-form-item label="业务日期">
            <el-date-picker v-model="bizDate" type="date" value-format="YYYYMMDD" placeholder="默认当天" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item v-for="(g, i) in dbGroups" :key="i" :label="`产品组 ${i + 1}`" required>
            <div class="db-group-row">
              <el-input v-model="g.product" class="grp-product" clearable
                        placeholder="产品标识（可空，从系统端模板名派生）" />
              <el-select v-model="g.system_template_id" filterable :loading="tplLoading"
                         class="grp-tpl" placeholder="系统端模板（m2_system）">
                <el-option v-for="t in templates.m2_system" :key="t.id" :value="t.id"
                           :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
              </el-select>
              <el-select v-model="g.valuation_template_id" filterable :loading="tplLoading"
                         class="grp-tpl" placeholder="估值表模板（m2_valuation）">
                <el-option v-for="t in templates.m2_valuation" :key="t.id" :value="t.id"
                           :label="`${t.name}（数据源: ${t.ds_name || '?'}）`" />
              </el-select>
              <el-button text type="danger" :disabled="dbGroups.length === 1"
                         @click="dbGroups.splice(i, 1)">删除</el-button>
            </div>
          </el-form-item>
          <el-form-item label=" ">
            <el-button @click="addGroup">添加产品组</el-button>
          </el-form-item>
          <el-form-item label="业务日期" required>
            <el-date-picker v-model="bizDate" type="date" value-format="YYYYMMDD" placeholder="必选（注入 :biz_date）" />
          </el-form-item>
          <el-alert v-if="dbSummary.length" type="info" :closable="false" class="db-summary">
            <template #title>将执行以下查询（结果落查询快照后进同一核对引擎）</template>
            <div v-for="(s, i) in dbSummary" :key="i" class="db-summary-line">
              产品 {{ s.product }}：系统端 {{ s.system }} ／ 估值表 {{ s.valuation }}
            </div>
          </el-alert>
        </template>

        <el-form-item>
          <el-button type="primary" size="large" :disabled="!canSubmit" :loading="submitting" @click="submit">
            开始核对（{{ groupCount }} 个产品）
          </el-button>
          <span class="submit-hint">科目取价规则取自【系统管理-系统配置】，任务执行时现取（热生效）</span>
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
            <span>核对结果（合计：{{ totalText }}）</span>
            <el-button @click="reset">新建任务</el-button>
          </div>
        </template>
        <el-tabs v-model="activeProduct">
          <el-tab-pane v-for="p in productList" :key="p" :label="`产品 ${p}`" :name="p">
            <el-row :gutter="12">
              <el-col :span="6" v-for="(v, k) in job.stats.products[p]" :key="k">
                <div class="stat-box" :class="(k === '差异' || k === '单边') && v > 0 ? 'warn' : ''">
                  <div class="stat-num">{{ v }}</div>
                  <div class="stat-name">{{ k }}</div>
                </div>
              </el-col>
            </el-row>
            <div class="download-row">
              <el-button type="primary" @click="download(p)">下载 {{ p }} 核对报告</el-button>
            </div>
          </el-tab-pane>
        </el-tabs>
        <div class="color-legend">
          <el-tag effect="dark" color="#c6efce" style="color:#1f2d3d">绿：一致</el-tag>
          <el-tag effect="dark" color="#ffc7ce" style="color:#1f2d3d">红：差异</el-tag>
          <el-tag effect="dark" color="#ffc000" style="color:#1f2d3d">橙：单边</el-tag>
        </div>
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

const phase = ref('upload')
const fileList = ref({ system: [], valuation: [] })
const bizDate = ref('')
const submitting = ref(false)
const logBox = ref(null)
const activeProduct = ref('')

/* DS-F4 取数模式：file 文件上传（默认）/ db 数据库查询（按产品组配模板，同步取数落快照） */
const fetchMode = ref('file')
const dbGroups = ref([{ product: '', system_template_id: null, valuation_template_id: null }])
const templates = reactive({ m2_system: [], m2_valuation: [] })
const tplLoading = ref(false)

const { job, start } = useJobPolling(2000)

/** 与后端 _extract_product_id 同口径：文件名首个 4 位及以上数字组 */
function extractProduct(name) {
  const stem = (name || '').replace(/\.[^.]+$/, '')
  const m = stem.match(/(\d{4,})/)
  return m ? m[1] : null
}

const pairRows = computed(() => {
  const sysMap = {}
  const valMap = {}
  const noId = []
  for (const f of fileList.value.system) {
    const p = extractProduct(f.name)
    if (p) sysMap[p] = f.name
  }
  for (const f of fileList.value.valuation) {
    const p = extractProduct(f.name)
    if (p) valMap[p] = f.name
  }
  for (const f of [...fileList.value.system, ...fileList.value.valuation]) {
    if (!extractProduct(f.name)) noId.push(f.name)
  }
  const products = [...new Set([...Object.keys(sysMap), ...Object.keys(valMap)])].sort()
  return products.map((p) => ({
    product: p,
    system: sysMap[p] || '',
    valuation: valMap[p] || '',
    ok: Boolean(sysMap[p] && valMap[p]),
    _noId: noId,
  }))
})

const unpairedNames = computed(() => pairRows.value[0]?._noId || [])
const pairedCount = computed(() => pairRows.value.filter((r) => r.ok).length)
const groupCount = computed(() => (fetchMode.value === 'db' ? dbGroups.value.length : pairedCount.value))
const canSubmit = computed(() => {
  if (submitting.value) return false
  if (fetchMode.value === 'db') {
    return Boolean(bizDate.value)
      && dbGroups.value.length > 0
      && dbGroups.value.every((g) => g.system_template_id && g.valuation_template_id)
  }
  return pairedCount.value > 0
    && pairRows.value.every((r) => r.ok)
    && unpairedNames.value.length === 0
})

/* 提交前回显所选模板分组，便于复核 */
const dbSummary = computed(() => {
  if (fetchMode.value !== 'db') return []
  const findTpl = (list, id) => list.find((t) => t.id === id)
  return dbGroups.value
    .map((g) => {
      const sys = findTpl(templates.m2_system, g.system_template_id)
      const val = findTpl(templates.m2_valuation, g.valuation_template_id)
      if (!sys || !val) return null
      const m = (sys.name || '').match(/(\d{4,})/)
      return {
        product: (g.product || '').trim() || (m ? m[1] : '未识别'),
        system: `${sys.name}（数据源: ${sys.ds_name || '?'}）`,
        valuation: `${val.name}（数据源: ${val.ds_name || '?'}）`,
      }
    })
    .filter(Boolean)
})

const productList = computed(() => Object.keys(job.value?.stats?.products || {}))
const totalText = computed(() => {
  const t = job.value?.stats?.['合计']
  if (!t) return ''
  return Object.entries(t).map(([k, v]) => `${k} ${v}`).join('，')
})

function onFiles(kind, files) {
  fileList.value[kind] = files
}

function addGroup() {
  dbGroups.value.push({ product: '', system_template_id: null, valuation_template_id: null })
}

async function loadTemplates() {
  tplLoading.value = true
  try {
    const [sys, val] = await Promise.all([
      api.get('/query-templates', { params: { module: 'm2_system' } }),
      api.get('/query-templates', { params: { module: 'm2_valuation' } }),
    ])
    templates.m2_system = sys.data
    templates.m2_valuation = val.data
  } catch {
    templates.m2_system = []
    templates.m2_valuation = []
  } finally {
    tplLoading.value = false
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
      const groups = dbGroups.value.map((g) => ({
        ...((g.product || '').trim() ? { product: g.product.trim() } : {}),
        system_template_id: g.system_template_id,
        valuation_template_id: g.valuation_template_id,
      }))
      fd.append('fetch_mode', 'db')
      fd.append('groups_json', JSON.stringify(groups))
      fd.append('biz_date', bizDate.value)
    } else {
      for (const f of fileList.value.system) fd.append('system_files', f.raw)
      for (const f of fileList.value.valuation) fd.append('valuation_files', f.raw)
      if (bizDate.value) fd.append('biz_date', bizDate.value)
    }
    const resp = await api.post('/recon/m2/jobs', fd)
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
    if (s === 'success' || s === 'failed') {
      phase.value = 'done'
      activeProduct.value = productList.value[0] || ''
    }
    await nextTick()
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  },
)

function download(product) {
  downloadFile(`/recon/jobs/${job.value.job_id}/download?product=${product}`)
}

function reset() {
  fileList.value = { system: [], valuation: [] }
  dbGroups.value = [{ product: '', system_template_id: null, valuation_template_id: null }]
  bizDate.value = ''
  phase.value = 'upload'
}

onMounted(loadTemplates)
</script>

<style scoped>
.pair-table { width: 100%; }
.pair-warn { margin-top: 8px; color: #b7791f; font-size: 12px; }
.submit-hint { margin-left: 12px; color: #909399; font-size: 12px; }
.db-group-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.grp-product { width: 260px; }
.grp-tpl { width: 340px; }
.db-summary { margin: 0 0 18px 130px; }
.db-summary-line { font-size: 12px; color: #606266; line-height: 1.7; word-break: break-all; }
.log-box {
  margin-top: 16px; height: 320px; overflow-y: auto;
  background: #1e1e1e; color: #d4d4d4; padding: 12px;
  border-radius: 4px; font-family: Consolas, monospace; font-size: 12px;
}
.log-line { white-space: pre-wrap; line-height: 1.6; }
.result-header { display: flex; justify-content: space-between; align-items: center; }
.stat-box { text-align: center; padding: 14px 0; background: #f7f9fc; border-radius: 6px; }
.stat-box.warn { background: #fdf6ec; }
.stat-num { font-size: 22px; font-weight: 700; color: #2c5282; }
.stat-box.warn .stat-num { color: #b7791f; }
.stat-name { font-size: 12px; color: #909399; margin-top: 4px; }
.download-row { margin-top: 16px; }
.color-legend { margin-top: 12px; display: flex; gap: 8px; }
.error-bar { margin-bottom: 16px; }
.error-text { white-space: pre-wrap; margin: 8px 0 0; font-size: 13px; }
</style>
