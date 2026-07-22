<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>系统日志查询（平台操作审计留痕；MAC 由服务端 ARP 解析，同网段可获取，跨网段显示"—"）</span>
        </div>
      </template>

      <!-- 查询条件 -->
      <div class="filter-bar">
        <el-input
          v-model="filters.username" placeholder="操作人员（编号/姓名）" clearable
          style="width: 180px" @keyup.enter="search(1)" @clear="search(1)" />
        <el-select
          v-model="filters.menu" placeholder="操作菜单（全部）" clearable filterable
          style="width: 240px" @change="search(1)">
          <el-option v-for="m in menuList" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select
          v-model="filters.action" placeholder="操作类型（全部）" clearable filterable
          style="width: 170px" @change="search(1)">
          <el-option v-for="a in actionList" :key="a" :label="ACTION_LABELS[a] || a" :value="a" />
        </el-select>
        <el-date-picker
          v-model="filters.range" type="daterange" range-separator="至"
          start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD"
          style="width: 250px" @change="search(1)" />
        <el-input
          v-model="filters.ip" placeholder="IP / MAC 模糊" clearable
          style="width: 150px" @keyup.enter="search(1)" @clear="search(1)" />
        <el-button type="primary" :icon="Search" @click="search(1)">查询</el-button>
        <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
      </div>

      <!-- 日志表格 -->
      <el-table :data="items" v-loading="loading" stripe border size="small">
        <el-table-column prop="time" label="时间" width="160" />
        <el-table-column label="操作人员" width="150">
          <template #default="{ row }">
            <div><b>{{ row.display_name || row.username }}</b></div>
            <div class="sub-text">{{ row.username }}<span v-if="row.department"> · {{ row.department }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="IP 地址" width="130">
          <template #default="{ row }"><span class="mono">{{ row.ip || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="MAC 地址" width="170">
          <template #default="{ row }">
            <span class="mono" :class="{ 'none-text': !row.mac }">{{ row.mac || '—（跨网段）' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作菜单" width="210">
          <template #default="{ row }">{{ row.menu || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="actionTag(row.action)">
              {{ ACTION_LABELS[row.action] || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作明细" min-width="300">
          <template #default="{ row }">
            <span class="detail-text">{{ row.detail || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && items.length === 0" description="暂无审计日志" :image-size="80" />

      <div class="pager">
        <el-pagination
          v-model:current-page="page" background layout="total, sizes, prev, pager, next"
          :total="total" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]"
          @current-change="search()" @size-change="onSizeChange" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshLeft, Search } from '@element-plus/icons-vue'
import api from '../api'

// 操作类型中文标签（与后端 action 对应）
const ACTION_LABELS = {
  login: '登录成功', login_failed: '登录失败', change_password: '修改密码',
  user_create: '新增用户', user_update: '修改用户', user_reset_password: '重置密码', user_delete: '删除用户',
  upload_create_job: '创建核对任务', download: '下载报告',
  rule_mapping_create: '新增映射', rule_mapping_update: '修改映射', rule_mapping_delete: '删除映射',
  rule_bulk_create: '新增特殊产品', rule_bulk_update: '修改特殊产品', rule_bulk_delete: '删除特殊产品',
  rule_threshold_update: '修改阈值', rule_import: '规则导入',
  ds_create: '新增数据源', ds_update: '修改数据源', ds_delete: '删除数据源', ds_test: '测试连接',
  tpl_create: '新增模板', tpl_update: '修改模板', tpl_delete: '删除模板', tpl_preview: '模板预览',
  schedule_create: '新增定时任务', schedule_update: '修改定时任务', schedule_delete: '删除定时任务',
  schedule_toggle: '启停定时任务', schedule_run_now: '立即执行',
  sys_subject_rule_create: '新增科目规则', sys_subject_rule_update: '修改科目规则',
  sys_subject_rule_delete: '删除科目规则', sys_params_update: '修改系统参数',
  dict_gen_sql: '字典生成SQL', dict_favorite_add: '收藏字典表', dict_favorite_remove: '取消收藏',
}

const DANGER_ACTIONS = new Set(['login_failed', 'user_delete', 'ds_delete', 'tpl_delete',
  'rule_mapping_delete', 'rule_bulk_delete', 'schedule_delete', 'sys_subject_rule_delete'])
const WARNING_ACTIONS = new Set(['change_password', 'rule_threshold_update', 'rule_import',
  'sys_params_update', 'ds_update', 'rule_mapping_update', 'rule_bulk_update', 'tpl_update',
  'sys_subject_rule_update', 'schedule_update', 'schedule_toggle'])

function actionTag(action) {
  if (DANGER_ACTIONS.has(action)) return 'danger'
  if (WARNING_ACTIONS.has(action)) return 'warning'
  if (action === 'login') return 'success'
  return 'primary'
}

const filters = ref({ username: '', menu: null, action: null, range: null, ip: '' })
const menuList = ref([])
const actionList = ref([])
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

async function search(p) {
  if (p) page.value = p
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filters.value.username) params.username = filters.value.username
    if (filters.value.menu) params.menu = filters.value.menu
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.ip) params.ip = filters.value.ip
    if (filters.value.range && filters.value.range.length === 2) {
      params.date_from = filters.value.range[0]
      params.date_to = filters.value.range[1]
    }
    const resp = await api.get('/audit-logs', { params })
    items.value = resp.data.items
    total.value = resp.data.total
    // 操作类型下拉：从结果集动态收集（仅取出现过的，避免下拉过长）
    const acts = new Set(actionList.value)
    resp.data.items.forEach((it) => acts.add(it.action))
    actionList.value = [...acts]
  } catch (e) {
    ElMessage.error('查询失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function onSizeChange(size) {
  pageSize.value = size
  search(1)
}

function reset() {
  filters.value = { username: '', menu: null, action: null, range: null, ip: '' }
  search(1)
}

onMounted(async () => {
  await search(1)
  try {
    const resp = await api.get('/audit-logs/menus')
    menuList.value = resp.data
  } catch { /* 菜单清单加载失败不阻塞主流程 */ }
})
</script>

<style scoped>
.header-row { display: flex; justify-content: space-between; align-items: center; }
.filter-bar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; align-items: center; }
.sub-text { font-size: 11px; color: #909399; }
.mono { font-family: Consolas, monospace; font-size: 12px; }
.none-text { color: #c0c4cc; }
.detail-text { font-size: 12px; color: #606266; }
.pager { margin-top: 14px; display: flex; justify-content: flex-end; }
</style>
