<template>
  <div>
    <!-- 新建任务 -->
    <el-card v-if="phase === 'upload'" shadow="never">
      <template #header><span>新建 M3 银行间ID匹配任务</span></template>
      <el-form label-width="130px">
        <el-form-item label="基金属性表" required>
          <el-upload drag :auto-upload="false" :limit="1" accept=".xls,.xlsx"
                     :on-change="(f) => onFile('fund', f)" :on-remove="() => (files.fund = null)">
            <el-icon size="40"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em>（.xls/.xlsx）</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="交易成员信息表" required>
          <el-upload drag :auto-upload="false" :limit="1" accept=".csv"
                     :on-change="(f) => onFile('member', f)" :on-remove="() => (files.member = null)">
            <el-icon size="40"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em>（.csv，GBK 编码）</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="业务日期">
          <el-date-picker v-model="bizDate" type="date" value-format="YYYYMMDD" placeholder="默认当天" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" :disabled="!files.fund || !files.member" :loading="submitting" @click="submit">
            开始匹配
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
            <span>匹配结果（统计：{{ statsText }}）</span>
            <el-button @click="reset">新建任务</el-button>
          </div>
        </template>
        <el-row :gutter="12">
          <el-col :span="6" v-for="(v, k) in job.stats" :key="k">
            <div class="stat-box" :class="k === '未匹配' && v > 0 ? 'warn' : ''">
              <div class="stat-num">{{ v }}</div>
              <div class="stat-name">{{ k }}</div>
            </div>
          </el-col>
        </el-row>
        <div class="download-row">
          <el-button type="primary" @click="download('updated')">下载更新表</el-button>
          <el-button @click="download('detail')">下载结果明细</el-button>
          <el-button @click="download('note')">下载匹配说明</el-button>
        </div>
        <div class="color-legend">
          <el-tag type="primary" effect="dark" color="#bdd7ee" style="color:#1f2d3d">蓝：有变动</el-tag>
          <el-tag type="success" effect="dark" color="#c6efce" style="color:#1f2d3d">绿：无变化</el-tag>
          <el-tag type="danger" effect="dark" color="#ffc7ce" style="color:#1f2d3d">红：未匹配</el-tag>
        </div>
      </el-card>
      <el-button v-if="job.status === 'failed'" type="primary" @click="reset">重新上传</el-button>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import api, { downloadFile } from '../api'
import { useJobPolling } from '../utils/useJobPolling'

const phase = ref('upload')
const files = reactive({ fund: null, member: null })
const bizDate = ref('')
const submitting = ref(false)
const logBox = ref(null)

const { job, start } = useJobPolling(2000)

const statsText = computed(() => {
  if (!job.value?.stats) return ''
  return Object.entries(job.value.stats).map(([k, v]) => `${k} ${v}`).join('，')
})

function onFile(kind, uploadFile) {
  files[kind] = uploadFile.raw
}

async function submit() {
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('fund_file', files.fund)
    fd.append('member_file', files.member)
    if (bizDate.value) fd.append('biz_date', bizDate.value)
    const resp = await api.post('/recon/m3/jobs', fd)
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

function download(kind) {
  downloadFile(`/recon/jobs/${job.value.job_id}/download?file=${kind}`)
}

function reset() {
  files.fund = null
  files.member = null
  bizDate.value = ''
  phase.value = 'upload'
}
</script>

<style scoped>
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
