/**
 * 轻量 Markdown 渲染（仅链接 + 换行），用于卡片描述等不可信文本的安全展示：
 * 1. 先做 HTML 转义（防 XSS）；
 * 2. [文本](url) 或 [文本](url "title") 渲染为 <a>文本</a>；
 * 3. 裸 http(s) URL 渲染为 <a>域名</a>（只显示域名，避免长 URL 撑破卡片）；
 * 4. 换行符转为 <br>。
 */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function domainOf(url) {
  try {
    return new URL(url).hostname || url
  } catch {
    return url
  }
}

function anchor(url, text, title) {
  const titleAttr = title ? ` title="${title}"` : ''
  return `<a href="${url}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`
}

/**
 * 将 Markdown 描述文本渲染为安全 HTML。
 * @param {string} text 原始文本
 * @returns {string} 可 v-html 输出的 HTML
 */
export function renderMarkdownLite(text) {
  if (!text) return ''
  let html = escapeHtml(text)

  // 1. Markdown 链接：[文本](url) / [文本](url "title")，先替换为占位符，避免与裸 URL 规则冲突
  const anchors = []
  html = html.replace(/\[([^\]]*)\]\((https?:\/\/[^\s)]+?)(?:\s+&quot;(.*?)&quot;)?\)/g,
    (_m, label, url, title) => {
      anchors.push(anchor(url, label || domainOf(url), title))
      return `\x00MDLINK${anchors.length - 1}\x00`
    })

  // 2. 裸 URL → <a>域名</a>（排除紧邻引号/等号的，避免命中已生成 HTML 属性；占位符不含 URL，安全）
  html = html.replace(/(?<!["'=])(https?:\/\/[^\s<]+)/g, (m) => {
    // 去掉末尾常见标点（如 )。，；），避免把标点包进链接
    const trail = m.match(/[).,;，。；、]+$/)
    const clean = trail ? m.slice(0, -trail[0].length) : m
    return anchor(clean, domainOf(clean)) + (trail ? trail[0] : '')
  })

  // 3. 还原占位符
  html = html.replace(/\x00MDLINK(\d+)\x00/g, (_m, i) => anchors[Number(i)])

  // 4. 换行
  return html.replace(/\n/g, '<br>')
}
