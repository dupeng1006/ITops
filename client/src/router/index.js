import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getToken, getUser } from '../utils/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '工作台', roles: ['admin', 'operator', 'viewer'] } },
      { path: 'recon/m1', name: 'recon-m1', component: () => import('../views/ReconM1View.vue'), meta: { title: '基金资产与净值核对', roles: ['admin', 'operator'] } },
      { path: 'recon/m2', name: 'recon-m2', component: () => import('../views/ReconM2View.vue'), meta: { title: '估值价格核对', roles: ['admin', 'operator'] } },
      { path: 'recon/m3', name: 'recon-m3', component: () => import('../views/ReconM3View.vue'), meta: { title: '银行间ID匹配', roles: ['admin', 'operator'] } },
      { path: 'archive', name: 'archive', component: () => import('../views/ArchiveView.vue'), meta: { title: '报告归档中心', roles: ['admin', 'operator', 'viewer'] } },
      { path: 'dict', name: 'dict', component: () => import('../views/DictView.vue'), meta: { title: '数据字典查询', roles: ['admin', 'operator'] } },
      { path: 'schedule', name: 'schedule', component: () => import('../views/ScheduleView.vue'), meta: { title: '任务调度中心', roles: ['admin', 'operator'] } },
      { path: 'rules', name: 'rules', component: () => import('../views/RulesView.vue'), meta: { title: '规则配置中心', roles: ['admin'] } },
      { path: 'datasource/connections', name: 'ds-connections', component: () => import('../views/DatasourceView.vue'), meta: { title: '数据源连接配置', roles: ['admin'] } },
      { path: 'datasource/templates', name: 'ds-templates', component: () => import('../views/QueryTemplatesView.vue'), meta: { title: '查询模板管理', roles: ['admin'] } },
      { path: 'system/config', name: 'system-config', component: () => import('../views/SystemConfigView.vue'), meta: { title: '系统配置', roles: ['admin'] } },
      { path: 'users', name: 'users', component: () => import('../views/UsersView.vue'), meta: { title: '用户维护', roles: ['admin'] } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!getToken()) return { path: '/login', query: to.fullPath !== '/dashboard' ? { redirect: to.fullPath } : {} }
  if (to.meta.roles) {
    const user = getUser()
    if (user && !to.meta.roles.includes(user.role)) {
      ElMessage.warning('权限不足：当前角色无权访问该页面')
      return { path: '/dashboard' }
    }
  }
  return true
})

export default router
