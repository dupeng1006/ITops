<template>
  <div>
    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="模块">
          <el-select v-model="filters.module" clearable placeholder="全部" style="width: 110px">
            <el-option label="M1" value="M1" />
            <el-option label="M3" value="M3" />
          </el-select>
        </el-form-item>
        <el-form-item label="业务日期">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYYMMDD"
                          start-placeholder="开始" end-placeholder="结束" style="width: 260px" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 110px">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="执行中" value="running" />
            <el-option label="排队中" value="pending" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="load(1)">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="module" label="模块" width="70" />
        <el-table-column prop="biz_date" label="业务日期" width="105" />
        <el-table-column label="状态" width="85">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusName(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="统计摘要" min-width="300">
          <template #default="{ row }">{{ statsSummary(row) }}</template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="90" />
        <el-table-column prop="created_at" label="创建时间" width="155" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="showDetail(row)">详情</el-button>
            <el-button v-if="row.status === 'success' && canDownload" text type="primary" size="small" @click="download(row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination class="pager" layout="total, prev, pager, next" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="load" />
    </el-card>

    <el-dialog v-model="detailVisible" :title="`任务详情（${detail?.job_id || ''}）`" width="720px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="模块">{{ detail.module }}</el-descriptions-item>
          <el-descriptions-item label="业务日期">{{ detail.biz_date }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(detail.status)" size="small">{{ statusName(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建人">{{ detail.created_by }}</el-descriptions-item>
          <el-descriptions-item label="结果文件" :span="2">{{ detail.result_filename || '—' }}</el-descriptions-item>
          <el-descriptions-item label="统计摘要" :span="2">
            <pre class="kv">{{ JSON.stringify(detail.stats, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.error" label="错误信息" :span="2">
            <pre class="kv error">{{ detail.error }}</pre>
          </el-descriptions-item>
        </el-descriptions>
        <div class="log-title">运行日志（尾部）</div>
        <div class="log-box">
          <div v-for="(line, i) in detail.log_tail" :key="i" class="log-line">{{ line }}</div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import api, { downloadFile } from '../api'
import { getUser } from '../utils/auth'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const dateRange = ref([])
const filters = reactive({ module: '', status: '' })
const detailVisible = ref(false)
const detail = ref(null)

const canDownload = computed(() => ['admin', 'operator'].includes(getUser()?.role))

function statusType(s) {
  return { success: 'success', failed: 'danger', running: 'warning', pending: 'info' }[s] || 'info'
}
function statusName(s) {
  return { success: '成功', failed: '失败', running: '执行中', pending: '排队中' }[s] || s
}
function statsSummary(row) {
  if (row.status === 'failed') return row.error ? String(row.error).split('\n')[0] : '执行失败'
  if (!row.stats) return '—'
  return Object.entries(row.stats).map(([k, v]) => `${k} ${v}`).join('，')
}

async function load(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize }
    if (filters.module) params.module = filters.module
    if (filters.status) params.status = filters.status
    if (dateRange.value?.length === 2) {
      params.date_from = dateRange.value[0]
      params.date_to = dateRange.value[1]
    }
    const resp = await api.get('/recon/jobs', { params })
    rows.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function showDetail(row) {
  const resp = await api.get(`/recon/jobs/${row.job_id}`, { params: { log_tail: 100 } })
  detail.value = resp.data
  detailVisible.value = true
}

function download(row) {
  downloadFile(`/recon/jobs/${row.job_id}/download`, row.result_filename || 'result.xlsx')
}

onMounted(() => load(1))
</script>

<style scoped>
.pager { margin-top: 16px; justify-content: flex-end; }
.kv { margin: 0; white-space: pre-wrap; font-size: 12px; }
.kv.error { color: #c53030; }
.log-title { margin: 14px 0 6px; font-weight: 600; }
.log-box {
  height: 260px; overflow-y: auto; background: #1e1e1e; color: #d4d4d4;
  padding: 12px; border-radius: 4px; font-family: Consolas, monospace; font-size: 12px;
}
.log-line { white-space: pre-wrap; line-height: 1.6; }
</style>
