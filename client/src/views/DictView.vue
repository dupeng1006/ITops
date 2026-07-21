<template>
  <div class="dict-page">
    <!-- 左栏：模型分组 + 搜索 + 收藏置顶 + 表列表 -->
    <div class="left-panel">
      <el-input
        v-model="keyword"
        placeholder="表名 / 中文名 / 字段名 模糊搜索"
        clearable
        @keyup.enter="search(1)"
        @clear="search(1)"
      >
        <template #append>
          <el-button :icon="Search" @click="search(1)" />
        </template>
      </el-input>

      <el-select
        v-model="modelId"
        placeholder="全部模型（按业务组过滤）"
        clearable
        class="model-filter"
        @change="search(1)"
      >
        <el-option-group v-for="g in modelGroups" :key="g.group" :label="g.group">
          <el-option
            v-for="m in g.items"
            :key="m.id"
            :label="`${m.model_name}（${m.table_count}表）`"
            :value="m.id"
          />
        </el-option-group>
      </el-select>

      <!-- 常用收藏：置顶展示 -->
      <div v-if="favTables.length" class="fav-section">
        <div class="fav-title">
          <el-icon><Star /></el-icon>
          <span>常用收藏</span>
        </div>
        <div class="fav-list">
          <div
            v-for="t in favTables"
            :key="t.table_id"
            class="table-item fav-item"
            :class="{ active: currentTable && currentTable.id === t.table_id }"
            @click="openTable(t.table_id)"
          >
            <div class="table-item-head">
              <span class="table-code">{{ t.table_code }}</span>
              <el-icon
                class="fav-icon faved"
                @click.stop="toggleFav({ id: t.table_id, table_code: t.table_code, table_name: t.table_name, is_favorite: true })"
              ><Star /></el-icon>
            </div>
            <div class="table-name">{{ t.table_name || '—' }}</div>
          </div>
        </div>
      </div>

      <div class="table-list" v-loading="loadingList">
        <div
          v-for="t in tableItems"
          :key="t.id"
          class="table-item"
          :class="{ active: currentTable && currentTable.id === t.id }"
          @click="openTable(t.id)"
        >
          <div class="table-item-head">
            <span class="table-code">{{ t.table_code }}</span>
            <el-icon
              class="fav-icon"
              :class="{ faved: t.is_favorite }"
              @click.stop="toggleFav(t)"
            ><Star /></el-icon>
          </div>
          <div class="table-name">{{ t.table_name || '—' }}</div>
          <div class="table-meta">
            <span class="biz-group">{{ t.biz_group }}</span>
            <el-tag v-if="t.matched_on.includes('column')" size="small" type="success" effect="plain">
              字段命中: {{ t.matched_columns.map(c => c.col_code).slice(0, 2).join(', ') }}
            </el-tag>
          </div>
        </div>
        <el-empty v-if="!loadingList && tableItems.length === 0" description="无匹配表" :image-size="60" />
      </div>

      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        small
        @current-change="search()"
      />
    </div>

    <!-- 右栏 -->
    <div class="right-panel">
      <template v-if="currentTable">
        <!-- 表详情 -->
        <el-card shadow="never" class="detail-card">
          <template #header>
            <div class="detail-head">
              <div>
                <span class="detail-code">{{ currentTable.table_code }}</span>
                <span class="detail-name">{{ currentTable.table_name }}</span>
                <el-tag size="small" effect="plain">{{ currentTable.biz_group }}</el-tag>
              </div>
              <el-button type="primary" size="small" @click="addAllColumns">全选字段加入</el-button>
            </div>
          </template>
          <div v-if="currentTable.comment" class="detail-comment">{{ currentTable.comment }}</div>

          <el-table :data="currentTable.columns" size="small" max-height="300" @selection-change="onColumnSel">
            <el-table-column type="selection" width="40" />
            <el-table-column label="字段" min-width="160">
              <template #default="{ row }">
                <span class="col-code">{{ row.col_code }}</span>
                <el-tag v-if="row.is_pk" size="small" type="warning" effect="dark" class="pk-tag">PK</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="col_name" label="中文名" min-width="140" show-overflow-tooltip />
            <el-table-column prop="data_type" label="类型" width="130" />
            <el-table-column prop="comment" label="注释" min-width="180" show-overflow-tooltip />
          </el-table>

          <!-- 关联表 -->
          <div v-if="refs.as_parent.length || refs.as_child.length" class="ref-box">
            <span class="ref-label">关联表：</span>
            <el-tag
              v-for="r in refs.as_child" :key="'c' + r.id"
              size="small" type="info" effect="plain" class="ref-tag"
              @click="openTable(r.other_id)"
            >父 ← {{ r.other_code }}（{{ r.joins.map(j => j.parent_col).join(',') }}）</el-tag>
            <el-tag
              v-for="r in refs.as_parent" :key="'p' + r.id"
              size="small" type="info" effect="plain" class="ref-tag"
              @click="openTable(r.other_id)"
            >子 → {{ r.other_code }}（{{ r.joins.map(j => j.child_col).join(',') }}）</el-tag>
          </div>
        </el-card>

        <!-- 已选表 + 条件构造 + 生成 -->
        <el-card shadow="never" class="gen-card">
          <template #header>
            <div class="gen-head">
              <span>查询生成器</span>
              <div>
                <el-checkbox v-model="useRownum" style="margin-right: 8px">ROWNUM 限制</el-checkbox>
                <el-input-number v-model="rowLimit" :min="1" :max="100000" size="small" :disabled="!useRownum" style="width: 120px" />
                <el-button type="primary" size="small" :disabled="!selectedTables.length" :loading="generating" @click="genSql">生成 SQL</el-button>
              </div>
            </div>
          </template>

          <div class="selected-tables">
            <span class="ref-label">已选表：</span>
            <el-tag
              v-for="(st, i) in selectedTables" :key="st.id"
              closable size="small" class="fav-tag"
              @close="selectedTables.splice(i, 1)"
            >t{{ i + 1 }} = {{ st.table_code }}（{{ st.columns.length ? st.columns.length + '列' : '全列' }}）</el-tag>
            <span v-if="!selectedTables.length" class="hint">在上方字段表勾选后加入；或直接"全选字段加入"</span>
            <el-button v-else size="small" text type="danger" @click="selectedTables = []">清空</el-button>
            <el-button size="small" text type="primary" :disabled="!selectedColumns.length" @click="addSelectedColumns">加入勾选字段（{{ selectedColumns.length }}）</el-button>
          </div>

          <!-- 条件行 -->
          <div v-for="(cond, i) in conditions" :key="i" class="cond-row">
            <el-select v-model="cond.tableIndex" size="small" style="width: 150px" placeholder="表">
              <el-option v-for="(st, ti) in selectedTables" :key="st.id" :label="`t${ti + 1} ${st.table_code}`" :value="ti" />
            </el-select>
            <el-select v-model="cond.column" size="small" style="width: 190px" placeholder="字段" filterable>
              <el-option v-for="c in condColumns(cond.tableIndex)" :key="c.col_code" :label="`${c.col_code}（${c.col_name || ''}）`" :value="c.col_code" />
            </el-select>
            <el-select v-model="cond.op" size="small" style="width: 110px">
              <el-option v-for="op in OPS" :key="op" :label="op" :value="op" />
            </el-select>
            <el-input
              v-model="cond.value" size="small" style="width: 220px"
              :placeholder="cond.op === 'IN' ? '逗号分隔多值' : cond.op === 'BETWEEN' ? '两值逗号分隔' : cond.op.startsWith('IS') ? '（无需值）' : '条件值'"
              :disabled="cond.op.startsWith('IS')"
            />
            <el-button size="small" text type="danger" :icon="Delete" @click="conditions.splice(i, 1)" />
          </div>
          <el-button size="small" text type="primary" :icon="Plus" :disabled="!selectedTables.length" @click="addCondition">添加条件</el-button>

          <!-- 生成结果 -->
          <template v-if="genResult">
            <el-alert
              v-for="(j, i) in genResult.joins" :key="'j' + i"
              :title="j" type="success" :closable="false" class="gen-alert"
            />
            <el-alert
              v-for="(w, i) in genResult.warnings" :key="'w' + i"
              :title="w" type="warning" :closable="false" class="gen-alert"
            />
            <div class="sql-box">
              <pre class="sql-text">{{ genResult.sql }}</pre>
              <div class="sql-actions">
                <el-button size="small" :icon="CopyDocument" @click="copySql">复制</el-button>
                <el-button v-if="isAdmin" size="small" type="primary" :icon="FolderAdd" @click="saveDialog = true">保存为查询模板</el-button>
              </div>
            </div>
          </template>
        </el-card>
      </template>
      <el-empty v-else description="从左侧选择表，或搜索表名 / 中文名 / 字段名" />
    </div>

    <!-- 保存模板对话框 -->
    <el-dialog v-model="saveDialog" title="保存为查询模板（模块 custom）" width="480px">
      <el-form label-width="80px">
        <el-form-item label="模板名称" required>
          <el-input v-model="saveForm.name" maxlength="100" placeholder="唯一名称" />
        </el-form-item>
        <el-form-item label="数据源" required>
          <el-select v-model="saveForm.ds_id" style="width: 100%" placeholder="执行该 SQL 的目标数据源">
            <el-option v-for="d in datasources" :key="d.id" :label="`${d.name}（${d.db_type}）`" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Delete, FolderAdd, Plus, Search, Star } from '@element-plus/icons-vue'
import api from '../api'
import { getUser } from '../utils/auth'

const OPS = ['=', '!=', '>', '>=', '<', '<=', 'LIKE', 'IN', 'BETWEEN', 'IS NULL', 'IS NOT NULL']
const pageSize = 20

const user = computed(() => getUser())
const isAdmin = computed(() => user.value?.role === 'admin')

const keyword = ref('')
const modelId = ref(null)
const models = ref([])
const tableItems = ref([])
const total = ref(0)
const page = ref(1)
const loadingList = ref(false)

const currentTable = ref(null)
const refs = ref({ as_parent: [], as_child: [] })
const selectedColumns = ref([])
const selectedTables = ref([])   // [{id, table_code, columns: [code...]}]

const conditions = ref([])
const useRownum = ref(true)
const rowLimit = ref(500)
const generating = ref(false)
const genResult = ref(null)

const saveDialog = ref(false)
const saving = ref(false)
const saveForm = ref({ name: '', ds_id: null })
const datasources = ref([])

const favs = ref([])
const favTables = computed(() => favs.value)

const modelGroups = computed(() => {
  const groups = {}
  for (const m of models.value) {
    ;(groups[m.biz_group] = groups[m.biz_group] || []).push(m)
  }
  return Object.entries(groups).map(([group, items]) => ({ group, items }))
})

function isFav(id) {
  return favs.value.some((f) => f.table_id === id)
}

async function loadFavorites() {
  try {
    const resp = await api.get('/dict/favorites')
    favs.value = resp.data
  } catch {
    // 收藏加载失败不阻塞主流程
    favs.value = []
  }
}

async function toggleFav(t) {
  try {
    if (t.is_favorite || isFav(t.id)) {
      await api.delete(`/dict/favorites/${t.id}`)
      ElMessage.success(`已取消收藏 ${t.table_code}`)
    } else {
      await api.post('/dict/favorites', {
        table_id: t.id,
        table_code: t.table_code,
        table_name: t.table_name || null,
      })
      ElMessage.success(`已收藏 ${t.table_code}`)
    }
  } finally {
    await loadFavorites()
    await search()
  }
}

async function loadModels() {
  const resp = await api.get('/dict/models')
  models.value = resp.data
}

async function search(p) {
  if (p) page.value = p
  loadingList.value = true
  try {
    const resp = await api.get('/dict/tables', {
      params: { keyword: keyword.value, model_id: modelId.value || undefined, page: page.value, page_size: pageSize },
    })
    tableItems.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loadingList.value = false
  }
}

async function openTable(id) {
  const [detail, r] = await Promise.all([
    api.get(`/dict/tables/${id}`),
    api.get(`/dict/tables/${id}/references`),
  ])
  currentTable.value = detail.data
  refs.value = r.data
  selectedColumns.value = []
}

function onColumnSel(rows) {
  selectedColumns.value = rows
}

function addSelectedColumns() {
  if (!currentTable.value || !selectedColumns.value.length) return
  const codes = selectedColumns.value.map((c) => c.col_code)
  upsertSelectedTable(codes)
  ElMessage.success(`已加入 ${codes.length} 个字段`)
}

function addAllColumns() {
  if (!currentTable.value) return
  upsertSelectedTable([])
  ElMessage.success(`已加入 ${currentTable.value.table_code}（全列）`)
}

function upsertSelectedTable(codes) {
  const t = currentTable.value
  const exist = selectedTables.value.find((s) => s.id === t.id)
  if (exist) {
    exist.columns = codes
    exist.allColumns = t.columns
  } else {
    selectedTables.value.push({
      id: t.id, table_code: t.table_code, columns: codes, allColumns: t.columns,
    })
  }
}

function condColumns(tableIndex) {
  if (tableIndex === undefined || tableIndex === null || tableIndex === '') return []
  const st = selectedTables.value[tableIndex]
  if (!st) return []
  const detail = st.id === currentTable.value?.id ? currentTable.value : null
  return detail ? detail.columns : (st.allColumns || [])
}

function addCondition() {
  conditions.value.push({ tableIndex: 0, column: '', op: '=', value: '' })
}

async function genSql() {
  generating.value = true
  genResult.value = null
  try {
    const resp = await api.post('/dict/gen-sql', {
      tables: selectedTables.value.map((st, i) => ({
        table_id: st.id, columns: st.columns, alias: `t${i + 1}`,
      })),
      conditions: conditions.value
        .filter((c) => c.column && (c.op.startsWith('IS') || String(c.value).trim() !== ''))
        .map((c) => ({
          table_alias: `t${Number(c.tableIndex) + 1}`,
          column: c.column, op: c.op, value: c.value,
        })),
      limit: rowLimit.value,
      use_rownum: useRownum.value,
    })
    genResult.value = resp.data
  } finally {
    generating.value = false
  }
}

async function copySql() {
  try {
    await navigator.clipboard.writeText(genResult.value.sql)
    ElMessage.success('SQL 已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function saveTemplate() {
  if (!saveForm.value.name.trim() || !saveForm.value.ds_id) {
    ElMessage.warning('请填写模板名称并选择数据源')
    return
  }
  saving.value = true
  try {
    await api.post('/dict/save-template', {
      name: saveForm.value.name.trim(),
      ds_id: saveForm.value.ds_id,
      sql_text: genResult.value.sql,
    })
    ElMessage.success('已保存为查询模板（模块 custom），可在 数据源管理 → 查询模板 中查看')
    saveDialog.value = false
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadModels()
  await loadFavorites()
  await search(1)
  if (isAdmin.value) {
    try {
      const resp = await api.get('/datasources')
      datasources.value = resp.data.filter((d) => d.enabled)
    } catch { /* 数据源列表加载失败不阻塞主流程 */ }
  }
})
</script>

<style scoped>
.dict-page { display: flex; gap: 16px; height: calc(100vh - 110px); }
.left-panel {
  width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px;
  background: #fff; padding: 12px; border-radius: 4px;
}
.model-filter { width: 100%; }
.table-list { flex: 1; overflow-y: auto; }
.table-item {
  padding: 8px 10px; border: 1px solid #e4e7ed; border-radius: 4px;
  margin-bottom: 6px; cursor: pointer;
}
.table-item:hover { border-color: #409eff; }
.table-item.active { border-color: #409eff; background: #ecf5ff; }
.table-item-head { display: flex; justify-content: space-between; align-items: center; }
.table-code { font-weight: 600; color: #303133; font-family: Consolas, monospace; }
.fav-icon { color: #c0c4cc; }
.fav-icon.faved { color: #e6a23c; }
.table-name { font-size: 12px; color: #606266; margin-top: 2px; }
.table-meta { margin-top: 4px; display: flex; gap: 6px; align-items: center; }
.biz-group { font-size: 12px; color: #909399; }
.fav-section { border-bottom: 1px dashed #e4e7ed; padding-bottom: 8px; max-height: 200px; display: flex; flex-direction: column; }
.fav-title { font-size: 13px; color: #e6a23c; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 4px; }
.fav-list { overflow-y: auto; }
.fav-item { background: #fff9ed; border-color: #f5dab1; }
.fav-item:hover { border-color: #e6a23c; }
.fav-tag { margin: 0 6px 6px 0; cursor: pointer; }

.right-panel { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.detail-card, .gen-card { flex-shrink: 0; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-code { font-size: 16px; font-weight: 700; font-family: Consolas, monospace; margin-right: 10px; }
.detail-name { color: #606266; margin-right: 10px; }
.detail-comment {
  font-size: 12px; color: #909399; margin-bottom: 8px;
  white-space: pre-wrap; max-height: 60px; overflow-y: auto;
}
.col-code { font-family: Consolas, monospace; }
.pk-tag { margin-left: 6px; }
.ref-box { margin-top: 8px; }
.ref-label { font-size: 13px; color: #606266; }
.ref-tag { margin: 0 6px 6px 0; cursor: pointer; }
.gen-head { display: flex; justify-content: space-between; align-items: center; }
.selected-tables { margin-bottom: 10px; display: flex; align-items: center; flex-wrap: wrap; }
.hint { font-size: 12px; color: #c0c4cc; }
.cond-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
.gen-alert { margin: 8px 0 0; }
.sql-box {
  margin-top: 10px; background: #1e1e1e; border-radius: 4px; padding: 12px;
  display: flex; justify-content: space-between; gap: 12px;
}
.sql-text {
  color: #d4d4d4; font-family: Consolas, 'Courier New', monospace; font-size: 13px;
  white-space: pre-wrap; word-break: break-all; margin: 0; flex: 1;
}
.sql-actions { display: flex; flex-direction: column; gap: 8px; }
</style>
