const state = {
  settings: null,
  dashboard: null,
  insights: null,
  posts: [],
  selectedRowId: null,
  view: "collection",
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function tagClass(label) {
  const text = String(label || "").toLowerCase();
  if (text.includes("负") || text.includes("negative") || text.includes("高")) return "negative high";
  if (text.includes("正") || text.includes("positive")) return "positive";
  if (text.includes("中") || text.includes("neutral")) return "neutral medium";
  return "";
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return response.json();
}

async function loadAll() {
  const scope = $("#scopeSelect").value;
  const [health, settings, dashboard, insights] = await Promise.all([
    fetchJson("/api/health"),
    fetchJson("/api/settings"),
    fetchJson(`/api/dashboard?scope=${encodeURIComponent(scope)}`),
    fetchJson(`/api/insights?scope=${encodeURIComponent(scope)}`),
  ]);
  state.settings = settings;
  state.dashboard = dashboard;
  state.insights = insights;
  state.posts = dashboard.posts || [];
  $("#healthDot").classList.add("ok");
  $("#healthText").textContent = `在线 · ${health.sqlite_files} DB · ${health.artifacts} 产物`;
  renderCollection();
  renderFilters();
  renderDashboard();
  renderInsights();
}

function renderCollection() {
  const settings = state.settings;
  if (!settings) return;
  $("#collectionTime").value = settings.schedule.collection_time || "07:00";
  $("#windowHours").value = settings.schedule.collection_window_hours || 24;
  $("#reportTime").value = settings.schedule.report_time || "08:00";
  $("#providerSelect").value = settings.schedule.collection_provider || "tikhub";
  $("#commandTemplate").textContent = [
    settings.command_template,
    "",
    "PYTHONPATH=src python3 -m reddit_voc.cli send-daily-report-live \\",
    "  --database data/reddit_voc_daily.sqlite3 \\",
    "  --output-dir outputs \\",
    "  --run-id <run_id> \\",
    "  --artifact-base-url <reachable-artifact-base-url> \\",
    "  --required-keyword LL \\",
    "  --authorize-live-send",
  ].join("\n");

  const tiers = settings.subreddits.tiers || {};
  $("#subredditTiers").innerHTML = Object.entries(tiers)
    .map(([tier, items]) => `
      <div class="tier-item">
        <div>
          <strong>${escapeHtml(tier.toUpperCase())}</strong>
          <div class="muted">${items.map((item) => `r/${escapeHtml(item.name)}`).join(" · ")}</div>
        </div>
        <span class="tag">${items.length}</span>
      </div>
    `)
    .join("");

  const counts = settings.keywords.counts || {};
  $("#keywordSummary").innerHTML = Object.entries(counts)
    .map(([key, value]) => `
      <div class="keyword-item">
        <span>${escapeHtml(key)}</span>
        <span class="tag">${escapeHtml(value)}</span>
      </div>
    `)
    .join("");
}

function renderFilters() {
  const filters = state.dashboard?.filters || {};
  const fill = (selector, values, label) => {
    const current = $(selector).value;
    $(selector).innerHTML = `<option value="">${label}</option>` + (values || [])
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join("");
    $(selector).value = current;
  };
  fill("#subredditFilter", filters.subreddits, "全部社区");
  fill("#sentimentFilter", filters.sentiments, "全部情感");
  fill("#severityFilter", filters.severities, "全部严重度");
}

function filteredPosts() {
  const query = $("#searchInput").value.trim().toLowerCase();
  const subreddit = $("#subredditFilter").value;
  const sentiment = $("#sentimentFilter").value;
  const severity = $("#severityFilter").value;
  return state.posts.filter((post) => {
    if (subreddit && post.subreddit !== subreddit) return false;
    if (sentiment && post.sentiment_label_cn !== sentiment) return false;
    if (severity && post.severity_cn !== severity) return false;
    if (!query) return true;
    const haystack = [
      post.title,
      post.title_zh,
      post.selftext,
      post.selftext_zh,
      post.comments_merged,
      post.comments_merged_zh,
      (post.matched_keywords_list || []).join(" "),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderDashboard() {
  const posts = filteredPosts();
  const totals = state.dashboard?.totals || {};
  $("#postMetric").textContent = `${totals.posts || 0} 帖`;
  $("#commentMetric").textContent = `${totals.comments || 0} 评论`;
  $("#postsTable").innerHTML = posts.map((post) => `
    <tr data-row-id="${escapeHtml(post.row_id)}" class="${post.row_id === state.selectedRowId ? "active" : ""}">
      <td>${escapeHtml(formatDate(post.created_at_utc))}</td>
      <td>r/${escapeHtml(post.subreddit)}</td>
      <td>
        <span class="post-title">${escapeHtml(post.title_zh || post.title)}</span>
        <span class="muted">${escapeHtml(post.title_zh ? post.title : post.selftext || "")}</span>
      </td>
      <td><span class="tag ${tagClass(post.sentiment_label_cn)}">${escapeHtml(post.sentiment_label_cn)}</span></td>
      <td>${escapeHtml(post.topic || "未分类")}</td>
      <td>${escapeHtml((post.comments || []).length)}</td>
      <td><span class="tag">${escapeHtml(post.coverage_grade || "unknown")}</span></td>
    </tr>
  `).join("");

  $("#postsTable").querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedRowId = row.dataset.rowId;
      const post = state.posts.find((item) => item.row_id === state.selectedRowId);
      renderDrawer(post);
      renderDashboard();
    });
  });

  if (!state.selectedRowId && posts[0]) {
    state.selectedRowId = posts[0].row_id;
    renderDrawer(posts[0]);
  }
}

function renderDrawer(post) {
  if (!post) return;
  $("#drawerTitle").textContent = post.title_zh || post.title || "未命名帖子";
  $("#drawerLink").href = post.source_url || "#";
  const comments = post.comments || [];
  $("#drawerContent").innerHTML = `
    <div>
      <strong>帖子正文中文</strong>
      <p>${escapeHtml(post.selftext_zh || "未生成中文翻译")}</p>
    </div>
    <div>
      <strong>帖子正文原文</strong>
      <p>${escapeHtml(post.selftext || "无正文")}</p>
    </div>
    <div>
      <strong>同帖评论整合</strong>
      ${comments.length ? comments.map((comment, index) => `
        <div class="comment-block">
          <div class="muted">#${index + 1} · ${escapeHtml(formatDate(comment.created_at_utc))} · ${escapeHtml(comment.sentiment_label_cn || "未知")}</div>
          <div>${escapeHtml(comment.body)}</div>
        </div>
      `).join("") : "<p class=\"muted\">当前样本没有解析评论。</p>"}
    </div>
    ${post.comments_merged_zh ? `<div><strong>评论整合中文</strong><p>${escapeHtml(post.comments_merged_zh)}</p></div>` : ""}
  `;
}

function renderBars(selector, data) {
  const entries = Object.entries(data || {});
  const max = Math.max(1, ...entries.map(([, value]) => Number(value) || 0));
  $(selector).innerHTML = entries.length ? entries.map(([label, value]) => {
    const width = Math.max(4, Math.round((Number(value) / max) * 100));
    return `
      <div class="bar-row">
        <span>${escapeHtml(label)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${width}%"></span></span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `;
  }).join("") : "<p class=\"muted\">暂无数据</p>";
}

function renderInsights() {
  const insights = state.insights;
  if (!insights) return;
  $("#insightScopeBadge").textContent = $("#scopeSelect").value === "latest" ? "最近批次" : "历史累计";
  $("#storyLines").innerHTML = (insights.story || [])
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
  renderBars("#sentimentChart", insights.metrics?.sentiment);
  renderBars("#topicChart", insights.metrics?.topics);
  renderBars("#painChart", insights.metrics?.pain_points);

  const report = insights.artifacts?.latest_report;
  if (report) {
    $("#reportFrame").src = report.url;
    $("#reportLink").href = report.url;
    $("#reportLink").textContent = `打开 ${report.name}`;
  } else {
    $("#reportFrame").removeAttribute("src");
    $("#reportLink").removeAttribute("href");
    $("#reportLink").textContent = "暂无 HTML 报告";
  }

  $("#artifactList").innerHTML = (insights.artifacts?.recent || [])
    .slice(0, 12)
    .map((item) => `
      <div class="artifact-item">
        <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}</a>
        <span class="tag">${escapeHtml(item.suffix)}</span>
      </div>
    `)
    .join("");
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
      $(`#${state.view}View`).classList.add("active");
    });
  });
  $("#refreshBtn").addEventListener("click", () => loadAll().catch(showError));
  $("#scopeSelect").addEventListener("change", () => {
    state.selectedRowId = null;
    loadAll().catch(showError);
  });
  ["#searchInput", "#subredditFilter", "#sentimentFilter", "#severityFilter"].forEach((selector) => {
    $(selector).addEventListener("input", renderDashboard);
    $(selector).addEventListener("change", renderDashboard);
  });
}

function showError(error) {
  $("#healthDot").classList.remove("ok");
  $("#healthDot").classList.add("error");
  $("#healthText").textContent = `异常 · ${error.message}`;
}

bindEvents();
loadAll().catch(showError);
