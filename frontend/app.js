// 自動偵測 API 位址：同域部署直接用相對路徑，
// 本地開發時（origin 是 localhost）改打 8000 port
const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  ? "http://localhost:8000"
  : "" // 同域部署：相對路徑即可，涵蓋用 IP 或網域存取的情況

const input = document.getElementById("searchInput")
const resultsEl = document.getElementById("results")

let debounceTimer = null
let currentController = null   // 用來取消尚未回來的舊請求，避免 race condition
let lastIssuedQuery = ""       // 記錄最後一次真正送出的查詢字串

const DEBOUNCE_MS = 300
const MIN_QUERY_LENGTH = 1

input.addEventListener("input", () => {
  clearTimeout(debounceTimer)

  const q = input.value.trim()

  if (!q) {
    if (currentController) currentController.abort()
    resultsEl.innerHTML = ""
    return
  }

  if (q.length < MIN_QUERY_LENGTH) {
    return
  }

  debounceTimer = setTimeout(() => {
    search(q)
  }, DEBOUNCE_MS)
})

async function search(q) {
  if (q === lastIssuedQuery && currentController) return

  if (currentController) currentController.abort()
  currentController = new AbortController()
  lastIssuedQuery = q

  showLoading()

  try {
    const response = await fetch(
      `${API_BASE}/search?q=${encodeURIComponent(q)}`,
      { signal: currentController.signal }
    )

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const data = await response.json()

    if (input.value.trim() === q) {
      render(data.results)
    }
  } catch (err) {
    if (err.name === "AbortError") {
      return
    }
    resultsEl.innerHTML = `
      <div class="error">
        搜尋發生錯誤，請稍後再試
      </div>
    `
  }
}

function showLoading() {
  resultsEl.innerHTML = `
    <div class="loading">
      搜尋中…
    </div>
  `
}

function render(results) {
  if (!results.length) {
    resultsEl.innerHTML = `
      <div class="empty">
        沒有找到符合的結果
      </div>
    `
    return
  }

  resultsEl.innerHTML = results.map(r => `
    <div class="card">
      
        <a
          href="${escapeHtml(r.link)}"
        target="_blank"
        rel="noopener noreferrer"
        class="title"
      >
        ${escapeHtml(r.title || "(無標題)")}
      </a>

      <div class="meta">
        ${escapeHtml(r.domain)}
        &nbsp;·&nbsp;
        ${r.published ? escapeHtml(r.published.slice(0, 10)) : ""}
      </div>

      <div class="summary">
        ${escapeHtml((r.summary || "").slice(0, 300))}
      </div>
    </div>
  `).join("")
}

function escapeHtml(text) {
  const div = document.createElement("div")
  div.textContent = text
  return div.innerHTML
}
