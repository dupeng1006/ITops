<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>用户维护（新建/重置后的账号首次登录均强制修改密码）</span>
          <el-button type="primary" :icon="Plus" @click="openCreate">新增用户</el-button>
        </div>
      </template>
      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column prop="username" label="用户编号" width="140" />
        <el-table-column label="用户姓名" width="120">
          <template #default="{ row }">{{ row.display_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="部门" min-width="140">
          <template #default="{ row }">{{ row.department || '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="{ admin: 'danger', operator: 'primary', viewer: 'info' }[row.role]">
              {{ roleName(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'warning'">
              {{ row.status === 'active' ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="165" />
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button text type="warning" size="small" @click="openReset(row)">重置密码</el-button>
            <el-popconfirm title="确认删除该用户？" @confirm="delUser(row)">
              <template #reference>
                <el-button text type="danger" size="small" :disabled="row.username === 'admin'">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createVisible" title="新增用户" width="420px">
      <el-form label-width="90px">
        <el-form-item label="用户编号" required>
          <el-input v-model="createForm.username" placeholder="登录使用的用户编号，2-50 位" />
        </el-form-item>
        <el-form-item label="用户姓名">
          <el-input v-model="createForm.display_name" maxlength="100" placeholder="选填" />
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="createForm.department" maxlength="100" placeholder="选填" />
        </el-form-item>
        <el-form-item label="初始密码" required>
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option label="操作员（核对执行）" value="operator" />
            <el-option label="只读用户（仅查询）" value="viewer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="`编辑用户 ${editForm.username}`" width="420px">
      <el-form label-width="90px">
        <el-form-item label="用户姓名">
          <el-input v-model="editForm.display_name" maxlength="100" placeholder="选填" />
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="editForm.department" maxlength="100" placeholder="选填" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role" style="width: 100%" :disabled="editForm.username === 'admin'">
            <el-option label="操作员（核对执行）" value="operator" />
            <el-option label="只读用户（仅查询）" value="viewer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editForm.statusActive" active-text="正常" inactive-text="停用"
                     :disabled="editForm.username === 'admin'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" :title="`重置密码 ${resetForm.username}`" width="420px">
      <el-form label-width="90px">
        <el-form-item label="新密码" required>
          <el-input v-model="resetForm.new_password" type="password" show-password placeholder="至少 8 位，重置后首登强制改密" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" @click="saveReset">重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'
import { roleName } from '../utils/auth'

const loading = ref(false)
const users = ref([])

async function load() {
  loading.value = true
  try {
    const resp = await api.get('/admin/users')
    users.value = resp.data
  } finally {
    loading.value = false
  }
}

/* 新增 */
const createVisible = ref(false)
const createForm = reactive({ username: '', password: '', role: 'operator', display_name: '', department: '' })

function openCreate() {
  Object.assign(createForm, { username: '', password: '', role: 'operator', display_name: '', department: '' })
  createVisible.value = true
}

async function saveCreate() {
  if (createForm.username.length < 2) {
    ElMessage.warning('用户编号至少 2 位')
    return
  }
  if (createForm.password.length < 8) {
    ElMessage.warning('初始密码至少 8 位')
    return
  }
  await api.post('/admin/users', {
    username: createForm.username,
    password: createForm.password,
    role: createForm.role,
    display_name: createForm.display_name.trim() || null,
    department: createForm.department.trim() || null,
  })
  ElMessage.success('已创建（首次登录强制改密）')
  createVisible.value = false
  load()
}

/* 编辑 */
const editVisible = ref(false)
const editForm = reactive({ id: null, username: '', role: 'operator', statusActive: true, display_name: '', department: '' })

function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    username: row.username,
    role: row.role,
    statusActive: row.status === 'active',
    display_name: row.display_name || '',
    department: row.department || '',
  })
  editVisible.value = true
}

async function saveEdit() {
  await api.put(`/admin/users/${editForm.id}`, {
    role: editForm.role,
    status: editForm.statusActive ? 'active' : 'disabled',
    display_name: editForm.display_name.trim() || null,
    department: editForm.department.trim() || null,
  })
  ElMessage.success('已保存')
  editVisible.value = false
  load()
}

/* 重置密码 */
const resetVisible = ref(false)
const resetForm = reactive({ id: null, username: '', new_password: '' })

function openReset(row) {
  Object.assign(resetForm, { id: row.id, username: row.username, new_password: '' })
  resetVisible.value = true
}

async function saveReset() {
  if (resetForm.new_password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  await api.post(`/admin/users/${resetForm.id}/reset-password`, { new_password: resetForm.new_password })
  ElMessage.success('已重置（该用户下次登录需修改密码）')
  resetVisible.value = false
}

/* 删除 */
async function delUser(row) {
  await api.delete(`/admin/users/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
</style>
