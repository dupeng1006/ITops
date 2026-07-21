<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="6" v-for="card in cards" :key="card.label">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 统计看板（operator 及以上；viewer 提示无权限） -->
    <el-alert v-if="noPerm" type="info" :closable="false" class="board-block">
      <template #title>统计看板（差异趋势 / 持续差异 / 任务健康度）需 operator 及以上角色，当前账号仅可查看任务列表</template>
    </el-alert>

    <template v-if="!noPerm">
      <!-- 任务健康度 -->
      <el-row :gutter="16" class="board-block">
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-value health">{{ health.schedule_enabled }}/{{ health.schedule_total }}</div>
            <div class="stat-label">定时任务 启用/总数</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-value" style="color:#38a169">{{ health.last30d?.success || 0 }}</div>
            <div class="stat-label">近30天定时执行成功</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-value" :style="{ color: (health.last30d?.failed || 0) > 0 ? '#c53030' : '#38a169' }">
              {{ health.last30d?.failed || 0 }}
            </div>
            <div class="stat-label">近30天定时执行失败</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-value" :style="{ color: (health.last30d?.wait_file || 0) > 0 ? '#b7791f' : '#2c5282' }">
              {{ health.last30d?.wait_file || 0 }}
            </div>
            <div class="stat-label">近30天"待文件"（就绪 {{ health.data_ready_time }}+{{ health.buffer_minutes }}min）</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 差异趋势 -->
      <el-card shadow="never" class="board-block">
        <template #header>
          <div class="card-header">
            <span>M1 核对差异趋势（近 {{ trendDays }} 天，按业务日期）</span>
            <el-radio-group v-model="trendDays" size="small" @change="loadTrend">
              <el-radio-button :value="7">7天</el-radio-button>
              <el-radio-button :value="30">30天</el-radio-button>
              <el-radio-button :value="90">90天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div ref="trendChart" class="trend-chart" v-loading="trendLoading">
          <el-empty v-if="!trendLoading && trendEmpty" description="期内暂无成功的 M1 任务" :image-size="80" />
        </div>
      </el-card>

      <!-- 持续差异产品 -->
      <el-card shadow="never" class="board-block">
        <template #header>
          <div class="card-header">
            <span>持续差异产品（近 {{ persistent.days || 7 }} 天差异&gt;{{ persistent.threshold_pct ?? 1 }}% 出现 ≥{{ persistent.min_times || 2 }} 次）</span>
            <el-button text type="primary" @click="loadPersistent">刷新</el-button>
          </div>
        </template>
        <el-table :data="persistent.items" size="small" stripe>
          <el-table-column prop="product_code" label="产品代码" width="130" />
          <el-table-column prop="product_name" label="产品名称" min-width="220" show-overflow-tooltip />
          <el-table-column prop="times" label="出现次数" width="100" align="center" />
          <el-table-column label="最近差异%" width="120" align="right">
            <template #default="{ row }">{{ row.last_diff_pct?.toFixed(2) ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="最大差异%" width="120" align="right">
            <template #default="{ row }">
              <span :style="{ color: '#c53030', fontWeight: 600 }">{{ row.max_diff_pct?.toFixed(2) ?? '—' }}</span>
            </template>
          </el-table-column>
          <template #empty>期内无持续超阈值差异产品</template>
        </el-table>
      </el-card>

      <!-- 最近定时执行 -->
      <el-card v-if="health.recent?.length" shadow="never" class="board-block">
        <template #header>
          <div class="card-header">
            <span>最近定时执行</span>
            <el-button text type="primary" @click="$router.push('/schedule')">任务调度中心</el-button>
          </div>
        </template>
        <el-table :data="health.recent" size="small" stripe>
          <el-table-column prop="module" label="模块" width="70" />
          <el-table-column prop="biz_date" label="业务日期" width="110" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusName(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="280">
            <template #default="{ row }">{{ row.status === 'success' ? statsText(row.stats) : (row.error || '—') }}</template>
          </el-table-column>
          <el-table-column prop="created_by" label="来源" width="180" show-overflow-tooltip />
          <el-table-column prop="finished_at" label="完成时间" width="160" />
        </el-table>
      </el-card>
    </template>

    <el-card shadow="never" class="board-block">
      <template #header>
        <div class="card-header">
          <span>最近任务</span>
          <el-button text type="primary" @click="$router.push('/archive')">全部历史</el-button>
        </div>
      </template>
      <el-table :data="recent" v-loading="loading" stripe>
        <el-table-column prop="module" label="模块" width="70" />
        <el-table-column prop="biz_date" label="业务日期" width="110" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusName(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="统计摘要" min-width="320">
          <template #default="{ row }">{{ statsSummary(row) }}</template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column prop="created_at" label="创建时间" width="160" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import api from '../api'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const loading = ref(false)
const todayJobs = ref([])
const recent = ref([])

/* 看板数据 */
const noPerm = ref(false)
const health = ref({ last30d: {}, recent: [] })
const persistent = ref({ items: [], threshold_pct: 1, days: 7, min_times: 2 })
const trendDays = ref(30)
const trendLoading = ref(false)
const trendEmpty = ref(false)
const trendChart = ref(null)
let chart = null

function today() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

const cards = computed(() => {
  const m1 = todayJobs.value.filter((j) => j.module === 'M1')
  const m3 = todayJobs.value.filter((j) => j.module === 'M3')
  const running = todayJobs.value.filter((j) => ['pending', 'running'].includes(j.status)).length
  const failed = todayJobs.value.filter((j) => j.status === 'failed').length
  return [
    { label: '今日 M1 任务', value: m1.length, color: '#2c5282' },
    { label: '今日 M3 任务', value: m3.length, color: '#2b6cb0' },
    { label: '进行中', value: running, color: '#b7791f' },
    { label: '失败', value: failed, color: failed > 0 ? '#c53030' : '#38a169' },
  ]
})

function statusType(s) {
  return { success: 'success', failed: 'danger', running: 'warning', pending: 'info', wait_file: 'warning', retrying: 'warning' }[s] || 'info'
}
function statusName(s) {
  return { success: '成功', failed: '失败', running: '执行中', pending: '排队中', wait_file: '待文件', retrying: '重试中' }[s] || s
}
function statsSummary(row) {
  if (row.status === 'failed') return row.error ? String(row.error).split('\n')[0] : '执行失败'
  if (!row.stats) return '—'
  return Object.entries(row.stats).map(([k, v]) => `${k} ${v}`).join('，')
}
function statsText(stats) {
  if (!stats) return '成功'
  return Object.entries(stats).map(([k, v]) => `${k} ${v}`).join('，')
}

async function load() {
  loading.value = true
  try {
    const d = today()
    const [todayResp, recentResp] = await Promise.all([
      api.get('/recon/jobs', { params: { date_from: d, date_to: d, page_size: 200 } }),
      api.get('/recon/jobs', { params: { page_size: 5 } }),
    ])
    todayJobs.value = todayResp.data.items
    recent.value = recentResp.data.items
  } finally {
    loading.value = false
  }
}

async function loadHealth() {
  const { data } = await api.get('/dashboard/health')
  health.value = data
}

async function loadPersistent() {
  const { data } = await api.get('/dashboard/persistent-diff', { params: { days: 7, min_times: 2 } })
  persistent.value = data
}

async function loadTrend() {
  trendLoading.value = true
  try {
    const { data } = await api.get('/dashboard/diff-trend', { params: { days: trendDays.value } })
    const pts = data.points || []
    trendEmpty.value = pts.length === 0
    await nextTick()
    if (!chart && trendChart.value) {
      chart = echarts.init(trendChart.value)
    }
    if (chart) {
      const x = pts.map((p) => p.biz_date)
      const seriesOf = (name, key, color) => ({ name, type: 'line', smooth: true, data: pts.map((p) => p[key]), lineStyle: { color }, itemStyle: { color } })
      chart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 50, right: 20, top: 36, bottom: 30 },
        xAxis: { type: 'category', data: x },
        yAxis: { type: 'value', minInterval: 1 },
        series: [
          seriesOf('总记录数', 'total', '#2c5282'),
          seriesOf('精确匹配', 'exact', '#38a169'),
          seriesOf('未匹配', 'unmatched', '#b7791f'),
          seriesOf('差异>1%（非特殊）', 'diff', '#c53030'),
        ],
      }, true)
      chart.resize()
    }
  } finally {
    trendLoading.value = false
  }
}

async function loadBoard() {
  try {
    await Promise.all([loadHealth(), loadPersistent(), loadTrend()])
  } catch (e) {
    if (e.response?.status === 403) noPerm.value = true
  }
}

function onResize() { chart && chart.resize() }

onMounted(() => {
  load()
  loadBoard()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart && chart.dispose()
  chart = null
})
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 30px; font-weight: 700; }
.stat-value.health { color: #2c5282; }
.stat-label { color: #909399; margin-top: 6px; font-size: 13px; }
.board-block { margin-top: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.trend-chart { height: 300px; }
</style>
