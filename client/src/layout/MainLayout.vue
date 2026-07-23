<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <div class="logo-title">安联资管运维管理平台</div>
        <div class="logo-sub">二期工程</div>
      </div>
      <el-menu :default-active="$route.path" router class="menu" background-color="#1f2d3d" text-color="#b8c4d4" active-text-color="#ffffff">
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
    <el-container>
      <el-header class="header">
        <div class="page-title">{{ $route.meta.title || '' }}</div>
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
      <el-main class="main">
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
.aside { background: #1f2d3d; }
.logo { padding: 18px 16px; border-bottom: 1px solid #2c3e50; }
.logo-title { color: #fff; font-size: 16px; font-weight: 600; line-height: 1.4; }
.logo-sub { color: #718096; font-size: 12px; margin-top: 2px; }
.menu { border-right: none; }
.header {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border-bottom: 1px solid #e4e7ed;
}
.page-title { font-size: 16px; font-weight: 600; color: #303133; }
.user-info { display: flex; align-items: center; gap: 6px; cursor: pointer; color: #606266; }
.main { background: #f5f7fa; padding: 16px; }
</style>
