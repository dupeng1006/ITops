<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>Trello 连接配置（Token 加密存储，读取仅显示掩码；全部变更留痕审计）</span>
          <el-button type="primary" :icon="Plus" @click="openForm()">新增配置</el-button>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="api_key" label="API Key" min-width="200" />
        <el-table-column prop="token" label="Token" width="100" />
        <el-table-column prop="sync_min" label="同步间隔" width="100">
          <template #default="{ row }">{{ row.sync_min }} 分钟</template>
        </el-table-column>
        <el-table-column label="最近同步" min-width="160">
          <template #default="{ row }">
            <span v-if="row.last_sync_at">{{ row.last_sync_at }}</span>
            <span v-else style="color: #c0c4cc">未同步</span>
            <el-tag v-if="row.last_sync_status" :type="row.last_sync_status === 'success' ? 'success' : 'danger'" size="small" style="margin-left: 6px">
              {{ row.last_sync_status === 'success' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="修改人" width="100">
          <template #default="{ row }">{{ fmtUpdater(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" :loading="testingId === row.id" @click="onTest(row)">测试连接</el-button>
            <el-button text type="primary" size="small" :loading="syncingId === row.id" @click="onSync(row)">立即同步</el-button>
            <el-button text type="primary" size="small" @click="openForm(row)">编辑</el-button>
            <el-popconfirm title="确认删除该配置？" @confirm="del(row)">
              <template #reference><el-button text type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="formVisible" :title="form.id ? '编辑 Trello 配置' : '新增 Trello 配置'" width="520px">
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：我的 Trello" />
        </el-form-item>
        <el-form-item label="API Key" required>
          <el-input v-model="form.api_key" placeholder="Trello API Key" />
        </el-form-item>
        <el-form-item label="Token" :required="!form.id">
          <el-input v-model="form.token" type="password" show-password
                    :placeholder="form.id ? '留空表示不修改 Token' : 'Trello Token（服务端加密存储）'" />
        </el-form-item>
        <el-form-item label="同步间隔" required>
          <el-input-number v-model="form.sync_min" :min="1" :max="1440" />
          <span class="hint">分钟（启用后按此间隔自动同步）</span>
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
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'
import { fmtUpdater } from '../utils/display'

const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const syncingId = ref(null)
const formVisible = ref(false)
const emptyForm = {
  id: null, name: '', api_key: '', token: '', enabled: true, sync_min: 5,
}
const form = reactive({ ...emptyForm })

async function load() {
  loading.value = true
  try {
    const resp = await api.get('/trello/configs')
    rows.value = resp.data
  } finally {
    loading.value = false
  }
}

function openForm(row) {
  Object.assign(form, emptyForm, row ? {
    id: row.id, name: row.name, api_key: row.api_key, token: '', enabled: row.enabled, sync_min: row.sync_min,
  } : {})
  formVisible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写配置名称')
  if (!form.api_key.trim()) return ElMessage.warning('请填写 API Key')
  if (!form.id && !form.token) return ElMessage.warning('请填写 Token')

  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      api_key: form.api_key.trim(),
      enabled: form.enabled,
      sync_min: form.sync_min,
    }
    if (form.id) {
      payload.token = form.token || null
      await api.put(`/trello/configs/${form.id}`, payload)
      ElMessage.success('配置已更新')
    } else {
      payload.token = form.token
      await api.post('/trello/configs', payload)
      ElMessage.success('配置已创建')
    }
    formVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row, v) {
  await api.put(`/trello/configs/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
  await load()
}

async function onTest(row) {
  testingId.value = row.id
  try {
    const resp = await api.post(`/trello/configs/${row.id}/test`)
    const body = resp.data
    if (body.success) {
      ElMessageBox.alert(body.message, '测试连接', { type: 'success', confirmButtonText: '知道了' })
    } else {
      ElMessageBox.alert(body.message, '测试连接失败', { type: 'error', confirmButtonText: '知道了' })
    }
  } finally {
    testingId.value = null
  }
}

async function onSync(row) {
  syncingId.value = row.id
  try {
    const resp = await api.post(`/trello/configs/${row.id}/sync`)
    const body = resp.data
    if (body.success) {
      ElMessage.success(body.message)
    } else {
      ElMessage.error(body.message)
    }
    await load()
  } finally {
    syncingId.value = null
  }
}

async function del(row) {
  await api.delete(`/trello/configs/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.header-row { display: flex; align-items: center; justify-content: space-between; }
.hint { margin-left: 10px; color: #909399; font-size: 12px; }
</style>
