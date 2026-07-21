/**
 * axios 统一封装：
 * - baseURL=/api，请求自动携带 JWT；
 * - 401 统一清理登录态并回登录页；
 * - 错误统一 ElMessage 中文提示（直接透传后端 detail 中文错误）；
 * - 提供 downloadFile（blob 下载，保留后端中文文件名）。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { getToken, clearAuth } from '../utils/auth'

const api = axios.create({ baseURL: '/api', timeout: 60000 })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

function extractDetail(data, fallback) {
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => d.msg || JSON.stringify(d)).join('；')
  }
  return data.detail || data.message || fallback
}

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const resp = error.response
    // 登录接口的 401 属于"用户名或密码错误"，走普通错误分支透传 detail，不清理登录态、不跳页
    const isLoginRequest = (error.config?.url || '').includes('/auth/login')
    if (resp && resp.status === 401 && !isLoginRequest) {
      clearAuth()
      if (router.currentRoute.value.path !== '/login') {
        ElMessage.warning('登录状态已失效，请重新登录')
        router.push('/login')
      }
    } else {
      const msg = extractDetail(resp && resp.data, `请求失败（${resp ? resp.status : '网络异常'}）`)
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  },
)

/**
 * 下载文件（blob）：成功触发浏览器保存；失败解析 JSON 错误并提示。
 */
export async function downloadFile(url, fallbackName = 'download') {
  try {
    const resp = await api.get(url, { responseType: 'blob' })
    const disposition = resp.headers['content-disposition'] || ''
    let filename = fallbackName
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
    if (utf8Match) filename = decodeURIComponent(utf8Match[1])
    else if (plainMatch) filename = plainMatch[1]
    const link = document.createElement('a')
    link.href = URL.createObjectURL(resp.data)
    link.download = filename
    link.click()
    URL.revokeObjectURL(link.href)
    return true
  } catch (error) {
    // blob 错误响应需解析为 JSON 提取中文 detail
    const resp = error.response
    if (resp && resp.data instanceof Blob) {
      try {
        const text = await resp.data.text()
        const data = JSON.parse(text)
        ElMessage.error(extractDetail(data, '下载失败'))
      } catch {
        ElMessage.error('下载失败')
      }
    }
    return false
  }
}

export default api
