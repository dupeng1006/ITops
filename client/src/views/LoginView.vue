<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <div class="brand">
        <BrandLogo variant="blue" :height="48" />
        <div class="brand-title">安联资管运维管理平台</div>
      </div>
      <el-alert
        v-if="loginError"
        :title="loginError"
        type="error"
        show-icon
        :closable="false"
        class="login-error"
      />
      <el-form :model="form" :rules="rules" ref="formRef" size="large" @keyup.enter="onLogin">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户编号" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="onLogin">登 录</el-button>
        </el-form-item>
      </el-form>
      <div class="login-tip">初始管理员 admin / Admin@123（首次登录强制修改密码）</div>
    </el-card>

    <el-dialog v-model="pwdVisible" title="首次登录请修改密码" width="420px" :close-on-click-modal="false" :show-close="false">
      <el-alert
        v-if="pwdError"
        :title="pwdError"
        type="error"
        show-icon
        :closable="false"
        class="login-error"
      />
      <el-form :model="pwdForm" :rules="pwdRules" ref="pwdFormRef" label-width="90px">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" :loading="pwdLoading" @click="onChangePassword">确认修改并重新登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import api from '../api'
import { setAuth } from '../utils/auth'
import BrandLogo from '../components/BrandLogo.vue'

const router = useRouter()
const route = useRoute()
const formRef = ref()
const pwdFormRef = ref()
const loading = ref(false)
const pwdVisible = ref(false)
const pwdLoading = ref(false)
const loginError = ref('')
const pwdError = ref('')
const form = reactive({ username: '', password: '' })
const pwdForm = reactive({ new_password: '', confirm: '' })

const rules = {
  username: [{ required: true, message: '请输入用户编号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const pwdRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '新密码至少 8 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) => cb(v === pwdForm.new_password ? undefined : new Error('两次输入的密码不一致')),
      trigger: 'blur',
    },
  ],
}

function extractError(error, fallback) {
  const data = error?.response?.data
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg || JSON.stringify(d)).join('；')
  return data.detail || data.message || fallback
}

async function doLogin() {
  const resp = await api.post('/auth/login', { username: form.username, password: form.password })
  return resp.data
}

async function onLogin() {
  await formRef.value.validate()
  loading.value = true
  loginError.value = ''
  try {
    const data = await doLogin()
    if (data.must_change_password) {
      // 首登强制改密：暂存 token，改密成功后重新登录
      tempToken = data.access_token
      pwdError.value = ''
      pwdVisible.value = true
      return
    }
    finishLogin(data)
  } catch (error) {
    // 拦截器已 ElMessage 提示，这里补充表单上方内联错误，避免登录页无可见反馈
    loginError.value = extractError(error, '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

let tempToken = ''

async function onChangePassword() {
  await pwdFormRef.value.validate()
  pwdLoading.value = true
  pwdError.value = ''
  try {
    await api.post(
      '/auth/change-password',
      { old_password: form.password, new_password: pwdForm.new_password },
      { headers: { Authorization: `Bearer ${tempToken}` } },
    )
    pwdVisible.value = false
    form.password = pwdForm.new_password
    const data = await doLogin()
    finishLogin(data)
    ElMessage.success('密码修改成功，已登录')
  } catch (error) {
    pwdError.value = extractError(error, '密码修改失败，请重试')
  } finally {
    pwdLoading.value = false
  }
}

function finishLogin(data) {
  setAuth(data.access_token, { username: data.username, role: data.role, display_name: data.display_name || null })
  router.push(route.query.redirect || '/dashboard')
}
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #003781 0%, #005eb8 60%, #2f86d6 100%);
}
.login-card {
  width: 400px;
  border-radius: 8px;
}
.brand { text-align: center; margin-bottom: 24px; }
.brand-title { font-size: 20px; font-weight: 600; color: #003781; margin-top: 12px; }
.login-error { margin-bottom: 16px; }
.login-btn { width: 100%; }
.login-tip { text-align: center; font-size: 12px; color: #a0aec0; }
</style>
