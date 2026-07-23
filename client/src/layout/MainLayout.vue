<template>
  <el-container class="layout">
    <el-header class="topbar" height="52px">
      <div class="topbar-left">
        <BrandLogo variant="white" :height="30" />
        <span class="topbar-divider"></span>
        <span class="system-name">安联资管运维管理平台</span>
      </div>
      <el-dropdown @command="onCommand">
        <span class="user-info">
          <el-icon><Avatar /></el-icon>
          {{ userLabel }}
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-header>
    <el-container class="layout-body">
      <el-aside width="220px" class="aside">
        <el-menu :default-active="$route.path" router class="menu">
          <el-menu-item index="/dashboard">
            <el-icon><Monitor /></el-icon><span>工作台</span>
          </el-menu-item>
          <el-sub-menu v-if="canOperate" index="recon">
            <template #title><el-icon><DocumentChecked /></el-icon><span>数据核对中心</span></template>
            <el-menu-item index="/recon/m1">基金资产与净值核对</el-menu-item>
            <el-menu-item index="/recon/m2">估值价格核对</el-menu-item>
            <el-menu-item index="/recon/m3">银行间ID匹配</el-menu-item>
          </el-sub-menu>
          <el-menu-item v-if="canOperate" index="/dict">
            <el-icon><Collection /></el-icon><span>数据字典查询</span>
          </el-menu-item>
          <el-menu-item index="/archive">
            <el-icon><Files /></el-icon><span>报告归档中心</span>
          </el-menu-item>
          <el-menu-item v-if="canOperate" index="/schedule">
            <el-icon><AlarmClock /></el-icon><span>任务调度中心</span>
          </el-menu-item>
          <el-menu-item v-if="isAdmin" index="/rules">
            <el-icon><SetUp /></el-icon><span>规则配置中心</span>
          </el-menu-item>
          <el-sub-menu v-if="isAdmin" index="datasource">
            <template #title><el-icon><Coin /></el-icon><span>数据源管理</span></template>
            <el-menu-item index="/datasource/connections">连接配置</el-menu-item>
            <el-menu-item index="/datasource/templates">查询模板</el-menu-item>
          </el-sub-menu>
          <el-sub-menu v-if="isAdmin" index="system">
            <template #title><el-icon><Setting /></el-icon><span>系统管理</span></template>
            <el-menu-item index="/system/config">系统配置</el-menu-item>
            <el-menu-item index="/users">用户维护</el-menu-item>
            <el-menu-item index="/audit-logs">系统日志查询</el-menu-item>
          </el-sub-menu>
          <el-sub-menu v-if="isAdmin" index="trello">
            <template #title><el-icon><CollectionTag /></el-icon><span>Trello 工作看板</span></template>
            <el-menu-item index="/trello/board">我的工作看板</el-menu-item>
            <el-menu-item index="/trello/config">连接配置</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>
      <el-main class="main">
        <div class="page-title">{{ $route.meta.title || '' }}</div>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { getUser, clearAuth } from '../utils/auth'
import BrandLogo from '../components/BrandLogo.vue'

const router = useRouter()
const user = computed(() => getUser())
const isAdmin = computed(() => user.value?.role === 'admin')
const canOperate = computed(() => ['admin', 'operator'].includes(user.value?.role))
// 有用户姓名时显示"用户姓名（用户编号）"，否则只显示用户编号
const userLabel = computed(() => {
  const u = user.value
  if (!u) return ''
  return u.display_name ? `${u.display_name}（${u.username}）` : u.username
})

async function onCommand(cmd) {
  if (cmd === 'logout') {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
    clearAuth()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout { height: 100%; }

/* 顶部安联蓝导航栏 */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(90deg, #003781 0%, #005EB8 100%);
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 55, 129, 0.25);
  z-index: 10;
}
.topbar-left { display: flex; align-items: center; gap: 14px; }
.topbar-divider { width: 1px; height: 22px; background: rgba(255, 255, 255, 0.35); }
.system-name { color: #fff; font-size: 15px; font-weight: 600; letter-spacing: 0.5px; }
.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #fff;
  font-size: 14px;
}
.user-info:hover { opacity: 0.85; }

.layout-body { height: calc(100% - 52px); }

/* 左侧白色菜单 */
.aside { background: #fff; border-right: 1px solid #e4e7ed; }
.menu { border-right: none; }
.menu:not(.el-menu--collapse) { width: 100%; }
.menu :deep(.el-menu-item),
.menu :deep(.el-sub-menu__title) {
  color: #303133;
  height: 46px;
  line-height: 46px;
}
.menu :deep(.el-menu-item .el-icon),
.menu :deep(.el-sub-menu__title .el-icon) { color: #7c8ea6; }
.menu :deep(.el-menu-item:hover),
.menu :deep(.el-sub-menu__title:hover) { background: #f2f6fb; }
.menu :deep(.el-sub-menu .el-menu) { background: #fff; }
.menu :deep(.el-sub-menu .el-menu-item) { color: #606266; }
.menu :deep(.el-menu-item.is-active) {
  color: #005EB8;
  background: #eaf3fb;
  box-shadow: inset 3px 0 0 0 #005EB8;
}
.menu :deep(.el-menu-item.is-active .el-icon) { color: #005EB8; }
.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) { color: #005EB8; }
.menu :deep(.el-sub-menu.is-active > .el-sub-menu__title .el-icon) { color: #005EB8; }

/* 内容区 */
.main { background: #f0f2f5; padding: 16px; }
.page-title {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 10px 16px;
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
</style>
