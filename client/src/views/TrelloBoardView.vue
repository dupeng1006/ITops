<template>
  <div class="trello-board">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 180px" @change="applyFilter">
            <el-option label="全部状态" value="" />
            <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value">
              <el-tag :color="s.color" size="small" style="margin-right: 6px">&nbsp;</el-tag>
              <span>{{ s.label }}</span>
            </el-option>
          </el-select>
          <el-input v-model="search" placeholder="搜索卡片标题" clearable style="width: 220px" @input="applyFilter" />
          <el-button @click="resetFilter">重置</el-button>
          <el-button type="primary" :loading="syncing" @click="syncAll">立即同步</el-button>
        </div>
        <div class="stats">
          <div class="stat"><div class="stat-num">{{ stats.total }}</div><div class="stat-label">与我相关</div></div>
          <div class="stat"><div class="stat-num">{{ stats.withDue }}</div><div class="stat-label">有截止日期</div></div>
          <div class="stat"><div class="stat-num" :class="{ 'overdue': stats.overdue > 0 }">{{ stats.overdue }}</div><div class="stat-label">已逾期</div></div>
        </div>
      </div>
      <div class="status-summary">
        <span v-for="s in statusSummary" :key="s.value" class="summary-badge" :style="{ backgroundColor: s.color }">
          {{ s.label }} <b>{{ s.count }}</b>
        </span>
      </div>
    </el-card>

    <div v-if="loading" v-loading="loading" class="board-loading" />

    <div v-else-if="groupedBoards.length === 0" class="empty-tip">
      <el-empty description="暂无 Trello 卡片，请先在配置页添加 Trello 连接并同步" />
    </div>

    <div v-else class="boards">
      <el-card v-for="board in groupedBoards" :key="board.board_id" shadow="never" class="board-card">
        <template #header>
          <div class="board-header">
            <span class="board-title">📋 {{ board.name }}</span>
            <el-link v-if="board.url" :href="board.url" target="_blank" type="primary">打开 Trello ↗</el-link>
          </div>
        </template>
        <div class="lists">
          <div v-for="list in board.lists" :key="list.list_id" class="list">
            <div class="list-header">{{ list.name }} <span class="list-count">({{ list.cards.length }})</span></div>
            <div class="list-body">
              <div v-for="card in list.cards" :key="card.card_id" class="card">
                <div class="card-status" :style="{ backgroundColor: statusColor(card.status) }">
                  {{ statusLabel(card.status) }}
                </div>
                <div class="card-title">{{ card.name }}</div>
                <div class="card-desc">{{ card.desc || '无描述' }}</div>
                <div class="card-meta">
                  <span v-for="(label, idx) in otherLabels(card.labels_json)" :key="idx" class="label" :style="{ backgroundColor: label.color }">
                    {{ label.name }}
                  </span>
                  <span v-if="card.due_date" class="due" :class="dueClass(card)">
                    {{ dueClass(card) === 'due-overdue' ? '⚠️' : (card.due_complete ? '✅' : '📅') }} {{ formatDue(card.due_date) }}
                  </span>
                </div>
                <div class="card-actions">
                  <el-link v-if="card.url" :href="card.url" target="_blank" type="primary" size="small">在 Trello 打开 ↗</el-link>
                </div>
              </div>
              <div v-if="list.cards.length === 0" class="empty-card">暂无卡片</div>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-pagination v-if="pagination.total > pagination.pageSize" class="pagination"
                   v-model:current-page="pagination.page" :page-size="pagination.pageSize"
                   :total="pagination.total" layout="prev, pager, next" @current-change="onPageChange" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const STATUS_MAP = {
  'Done': { label: '已完成', color: '#67c23a' },
  'Suspended': { label: '已暂停', color: '#e6a23c' },
  'Help': { label: '求助', color: '#ff9f1a' },
  'Delayed': { label: '已延期', color: '#f56c6c' },
  'Not Started': { label: '未开始', color: '#c377e0' },
  'Ongoing': { label: '进行中', color: '#409eff' },
  'Closed': { label: '已关闭', color: '#909399' },
}
const STATUS_LABELS = ['Done', 'Suspended', 'Help', 'Delayed', 'Not Started', 'Ongoing', 'Closed']

const allCards = ref([])
const loading = ref(false)
const syncing = ref(false)
const statusFilter = ref('')
const search = ref('')
const pagination = reactive({ page: 1, pageSize: 500, total: 0 })

const statusOptions = computed(() => STATUS_LABELS.map((s) => ({ value: s, label: `${s} ${STATUS_MAP[s].label}`, color: STATUS_MAP[s].color })))

const statusSummary = computed(() => {
  const counts = {}
  STATUS_LABELS.forEach((s) => { counts[s] = 0 })
  counts['未设置状态'] = 0
  allCards.value.forEach((c) => {
    if (c.status && STATUS_LABELS.includes(c.status)) counts[c.status]++
    else counts['未设置状态']++
  })
  return STATUS_LABELS.map((s) => ({ value: s, label: `${s} ${STATUS_MAP[s].label}`, count: counts[s], color: STATUS_MAP[s].color }))
    .concat([{ value: '未设置状态', label: '未设置状态', count: counts['未设置状态'], color: '#c0c4cc' }])
})

const stats = computed(() => {
  const total = allCards.value.length
  const withDue = allCards.value.filter((c) => c.due_date).length
  const overdue = allCards.value.filter((c) => c.due_date && !c.due_complete && new Date(c.due_date) < new Date()).length
  return { total, withDue, overdue }
})

const filteredCards = computed(() => {
  let list = allCards.value
  if (statusFilter.value) {
    if (statusFilter.value === '未设置状态') {
      list = list.filter((c) => !c.status || !STATUS_LABELS.includes(c.status))
    } else {
      list = list.filter((c) => c.status === statusFilter.value)
    }
  }
  if (search.value.trim()) {
    const kw = search.value.trim().toLowerCase()
    list = list.filter((c) => c.name.toLowerCase().includes(kw))
  }
  return list
})

const groupedBoards = computed(() => {
  const map = {}
  filteredCards.value.forEach((card) => {
    const boardKey = card.board_id || 'unknown'
    if (!map[boardKey]) {
      map[boardKey] = {
        board_id: boardKey,
        name: card.board_name || '未知 Board',
        url: card.board_url || '',
        lists: {},
      }
    }
    const listKey = card.list_id || 'unknown'
    if (!map[boardKey].lists[listKey]) {
      map[boardKey].lists[listKey] = { list_id: listKey, name: card.list_name || '未分类', cards: [] }
    }
    map[boardKey].lists[listKey].cards.push(card)
  })
  return Object.values(map).map((b) => ({
    ...b,
    lists: Object.values(b.lists).sort((a, b) => (a.cards[0]?.pos || 0) - (b.cards[0]?.pos || 0)),
  }))
})

function statusColor(status) {
  return STATUS_MAP[status]?.color || '#c0c4cc'
}
function statusLabel(status) {
  if (!status || !STATUS_MAP[status]) return '未设置状态'
  return `${status} ${STATUS_MAP[status].label}`
}
function otherLabels(labelsJson) {
  try {
    const arr = JSON.parse(labelsJson || '[]')
    return arr.filter((l) => !STATUS_LABELS.includes(l.name)).map((l) => ({
      name: l.name,
      color: l.color ? labelColor(l.color) : '#909399',
    }))
  } catch {
    return []
  }
}
function labelColor(trelloColor) {
  const map = {
    green: '#61bd4f', yellow: '#f2d600', orange: '#ff9f1a', red: '#eb5a46',
    purple: '#c377e0', blue: '#0079bf', sky: '#00c2e0', lime: '#51e898',
    pink: '#ff78cb', black: '#344563',
  }
  return map[trelloColor] || '#b3b3b3'
}
function formatDue(due) {
  if (!due) return ''
  const d = new Date(due)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function dueClass(card) {
  if (card.due_complete) return 'due-done'
  if (card.due_date && new Date(card.due_date) < new Date()) return 'due-overdue'
  return 'due-normal'
}
function applyFilter() {
  pagination.page = 1
}
function resetFilter() {
  statusFilter.value = ''
  search.value = ''
  pagination.page = 1
}
function onPageChange(page) {
  pagination.page = page
  loadCards()
}

async function loadCards() {
  loading.value = true
  try {
    const resp = await api.get('/trello/cards', {
      params: {
        page: pagination.page,
        page_size: pagination.pageSize,
        status: statusFilter.value || undefined,
        search: search.value.trim() || undefined,
      },
    })
    const data = resp.data
    allCards.value = data.items
    pagination.total = data.total
    // 补 board_url（本地未冗余，用 Trello 规律拼接）
    allCards.value.forEach((c) => {
      if (c.url && !c.board_url) {
        c.board_url = c.url.replace(/\/c\/.*$/, '')
      }
    })
  } finally {
    loading.value = false
  }
}

async function syncAll() {
  syncing.value = true
  try {
    const resp = await api.get('/trello/configs')
    const configs = resp.data || []
    if (configs.length === 0) {
      ElMessage.warning('请先添加 Trello 配置')
      return
    }
    let ok = 0
    for (const cfg of configs) {
      const r = await api.post(`/trello/configs/${cfg.id}/sync`)
      if (r.data.success) ok++
    }
    ElMessage.success(`同步完成：${ok}/${configs.length} 个配置成功`)
    await loadCards()
  } finally {
    syncing.value = false
  }
}

onMounted(loadCards)
</script>

<style scoped>
.trello-board { height: 100%; }
.toolbar-card { margin-bottom: 16px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.toolbar-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.stats { display: flex; gap: 16px; }
.stat { text-align: center; }
.stat-num { font-size: 22px; font-weight: 700; color: #303133; }
.stat-num.overdue { color: #f56c6c; }
.stat-label { font-size: 12px; color: #909399; }
.status-summary { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
.summary-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 12px; font-size: 12px; color: #fff; font-weight: 500; }
.summary-badge b { margin-left: 4px; }
.boards { display: flex; flex-direction: column; gap: 16px; }
.board-card { overflow: hidden; }
.board-header { display: flex; justify-content: space-between; align-items: center; }
.board-title { font-size: 16px; font-weight: 600; color: #303133; }
.lists { display: flex; gap: 16px; overflow-x: auto; padding: 4px 0 10px; }
.list { min-width: 280px; max-width: 320px; background: #f5f7fa; border-radius: 8px; padding: 12px; flex-shrink: 0; }
.list-header { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #e4e7ed; }
.list-count { color: #909399; font-weight: 400; }
.card { background: #fff; border-radius: 6px; padding: 12px; margin-bottom: 10px; border: 1px solid #ebeef5; transition: transform 0.15s; }
.card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.card-status { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 12px; font-size: 12px; color: #fff; font-weight: 600; margin-bottom: 8px; }
.card-title { font-size: 14px; font-weight: 500; color: #303133; line-height: 1.4; }
.card-desc { font-size: 12px; color: #909399; margin-top: 6px; line-height: 1.5; }
.card-meta { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.label { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; color: #fff; font-weight: 500; }
.due { font-size: 12px; padding: 2px 8px; border-radius: 12px; background: #f0f2f5; }
.due-overdue { background: #fef0f0; color: #f56c6c; }
.due-done { background: #f0f9eb; color: #67c23a; }
.due-normal { color: #606266; }
.card-actions { margin-top: 10px; }
.empty-card { color: #c0c4cc; font-size: 13px; text-align: center; padding: 20px 0; }
.empty-tip { margin-top: 40px; }
.pagination { margin-top: 20px; justify-content: flex-end; }
.board-loading { min-height: 200px; }
</style>
