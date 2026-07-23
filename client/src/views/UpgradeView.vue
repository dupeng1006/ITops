<template>
  <div>
    <!-- 在线升级：数据（账号/规则/配置/历史/归档）全部在后台数据库与固定数据目录，
         升级仅替换程序，全程无需人工执行脚本 -->
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>版本升级（上传官方部署包 zip，系统自动完成：备份数据 → 替换程序 → 自动重启，数据完整保留）</span>
          <el-tag v-if="info.version" type="info" size="large">当前版本 v{{ info.version }}</el-tag>
        </div>
      </template>

      <el-descriptions :column="1" border class="info-table">
        <el-descriptions-item label="当前版本">v{{ info.version || '读取中…' }}</el-descriptions-item>
        <el-descriptions-item label="安装目录">{{ info.install_root || '—' }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ info.data_dir || '—' }}（升级不触碰）</el-descriptions-item>
        <el-descriptions-item label="归档目录">{{ info.archive_dir || '—' }}（升级不触碰）</el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="info.frozen === false" type="warning" :closable="false" class="tip-bar">
        <template #title>当前为源码运行环境，在线升级仅对部署版（exe）开放。</template>
      </el-alert>

      <template v-else>
        <el-divider content-position="left">选择新版部署包</el-divider>
        <div class="pick-row">
          <input ref="fileInput" type="file" accept=".zip" class="file-input" @change="onPick" />
          <div v-if="pkg" class="pkg-info">
            <el-icon><Document /></el-icon>
            <span class="pkg-name">{{ pkg.name }}</span>
            <span class="pkg-size">（{{ fmtSize(pkg.size) }}）</span>
            <el-button text type="danger" size="small" @click="clearPick">移除</el-button>
          </div>
        </div>

        <el-alert type="info" :closable="false" class="tip-bar">
          <template #title>
            升级期间服务将自动重启约 10~30 秒，期间页面短暂不可访问；
            账号、规则、特殊产品清单、模板、数据源、Trello 配置、历史任务、归档全部自动保留，
            升级前系统还会自动把数据备份到 安装目录\backups\ 作为安全垫。
          </template>
        </el-alert>

        <div class="action-row">
          <el-button type="primary" size="large" :disabled="!pkg || upgrading" :loading="upgrading"
                     @click="confirmUpgrade">
            {{ upgrading ? phaseText : '开始升级' }}
          </el-button>
        </div>

        <el-progress v-if="upgrading && phase === 'upload'" :percentage="uploadPct" class="progress" />

        <el-result v-if="phase === 'restarting'" icon="warning" title="服务正在重启，请稍候…"
                   sub-title="系统正在备份数据并替换程序，完成后会自动恢复访问（通常 10~30 秒），请勿关闭本页">
        </el-result>

        <el-result v-if="phase === 'done'" icon="success" :title="`升级成功：v${oldVersion} → v${info.version}`"
                   sub-title="数据与配置完整保留，操作已留痕审计（系统日志查询可见）">
          <template #extra>
            <el-button type="primary" @click="reset">完成</el-button>
          </template>
        </el-result>

        <el-result v-if="phase === 'failed'" icon="error" title="服务重启等待超时"
                   sub-title="升级可能未完成。请到服务器查看 安装目录\upgrade\ 下的日志；必要时运行 安装目录\start.bat 手工启动，或从 安装目录\backups\ 还原数据">
          <template #extra>
            <el-button @click="reset">返回</el-button>
          </template>
        </el-result>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import api from '../api'

const info = ref({})
const pkg = ref(null)
const fileInput = ref(null)
const upgrading = ref(false)
const phase = ref('idle') // idle | upload | restarting | done | failed
const uploadPct = ref(0)
const oldVersion = ref('')
const expectedVersion = ref('')
const phaseText = ref('')

function fmtSize(n) {
  return n >= 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + ' MB' : (n / 1024).toFixed(0) + ' KB'
}

async function loadInfo() {
  const resp = await api.get('/admin/system/version')
  info.value = resp.data
}

function onPick(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  if (!f.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('请选择平台部署包 zip 文件')
    e.target.value = ''
    return
  }
  pkg.value = f
}

function clearPick() {
  pkg.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function confirmUpgrade() {
  try {
    await ElMessageBox.confirm(
      `确认将系统从 v${info.value.version} 升级到所选部署包版本？升级期间服务自动重启，数据自动备份并完整保留。`,
      '升级确认',
      { confirmButtonText: '确认升级', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  doUpgrade()
}

async function doUpgrade() {
  upgrading.value = true
  phase.value = 'upload'
  phaseText.value = '正在上传部署包…'
  uploadPct.value = 0
  oldVersion.value = info.value.version
  try {
    const fd = new FormData()
    fd.append('file', pkg.value)
    const resp = await api.post('/admin/system/upgrade', fd, {
      timeout: 600000,
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => { if (e.total) uploadPct.value = Math.round((e.loaded / e.total) * 100) },
    })
    expectedVersion.value = resp.data.to_version || ''
    phase.value = 'restarting'
    phaseText.value = '服务重启中…'
    waitRestart()
  } catch {
    upgrading.value = false
    phase.value = 'idle'
  }
}

// 轮询健康检查直到服务恢复（用原生 fetch，避免响应拦截器在 401/失败时跳登录页）
async function waitRestart() {
  const deadline = Date.now() + 120000
  // 先等服务真的断开（updater 替换程序需要数秒）
  await new Promise((r) => setTimeout(r, 6000))
  while (Date.now() < deadline) {
    try {
      const r = await fetch('/api/health', { cache: 'no-store' })
      if (r.ok) {
        await loadInfo()
        phase.value = 'done'
        upgrading.value = false
        ElMessage.success(`升级完成，当前版本 v${info.value.version}`)
        return
      }
    } catch { /* 服务尚未起来，继续等 */ }
    await new Promise((r) => setTimeout(r, 2000))
  }
  phase.value = 'failed'
  upgrading.value = false
}

function reset() {
  phase.value = 'idle'
  clearPick()
  loadInfo()
}

onMounted(loadInfo)
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
.info-table { max-width: 860px; }
.tip-bar { margin: 14px 0; max-width: 860px; }
.pick-row { display: flex; align-items: center; gap: 14px; margin: 6px 0; }
.file-input { font-size: 14px; }
.pkg-info { display: flex; align-items: center; gap: 6px; }
.pkg-name { font-weight: 600; }
.pkg-size { color: #909399; }
.action-row { margin-top: 6px; }
.progress { max-width: 860px; margin-top: 14px; }
</style>
