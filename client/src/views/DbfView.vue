<template>
  <div>
    <!-- DBF 数据查看：纯只读解析 dBase/FoxPro .dbf，不修改原文件，操作留痕审计 -->
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>DBF 数据查看（上传 dBase / FoxPro 格式文件，按文件内容识别，不限扩展名——中登 .713 等日期后缀文件可直接上传；纯只读，不修改原文件）</span>
          <el-button v-if="meta" type="primary" :loading="exporting" @click="doExport">导出 Excel</el-button>
        </div>
      </template>

      <div class="pick-row">
        <input ref="fileInput" type="file" accept=".dbf,*.*" class="file-input" @change="onPick" />
        <el-button type="primary" :disabled="!dbfFile" :loading="loading" @click="doPreview">
          {{ loading ? '解析中…' : '解析查看' }}
        </el-button>
        <el-button v-if="meta" text type="danger" @click="reset">清除结果</el-button>
      </div>

      <template v-if="meta">
        <el-descriptions :column="4" border class="meta-table">
          <el-descriptions-item label="文件">{{ meta.filename }}</el-descriptions-item>
          <el-descriptions-item label="字段数">{{ meta.field_count }}</el-descriptions-item>
          <el-descriptions-item label="总记录数">{{ meta.total_rows }}</el-descriptions-item>
          <el-descriptions-item label="字符编码">{{ meta.encoding }}</el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="meta.garbled_warning" type="warning" :closable="false" class="tip-bar">
          <template #title>未能按 GBK/UTF-8 解码，已按单字节编码兜底，中文可能显示为乱码——请确认文件来源编码。</template>
        </el-alert>
        <el-alert v-if="meta.truncated" type="info" :closable="false" class="tip-bar">
          <template #title>记录较多，页面仅展示前 {{ meta.preview_rows }} 行；全量数据请点「导出 Excel」。</template>
        </el-alert>

        <el-alert v-if="meta.spec" type="success" :closable="false" class="tip-bar">
          <template #title>
            <b>接口自动匹配</b>：{{ meta.spec.code }}（{{ meta.spec.name }}）
            ｜规范来源：{{ meta.spec.spec_name }}
            <template v-if="meta.spec.file_pattern">｜官方命名约定：{{ meta.spec.file_pattern }}</template>
            ｜字段说明覆盖 {{ meta.spec.matched_fields }}/{{ meta.spec.total_spec_fields }}
            （表头蓝色文字为官方字段说明，悬停可见完整内容）
          </template>
        </el-alert>

        <el-table :data="pageRows" stripe border size="small" class="data-table" v-loading="loading">
          <el-table-column type="index" label="#" width="55" :index="(i) => (page - 1) * pageSize + i + 1" />
          <el-table-column v-for="f in meta.fields" :key="f.name" :prop="f.name" min-width="110"
                           show-overflow-tooltip>
            <template #header>
              <div class="col-head" :title="specDesc(f.name) || ''">
                <span>{{ f.name }}</span>
                <span v-if="specDesc(f.name)" class="col-cn">{{ specDesc(f.name) }}</span>
                <span class="col-type">{{ f.type_name }}{{ f.type === 'N' || f.type === 'F' ? `(${f.length},${f.decimal})` : f.type === 'C' ? `(${f.length})` : '' }}</span>
              </div>
            </template>
            <template #default="{ row }">{{ row[f.name] ?? '' }}</template>
          </el-table-column>
        </el-table>

        <el-pagination v-if="meta.preview_rows > 0" class="pager" background
                       layout="total, sizes, prev, pager, next, jumper"
                       :total="meta.preview_rows" v-model:current-page="page"
                       v-model:page-size="pageSize" :page-sizes="[20, 50, 100, 200]" />
      </template>

      <el-empty v-else-if="!loading" description="请选择 DBF 格式文件（按内容识别，不限扩展名）并点击「解析查看」" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const fileInput = ref(null)
const dbfFile = ref(null)
const meta = ref(null)
const loading = ref(false)
const exporting = ref(false)
const page = ref(1)
const pageSize = ref(50)

const pageRows = computed(() => {
  if (!meta.value) return []
  const start = (page.value - 1) * pageSize.value
  return meta.value.rows.slice(start, start + pageSize.value)
})

// 中登接口官方字段说明（匹配成功时显示在表头字段名下方）
function specDesc(fieldName) {
  const sp = meta.value && meta.value.spec
  if (!sp || !sp.fields) return ''
  const f = sp.fields[fieldName]
  return f ? (f.desc || '') : ''
}

function onPick(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  dbfFile.value = f
}

async function doPreview() {
  loading.value = true
  meta.value = null
  try {
    const fd = new FormData()
    fd.append('file', dbfFile.value)
    const resp = await api.post('/dbf/preview', fd, { timeout: 300000 })
    meta.value = resp.data.data || resp.data
    page.value = 1
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function doExport() {
  exporting.value = true
  try {
    const fd = new FormData()
    fd.append('file', dbfFile.value)
    const resp = await api.post('/dbf/export', fd, { responseType: 'blob', timeout: 600000 })
    const disposition = resp.headers['content-disposition'] || ''
    const m = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    const name = m ? decodeURIComponent(m[1]) : 'export.xlsx'
    const url = URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url; a.download = name; a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 ' + name)
  } catch { /* 拦截器已提示 */ } finally {
    exporting.value = false
  }
}

function reset() {
  meta.value = null
  dbfFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
.pick-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.file-input { font-size: 14px; }
.meta-table { margin-bottom: 10px; }
.tip-bar { margin: 8px 0; }
.data-table { margin-top: 8px; }
.col-head { display: flex; flex-direction: column; line-height: 1.3; }
.col-cn { font-size: 12px; color: #005EB8; font-weight: 600; }
.col-type { font-size: 11px; color: #909399; font-weight: normal; }
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
