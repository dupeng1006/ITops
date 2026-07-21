/**
 * 认证工具：token 与当前用户信息的本地存取
 */
const TOKEN_KEY = 'o32_token'
const USER_KEY = 'o32_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY)) || null
  } catch {
    return null
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function roleName(role) {
  return { admin: '管理员', operator: '操作员', viewer: '只读用户' }[role] || role
}
