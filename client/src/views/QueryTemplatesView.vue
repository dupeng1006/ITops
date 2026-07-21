<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>查询模板（SQL 保存时经只读白名单校验，执行前二次校验；预览仅返回前 50 行）</span>
          <el-button type="primary" :icon="Plus" @click="openForm()">新增模板</el-button>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="模板名称" min-width="160" />
        <el-table-column label="所属模块" width="130">
          <template #default="{ row }">{{ moduleLabel(row.module) }}</template>
        </el-table-column>
        <el-table-column prop="ds_name" label="数据源" min-width="140" />
        <el-table-column label="参数" width="120">
          <template #default="{ row }">{{ paramNames(row) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="updated_by" label="修改人" width="100" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openPreview(row)">预览</el-button>
            <el-button text type="primary" size="small" @click="openForm(row)">编辑</el-button>
            <el-popconfirm title="确认删除该模板？" @confirm="del(row)">
              <template #reference><el-button text type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑模板' : '新增模板'" width="760px" top="4vh">
      <el-form label-width="110px">
        <el-form-item label="模板名称" required>
          <el-input v-model="form.name" placeholder="如：多账套净值查询" />
        </el-form-item>
        <el-form-item label="所属模块" required>
          <el-select v-model="form.module" style="width: 100%">
            <el-option v-for="m in modules" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据源" required>
          <el-select v-model="form.ds_id" style="width: 100%">
            <el-option v-for="d in datasources" :key="d.id" :label="`${d.name}（${d.db_type}）`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="查询 SQL" required>
          <el-input v-model="form.sql_text" type="textarea" :rows="7"
                    placeholder="仅允许单条 SELECT / WITH 查询；参数用 :参数名 绑定（如 :biz_date）"
                    class="sql-input" />
        </el-form-item>

        <el-form-item label="字段映射">
          <div class="kv-block">
            <div v-for="(item, idx) in form.columnMapList" :key="idx" class="kv-row">
              <el-input v-model="item.db_col" placeholder="结果列名（如 FUND_CODE）" class="kv-key" />
              <span class="kv-arrow">→</span>
              <el-input v-model="item.logic_field" placeholder="标准逻辑字段（如 product_code）" class="kv-val" />
              <el-button text type="danger" size="small" @click="form.columnMapList.splice(idx, 1)">删除</el-button>
            </div>
            <el-button text type="primary" size="small" :icon="Plus"
                       @click="form.columnMapList.push({ db_col: '', logic_field: '' })">添加映射</el-button>
          </div>
        </el-form-item>

        <el-form-item label="参数定义">
          <div class="kv-block">
            <div v-for="(item, idx) in form.paramsList" :key="idx" class="kv-row">
              <el-input v-model="item.name" placeholder="参数名（如 biz_date）" class="kv-key" />
              <el-select v-model="item.type" class="kv-type">
                <el-option label="日期" value="date" />
                <el-option label="字符串" value="string" />
                <el-option label="整数" value="integer" />
                <el-option label="数值" value="number" />
              </el-select>
              <el-input v-model="item.label" placeholder="中文名（如 业务日期）" class="kv-val" />
              <el-checkbox v-model="item.required">必填</el-checkbox>
              <el-button text type="danger" size="small" @click="form.paramsList.splice(idx, 1)">删除</el-button>
            </div>
            <el-button text type="primary" size="small" :icon="Plus"
                       @click="form.paramsList.push({ name: '', type: 'date', label: '', required: true })">添加参数</el-button>
          </div>
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewVisible" :title="`预览：${previewTpl?.name || ''}`" width="900px" top="4vh">
      <div class="preview-params">
        <template v-if="previewParamList.length">
          <div v-for="p in previewParamList" :key="p.name" class="preview-param-item">
            <span class="preview-param-label">{{ p.label || p.name }}（{{ p.name }}）{{ p.required ? ' *' : '' }}</span>
            <el-input v-model="previewParams[p.name]"
                      :placeholder="p.type === 'date' ? 'yyyyMMdd 或 yyyy-MM-dd' : p.type" />
          </div>
        </template>
        <el-button type="primary" :loading="previewing" @click="runPreview">执行预览</el-button>
      </div>
      <template v-if="previewResult">
        <el-alert type="info" :closable="false" class="preview-meta">
          返回 {{ previewResult.rows_returned }} 行（预览上限 50 行），耗时 {{ previewResult.elapsed_ms }}ms；
          执行保护：{{ previewResult.protections.join('；') }}
        </el-alert>
        <el-table :data="previewResult.rows" stripe size="small" max-height="420" class="preview-table">
          <el-table-column v-for="col in previewResult.columns" :key="col" :prop="col" :label="col"
                           min-width="120" show-overflow-tooltip />
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'

const modules = [
  { value: 'm1_fund', label: 'M1 基金资产表' },
  { value: 'm1_netvalue', label: 'M1 净值查询表' },
  { value: 'm2_system', label: 'M2 新综合信息查询' },
  { value: 'm2_valuation', label: 'M2 估值表' },
  { value: 'm3_member', label: 'M3 交易成员信息' },
  { value: 'custom', label: '自定义（数据字典生成）' },
]

const rows = ref([])
const datasources = ref([])
const loading = ref(false)
const saving = ref(false)
const formVisible = ref(false)
const emptyForm = {
  id: null, name: '', module: 'm1_fund', ds_id: null, sql_text: '',
  columnMapList: [], paramsList: [], enabled: true,
}
const form = reactive(JSON.parse(JSON.stringify(emptyForm)))

const previewVisible = ref(false)
const previewTpl = ref(null)
const previewParamList = ref([])
const previewParams = reactive({})
const previewing = ref(false)
const previewResult = ref(null)

function moduleLabel(v) {
  return (modules.find((m) => m.value === v) || {}).label || v
}

function paramNames(row) {
  const def = row.params_def || {}
  const names = Object.keys(def)
  return names.length ? names.join(', ') : '（无）'
}

async function load() {
  loading.value = true
  try {
    const [tplResp, dsResp] = await Promise.all([
      api.get('/query-templates'),
      api.get('/datasources'),
    ])
    rows.value = tplResp.data
    datasources.value = dsResp.data
  } finally {
    loading.value = false
  }
}

function openForm(row) {
  Object.keys(form).forEach((k) => delete form[k])
  Object.assign(form, JSON.parse(JSON.stringify(emptyForm)))
  if (row) {
    form.id = row.id
    form.name = row.name
    form.module = row.module
    form.ds_id = row.ds_id
    form.sql_text = row.sql_text
    form.enabled = row.enabled
    form.columnMapList = Object.entries(row.column_map || {}).map(([db_col, logic_field]) => ({ db_col, logic_field }))
    form.paramsList = Object.entries(row.params_def || {}).map(([name, spec]) => ({
      name, type: spec.type || 'string', label: spec.label || '', required: !!spec.required,
    }))
  }
  formVisible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写模板名称')
  if (!form.ds_id) return ElMessage.warning('请选择数据源')
  if (!form.sql_text.trim()) return ElMessage.warning('请填写查询 SQL')

  const columnMap = {}
  for (const item of form.columnMapList) {
    if (item.db_col.trim() && item.logic_field.trim()) columnMap[item.db_col.trim()] = item.logic_field.trim()
  }
  const paramsDef = {}
  for (const item of form.paramsList) {
    if (!item.name.trim()) continue
    paramsDef[item.name.trim()] = { type: item.type, label: item.label.trim() || item.name.trim(), required: item.required }
  }

  saving.value = true
  try {
    const payload = {
      name: form.name.trim(), module: form.module, ds_id: form.ds_id,
      sql_text: form.sql_text, column_map: columnMap, params_def: paramsDef, enabled: form.enabled,
    }
    if (form.id) {
      await api.put(`/query-templates/${form.id}`, payload)
      ElMessage.success('模板已更新')
    } else {
      await api.post('/query-templates', payload)
      ElMessage.success('模板已创建')
    }
    formVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row, v) {
  await api.put(`/query-templates/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
  await load()
}

function openPreview(row) {
  previewTpl.value = row
  previewResult.value = null
  previewParamList.value = Object.entries(row.params_def || {}).map(([name, spec]) => ({
    name, type: spec.type || 'string', label: spec.label || name, required: !!spec.required,
  }))
  Object.keys(previewParams).forEach((k) => delete previewParams[k])
  previewParamList.value.forEach((p) => { previewParams[p.name] = '' })
  previewVisible.value = true
}

async function runPreview() {
  for (const p of previewParamList.value) {
    if (p.required && !String(previewParams[p.name] || '').trim()) {
      return ElMessage.warning(`请填写必填参数：${p.label}（${p.name}）`)
    }
  }
  previewing.value = true
  try {
    const params = {}
    Object.entries(previewParams).forEach(([k, v]) => {
      if (String(v || '').trim()) params[k] = String(v).trim()
    })
    const resp = await api.post(`/query-templates/${previewTpl.value.id}/preview`, { params })
    previewResult.value = resp.data
  } catch {
    previewResult.value = null  // 错误信息已由拦截器统一提示
  } finally {
    previewing.value = false
  }
}

async function del(row) {
  await api.delete(`/query-templates/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.header-row { display: flex; align-items: center; justify-content: space-between; }
.sql-input :deep(textarea) { font-family: Consolas, 'Courier New', monospace; font-size: 13px; }
.kv-block { width: 100%; }
.kv-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.kv-key { width: 220px; }
.kv-val { width: 220px; }
.kv-type { width: 100px; }
.kv-arrow { color: #909399; }
.preview-params { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
.preview-param-item { display: flex; flex-direction: column; gap: 4px; width: 240px; }
.preview-param-label { font-size: 12px; color: #606266; }
.preview-meta { margin-bottom: 10px; }
.preview-table { width: 100%; }
</style>
