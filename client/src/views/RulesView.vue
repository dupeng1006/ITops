<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>规则配置（修改即时热生效，新任务按新规则执行；全部修改留痕审计）</span>
          <div>
            <el-button :icon="Download" @click="onExport">导出配置</el-button>
            <el-button type="primary" :icon="Upload" @click="importVisible = true">导入配置</el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="tab">
        <!-- 映射规则 -->
        <el-tab-pane label="映射规则" name="mappings">
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openMapping()">新增映射</el-button>
          </div>
          <el-table :data="mappings" v-loading="loading.mappings" stripe>
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="source_code" label="原代码" width="140" />
            <el-table-column prop="target_code" label="映射后代码" width="140" />
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(v) => toggleMapping(row, v)" />
              </template>
            </el-table-column>
            <el-table-column label="修改人" width="110">
              <template #default="{ row }">{{ fmtUpdater(row) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="修改时间" width="160" />
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="openMapping(row)">编辑</el-button>
                <el-popconfirm title="确认删除该映射？" @confirm="delMapping(row)">
                  <template #reference><el-button text type="danger" size="small">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 特殊产品 -->
        <el-tab-pane label="特殊产品清单" name="bulk">
          <el-alert type="info" :closable="false" class="bulk-alert">
            特殊产品不参与差异超阈值统计；差异说明与颜色将体现在 M1 核对结果 Excel 的『差异原因』列与行填充色中；不填差异说明时默认显示「大宗产品无需核对」，默认颜色为橙色。
          </el-alert>
          <div class="tab-bar">
            <el-button type="primary" :icon="Plus" @click="openBulk()">新增特殊产品</el-button>
          </div>
          <el-table :data="bulks" v-loading="loading.bulk" stripe>
            <el-table-column prop="product_code" label="产品代码" width="140" />
            <el-table-column label="差异说明" min-width="220">
              <template #default="{ row }">
                <span v-if="row.note">{{ row.note }}</span>
                <span v-else class="note-default">（默认）大宗产品无需核对</span>
              </template>
            </el-table-column>
            <el-table-column label="颜色" width="150">
              <template #default="{ row }">
                <span class="color-cell">
                  <span class="color-block" :style="{ background: '#' + (row.color || DEFAULT_COLOR) }"></span>
                  <span>#{{ (row.color || DEFAULT_COLOR).toUpperCase() }}</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(v) => toggleBulk(row, v)" />
              </template>
            </el-table-column>
            <el-table-column label="修改人" width="110">
              <template #default="{ row }">{{ fmtUpdater(row) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="修改时间" width="160" />
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="openBulk(row)">编辑</el-button>
                <el-popconfirm title="确认删除该特殊产品？" @confirm="delBulk(row)">
                  <template #reference><el-button text type="danger" size="small">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 阈值 -->
        <el-tab-pane label="阈值参数" name="thresholds">
          <el-table :data="thresholds" v-loading="loading.thresholds" stripe>
            <el-table-column prop="param_key" label="参数键" width="140" />
            <el-table-column prop="param_value" label="当前值" width="120" />
            <el-table-column prop="description" label="说明" min-width="240" />
            <el-table-column label="合法范围" width="140">
              <template #default="{ row }">{{ rangeText(row.param_key) }}</template>
            </el-table-column>
            <el-table-column label="修改人" width="110">
              <template #default="{ row }">{{ fmtUpdater(row) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="修改时间" width="160" />
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button text type="primary" size="small" @click="openThreshold(row)">修改</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 映射编辑弹窗 -->
    <el-dialog v-model="mappingVisible" :title="mappingForm.id ? '编辑映射' : '新增映射'" width="420px">
      <el-form label-width="100px">
        <el-form-item label="原代码" required>
          <el-input v-model="mappingForm.source_code" placeholder="净值查询表侧代码" />
        </el-form-item>
        <el-form-item label="映射后代码" required>
          <el-input v-model="mappingForm.target_code" placeholder="基金资产表侧代码" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="mappingForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mappingVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMapping">保存</el-button>
      </template>
    </el-dialog>

    <!-- 特殊产品编辑弹窗 -->
    <el-dialog v-model="bulkVisible" :title="bulkForm.id ? '编辑特殊产品' : '新增特殊产品'" width="460px">
      <el-form label-width="100px">
        <el-form-item label="产品代码" required>
          <el-input v-model="bulkForm.product_code" placeholder="必填" />
        </el-form-item>
        <el-form-item label="差异说明">
          <el-input
            v-model="bulkForm.note"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="留空则默认：大宗产品无需核对"
          />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="bulkForm.color" />
          <span class="color-tip">默认 #FFC000（橙色），用于 Excel 行填充色</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="bulkForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bulkVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBulk">保存</el-button>
      </template>
    </el-dialog>

    <!-- 阈值编辑弹窗 -->
    <el-dialog v-model="thresholdVisible" :title="`修改阈值 ${thresholdForm.param_key}`" width="420px">
      <el-form label-width="100px">
        <el-form-item :label="thresholdForm.param_key" required>
          <el-input-number v-model="thresholdForm.value" :precision="6" :step="0.1" style="width: 200px" />
        </el-form-item>
        <div class="range-tip">合法范围：{{ rangeText(thresholdForm.param_key) }}（越界将被服务端拒绝）</div>
      </el-form>
      <template #footer>
        <el-button @click="thresholdVisible = false">取消</el-button>
        <el-button type="primary" @click="saveThreshold">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入弹窗 -->
    <el-dialog v-model="importVisible" title="导入规则配置" width="520px">
      <el-alert type="warning" :closable="false" class="import-alert">
        导入将<strong>整体替换</strong>现有映射规则与特殊产品清单（与核对小程序 config JSON 同构）。
        操作记录审计日志，请先确认文件内容无误。
      </el-alert>
      <el-upload drag :auto-upload="false" :limit="1" accept=".json" :on-change="onImportFile" class="import-upload">
        <el-icon size="40"><UploadFilled /></el-icon>
        <div class="el-upload__text">选择小程序配置文件（fund_reconciler_config.json）</div>
      </el-upload>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="danger" :disabled="!importData" @click="onImport">确认整体替换</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Download, Upload, UploadFilled } from '@element-plus/icons-vue'
import api, { downloadFile } from '../api'
import { fmtUpdater } from '../utils/display'

const tab = ref('mappings')
const mappings = ref([])
const bulks = ref([])
const thresholds = ref([])
const loading = reactive({ mappings: false, bulk: false, thresholds: false })

const RANGES = { diff_pct: '0.01 ~ 100', fuzzy_sim: '0 ~ 1', price_tol: '0 ~ 1' }
function rangeText(key) {
  return RANGES[key] || '—'
}

async function loadAll() {
  loading.mappings = loading.bulk = loading.thresholds = true
  try {
    const [m, b, t] = await Promise.all([
      api.get('/rules/mappings'),
      api.get('/rules/bulk-products'),
      api.get('/rules/thresholds'),
    ])
    mappings.value = m.data
    bulks.value = b.data
    thresholds.value = t.data
  } finally {
    loading.mappings = loading.bulk = loading.thresholds = false
  }
}

/* ---- 映射 ---- */
const mappingVisible = ref(false)
const mappingForm = reactive({ id: null, source_code: '', target_code: '', enabled: true })

function openMapping(row) {
  Object.assign(mappingForm, row
    ? { id: row.id, source_code: row.source_code, target_code: row.target_code, enabled: row.enabled }
    : { id: null, source_code: '', target_code: '', enabled: true })
  mappingVisible.value = true
}

async function saveMapping() {
  if (!mappingForm.source_code.trim() || !mappingForm.target_code.trim()) {
    ElMessage.warning('原代码与映射后代码均不能为空')
    return
  }
  if (mappingForm.id) {
    await api.put(`/rules/mappings/${mappingForm.id}`, mappingForm)
  } else {
    await api.post('/rules/mappings', mappingForm)
  }
  ElMessage.success('已保存')
  mappingVisible.value = false
  loadAll()
}

async function toggleMapping(row, v) {
  await api.put(`/rules/mappings/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
  loadAll()
}

async function delMapping(row) {
  await api.delete(`/rules/mappings/${row.id}`)
  ElMessage.success('已删除')
  loadAll()
}

/* ---- 特殊产品 ---- */
const DEFAULT_COLOR = 'FFC000'
const HEX_RE = /^[0-9A-Fa-f]{6}$/
const bulkVisible = ref(false)
const bulkForm = reactive({ id: null, product_code: '', note: '', color: '#FFC000', enabled: true })

function openBulk(row) {
  Object.assign(bulkForm, row
    ? {
        id: row.id,
        product_code: row.product_code,
        note: row.note || '',
        color: '#' + (row.color || DEFAULT_COLOR),
        enabled: row.enabled,
      }
    : { id: null, product_code: '', note: '', color: '#FFC000', enabled: true })
  bulkVisible.value = true
}

async function saveBulk() {
  if (!bulkForm.product_code.trim()) {
    ElMessage.warning('产品代码不能为空')
    return
  }
  // el-color-picker 返回值形如 #ffc000；提交时去掉 # 并转大写
  const color = (bulkForm.color || '').replace(/^#/, '').toUpperCase()
  if (!HEX_RE.test(color)) {
    ElMessage.warning('颜色须为6位十六进制（不含#），如 FFC000')
    return
  }
  const payload = {
    product_code: bulkForm.product_code.trim(),
    note: bulkForm.note.trim() || null,
    color,
    enabled: bulkForm.enabled,
  }
  if (bulkForm.id) {
    await api.put(`/rules/bulk-products/${bulkForm.id}`, payload)
  } else {
    await api.post('/rules/bulk-products', payload)
  }
  ElMessage.success('已保存')
  bulkVisible.value = false
  loadAll()
}

async function toggleBulk(row, v) {
  await api.put(`/rules/bulk-products/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
  loadAll()
}

async function delBulk(row) {
  await api.delete(`/rules/bulk-products/${row.id}`)
  ElMessage.success('已删除')
  loadAll()
}

/* ---- 阈值 ---- */
const thresholdVisible = ref(false)
const thresholdForm = reactive({ param_key: '', value: 0 })

function openThreshold(row) {
  thresholdForm.param_key = row.param_key
  thresholdForm.value = parseFloat(row.param_value)
  thresholdVisible.value = true
}

async function saveThreshold() {
  await api.put(`/rules/thresholds/${thresholdForm.param_key}`, { value: thresholdForm.value })
  ElMessage.success('已保存')
  thresholdVisible.value = false
  loadAll()
}

/* ---- 导入导出 ---- */
const importVisible = ref(false)
const importData = ref(null)

function onExport() {
  downloadFile('/rules/export', 'fund_reconciler_config.json')
}

function onImportFile(uploadFile) {
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result)
      if (!data.rename_map || !Array.isArray(data.bulk_products)) {
        ElMessage.error('文件结构不符：需含 rename_map（对象）与 bulk_products（数组）')
        importData.value = null
        return
      }
      importData.value = data
      ElMessage.success(`文件解析成功：映射 ${Object.keys(data.rename_map).length} 条，特殊产品 ${data.bulk_products.length} 个`)
    } catch {
      ElMessage.error('JSON 解析失败，请确认文件格式')
      importData.value = null
    }
  }
  reader.readAsText(uploadFile.raw)
}

async function onImport() {
  await ElMessageBox.confirm(
    `即将整体替换：映射 ${Object.keys(importData.value.rename_map).length} 条、特殊产品 ${importData.value.bulk_products.length} 个。确认继续？`,
    '整体替换确认',
    { type: 'warning', confirmButtonText: '确认替换', cancelButtonText: '取消' },
  )
  const resp = await api.post('/rules/import', importData.value)
  ElMessage.success(resp.data.message || '导入完成')
  importVisible.value = false
  importData.value = null
  loadAll()
}

onMounted(loadAll)
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
.tab-bar { margin-bottom: 12px; }
.range-tip { color: #909399; font-size: 12px; margin-left: 100px; }
.import-alert { margin-bottom: 12px; }
.import-upload { width: 100%; }
.bulk-alert { margin-bottom: 12px; }
.note-default { color: #909399; }
.color-cell { display: inline-flex; align-items: center; gap: 6px; }
.color-block { display: inline-block; width: 16px; height: 16px; border-radius: 3px; border: 1px solid #dcdfe6; }
.color-tip { margin-left: 10px; color: #909399; font-size: 12px; }
</style>
