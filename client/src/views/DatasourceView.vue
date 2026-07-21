<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>数据源连接配置（密码加密存储，读取仅显示掩码；全部变更留痕审计）</span>
          <el-button type="primary" :icon="Plus" @click="openForm()">新增数据源</el-button>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ typeLabel(row.db_type) }}</template>
        </el-table-column>
        <el-table-column label="连接目标" min-width="220">
          <template #default="{ row }">{{ targetText(row) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="账号" width="120" />
        <el-table-column prop="password" label="密码" width="100" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="updated_by" label="修改人" width="100" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" :loading="testingId === row.id"
                       @click="onTest(row)">测试连接</el-button>
            <el-button text type="primary" size="small" @click="openForm(row)">编辑</el-button>
            <el-popconfirm title="确认删除该数据源？被模板引用时将无法删除" @confirm="del(row)">
              <template #reference><el-button text type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑数据源' : '新增数据源'" width="560px">
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：O32 生产库（只读）" />
        </el-form-item>
        <el-form-item label="数据库类型" required>
          <el-select v-model="form.db_type" style="width: 100%" @change="onTypeChange">
            <el-option v-for="t in dbTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机" required>
          <el-input v-model="form.host" placeholder="IP 或主机名" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" :placeholder="String(defaultPort)" />
          <span class="hint">留空按类型默认（当前默认 {{ defaultPort }}）</span>
        </el-form-item>
        <template v-if="form.db_type === 'oracle'">
          <el-form-item label="服务名">
            <el-input v-model="form.service_name" placeholder="service_name（与 SID 二选一，推荐）" />
          </el-form-item>
          <el-form-item label="SID">
            <el-input v-model="form.sid" placeholder="SID（与服务名二选一）" />
          </el-form-item>
        </template>
        <el-form-item v-else label="库名" required>
          <el-input v-model="form.db_name" placeholder="数据库名" />
        </el-form-item>
        <el-form-item label="账号" required>
          <el-input v-model="form.username" placeholder="建议使用只读账号（见部署手册授权示例）" />
        </el-form-item>
        <el-form-item label="密码" :required="!form.id">
          <el-input v-model="form.password" type="password" show-password
                    :placeholder="form.id ? '留空表示不修改密码' : '请输入密码（服务端加密存储）'" />
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'

const dbTypes = [
  { value: 'oracle', label: 'Oracle', port: 1521 },
  { value: 'mariadb', label: 'MariaDB', port: 3306 },
  { value: 'mysql', label: 'MySQL', port: 3306 },
  { value: 'mssql', label: 'SQL Server', port: 1433 },
  { value: 'postgresql', label: 'PostgreSQL', port: 5432 },
]

const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const testingId = ref(null)
const formVisible = ref(false)
const emptyForm = {
  id: null, name: '', db_type: 'oracle', host: '', port: null,
  db_name: '', service_name: '', sid: '', username: '', password: '', enabled: true,
}
const form = reactive({ ...emptyForm })

const defaultPort = computed(() => (dbTypes.find((t) => t.value === form.db_type) || {}).port || 0)

function typeLabel(v) {
  return (dbTypes.find((t) => t.value === v) || {}).label || v
}

function targetText(row) {
  if (row.db_type === 'oracle') {
    return `${row.host || ''}:${row.port || 1521} / ${row.service_name ? '服务名 ' + row.service_name : 'SID ' + (row.sid || '')}`
  }
  return `${row.host || ''}:${row.port || ''} / ${row.db_name || ''}`
}

async function load() {
  loading.value = true
  try {
    const resp = await api.get('/datasources')
    rows.value = resp.data
  } finally {
    loading.value = false
  }
}

function onTypeChange() {
  form.port = null
}

function openForm(row) {
  Object.assign(form, emptyForm, row ? {
    id: row.id, name: row.name, db_type: row.db_type, host: row.host,
    port: row.port, db_name: row.db_name || '', service_name: row.service_name || '',
    sid: row.sid || '', username: row.username, password: '', enabled: row.enabled,
  } : {})
  formVisible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写数据源名称')
  if (!form.host.trim()) return ElMessage.warning('请填写主机')
  if (form.db_type === 'oracle') {
    if (!form.service_name.trim() && !form.sid.trim()) return ElMessage.warning('Oracle 需填写服务名或 SID 之一')
  } else if (!form.db_name.trim()) return ElMessage.warning('请填写库名')
  if (!form.username.trim()) return ElMessage.warning('请填写账号')
  if (!form.id && !form.password) return ElMessage.warning('请填写密码')

  saving.value = true
  try {
    const payload = {
      name: form.name.trim(), db_type: form.db_type, host: form.host.trim(),
      port: form.port || null,
      db_name: form.db_type === 'oracle' ? null : form.db_name.trim() || null,
      service_name: form.db_type === 'oracle' ? form.service_name.trim() || null : null,
      sid: form.db_type === 'oracle' ? form.sid.trim() || null : null,
      username: form.username.trim(), enabled: form.enabled,
    }
    if (form.id) {
      payload.password = form.password || null  // 留空表示不修改
      await api.put(`/datasources/${form.id}`, payload)
      ElMessage.success('数据源已更新')
    } else {
      payload.password = form.password
      await api.post('/datasources', payload)
      ElMessage.success('数据源已创建')
    }
    formVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row, v) {
  await api.put(`/datasources/${row.id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
  await load()
}

async function onTest(row) {
  testingId.value = row.id
  try {
    const resp = await api.post(`/datasources/${row.id}/test`)
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

async function del(row) {
  await api.delete(`/datasources/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.header-row { display: flex; align-items: center; justify-content: space-between; }
.hint { margin-left: 10px; color: #909399; font-size: 12px; }
</style>
