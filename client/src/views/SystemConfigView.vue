<template>
  <div>
    <!-- 系统参数（任务调度中心就绪时间与重试策略；存 sys_config，读写留痕审计） -->
    <el-card shadow="never" class="params-card">
      <template #header>
        <div class="header-row">
          <span>系统参数（定时任务 file 模式就绪判定与失败重试；保存后新执行即时生效）</span>
          <el-button type="primary" :loading="paramsSaving" @click="saveParams">保存参数</el-button>
        </div>
      </template>
      <el-form inline label-width="auto">
        <el-form-item label="数据就绪时间">
          <el-time-picker v-model="params.data_ready_time" format="HH:mm" value-format="HH:mm"
                          placeholder="HH:MM" class="param-time" />
          <span class="form-hint">file 模式判定文件就绪的基准时刻（默认 17:30）</span>
        </el-form-item>
        <el-form-item label="就绪缓冲(分钟)">
          <el-input-number v-model="params.buffer_minutes" :min="0" :max="180" />
          <span class="form-hint">就绪时间 + 缓冲之前文件大概率未就绪（默认 30）</span>
        </el-form-item>
        <el-form-item label="失败重试间隔(分钟)">
          <el-input-number v-model="params.retry_delay" :min="1" :max="1440" />
          <span class="form-hint">定时任务失败后隔此时长重试 1 次（默认 5）</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>科目取价规则（M2 估值价格核对取价口径；修改即时热生效，新建任务按新规则执行；全部修改留痕审计）</span>
          <el-button type="primary" :icon="Plus" @click="openEdit()">新增规则</el-button>
        </div>
      </template>

      <el-alert type="info" :closable="false" class="tip-bar">
        <template #title>
          估值表按科目层级取价：科目前缀（如 1101）匹配叶子明细后，按取价字段（如 市价）取估值表价格。
          口径提示语会在差异行「备注」列自动带出（如 1501 摊余成本说明）。
        </template>
      </el-alert>

      <el-table :data="rules" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="subject_prefix" label="科目前缀" width="110" />
        <el-table-column prop="price_field" label="取价字段" width="110" />
        <el-table-column prop="description" label="科目说明" min-width="140" />
        <el-table-column prop="note" label="口径提示语" min-width="220">
          <template #default="{ row }">{{ row.note || '（空）' }}</template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序号" width="80" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="updated_by" label="修改人" width="110" />
        <el-table-column prop="updated_at" label="修改时间" width="160" />
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确认删除该规则？删除后新建任务不再按此科目取价" @confirm="del(row)">
              <template #reference><el-button text type="danger" size="small">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑科目取价规则' : '新增科目取价规则'" width="520px">
      <el-form label-width="100px">
        <el-form-item label="科目前缀" required>
          <el-input v-model="form.subject_prefix" placeholder="如 1101 / 1501" maxlength="20" />
        </el-form-item>
        <el-form-item label="取价字段" required>
          <el-select v-model="form.price_field" filterable allow-create default-first-option
                     placeholder="估值表列名，如 市价" class="field-select">
            <el-option v-for="f in presetFields" :key="f" :label="f" :value="f" />
          </el-select>
        </el-form-item>
        <el-form-item label="科目说明">
          <el-input v-model="form.description" placeholder="如 交易性金融资产" maxlength="100" />
        </el-form-item>
        <el-form-item label="口径提示语">
          <el-input v-model="form.note" type="textarea" :rows="2" maxlength="200"
                    placeholder="差异行备注带出的说明（可空），如：摊余成本与市场估值口径差异，属正常" />
        </el-form-item>
        <el-form-item label="排序号">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
          <span class="form-hint">小者先提取</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'

const presetFields = ['市价', '单位成本', '成本']
const rules = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const form = reactive({
  id: null, subject_prefix: '', price_field: '', description: '',
  note: '', sort_order: 0, enabled: true,
})

/* 系统参数（sys_config：调度就绪时间与重试策略） */
const params = reactive({ data_ready_time: '17:30', buffer_minutes: 30, retry_delay: 5 })
const paramsSaving = ref(false)

async function loadParams() {
  const resp = await api.get('/admin/system/params')
  const map = Object.fromEntries(resp.data.map((p) => [p.param_key, p.param_value]))
  if (map.data_ready_time) params.data_ready_time = map.data_ready_time
  if (map.buffer_minutes !== undefined) params.buffer_minutes = Number(map.buffer_minutes)
  if (map.schedule_retry_delay_minutes !== undefined) {
    params.retry_delay = Number(map.schedule_retry_delay_minutes)
  }
}

async function saveParams() {
  if (!params.data_ready_time) {
    ElMessage.warning('数据就绪时间不能为空')
    return
  }
  paramsSaving.value = true
  try {
    await api.put('/admin/system/params', {
      values: {
        data_ready_time: params.data_ready_time,
        buffer_minutes: String(params.buffer_minutes),
        schedule_retry_delay_minutes: String(params.retry_delay),
      },
    })
    ElMessage.success('系统参数已保存（新执行即时生效）')
    await loadParams()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    paramsSaving.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const resp = await api.get('/admin/system/subject-price-rules')
    rules.value = resp.data
  } finally {
    loading.value = false
  }
}

function openEdit(row) {
  if (row) {
    Object.assign(form, {
      id: row.id, subject_prefix: row.subject_prefix, price_field: row.price_field,
      description: row.description || '', note: row.note || '',
      sort_order: row.sort_order, enabled: row.enabled,
    })
  } else {
    Object.assign(form, {
      id: null, subject_prefix: '', price_field: '', description: '',
      note: '', sort_order: (rules.value.length + 1) * 10, enabled: true,
    })
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.subject_prefix.trim() || !form.price_field.trim()) {
    ElMessage.warning('科目前缀与取价字段不能为空')
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await api.put(`/admin/system/subject-price-rules/${form.id}`, {
        subject_prefix: form.subject_prefix, price_field: form.price_field,
        description: form.description || null, note: form.note || null,
        sort_order: form.sort_order, enabled: form.enabled,
      })
      ElMessage.success('规则已更新（新建任务即时生效）')
    } else {
      await api.post('/admin/system/subject-price-rules', {
        subject_prefix: form.subject_prefix, price_field: form.price_field,
        description: form.description || null, note: form.note || null,
        sort_order: form.sort_order, enabled: form.enabled,
      })
      ElMessage.success('规则已新增（新建任务即时生效）')
    }
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function toggle(row, enabled) {
  await api.put(`/admin/system/subject-price-rules/${row.id}`, { enabled })
  ElMessage.success(enabled ? '已启用' : '已停用')
  await load()
}

async function del(row) {
  await api.delete(`/admin/system/subject-price-rules/${row.id}`)
  ElMessage.success('规则已删除')
  await load()
}

onMounted(() => {
  load()
  loadParams()
})
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
.tip-bar { margin-bottom: 12px; }
.field-select { width: 100%; }
.form-hint { margin-left: 10px; color: #909399; font-size: 12px; }
.params-card { margin-bottom: 16px; }
.param-time { width: 130px; }
</style>
