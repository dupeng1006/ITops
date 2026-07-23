/**
 * 通用展示格式化工具
 */

/**
 * "修改人"列统一展示：优先显示后端冗余的 updated_by_name（人员姓名），
 * 无该字段时回退 updated_by（用户编号/系统账号）。
 * @param {object} row 列表行数据
 * @returns {string}
 */
export function fmtUpdater(row) {
  if (!row) return ''
  return row.updated_by_name || row.updated_by || ''
}
