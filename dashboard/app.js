const APP_VERSION = "20260822-8";
const CHECKER_STORAGE_KEY = "odds-analyzer-checker-v1";

const state = {
  currentMatches: [],
  mismatchHistory: [],
  checkerHistory: [],
  nextMatchday: { generated_at: null, competitions: [] },
  analysisCompetitionCodes: ["PL"],
  activeView: "detail",
  checker: {},
  pages: {
    mismatch: 1,
    checker: 1,
  },
};

const elements = {
  slateDate: document.querySelector("#slateDate"),
  slateWindow: document.querySelector("#slateWindow"),
  totalMatches: document.querySelector("#totalMatches"),
  mismatchMatches: document.querySelector("#mismatchMatches"),
  pendingMatches: document.querySelector("#pendingMatches"),
  checkerCount: document.querySelector("#checkerCount"),
  viewButtons: document.querySelectorAll(".view-button"),
  runStatusLabel: document.querySelector("#runStatusLabel"),
  runType: document.querySelector("#runType"),
  runUpdatedAt: document.querySelector("#runUpdatedAt"),
  runLink: document.querySelector("#runLink"),
  viewEyebrow: document.querySelector("#viewEyebrow"),
  viewTitle: document.querySelector("#viewTitle"),
  viewCounter: document.querySelector("#viewCounter"),
  viewBody: document.querySelector("#viewBody"),
};

async function loadDashboard() {
  const response = await fetch(`./data/daily_matches.json?v=${APP_VERSION}-${Date.now()}`);
  const payload = await response.json();
  const normalized = normalizePayload(payload);
  state.currentMatches = normalized.currentMatches;
  state.mismatchHistory = normalized.mismatchHistory;
  state.checkerHistory = normalized.checkerHistory;
  state.nextMatchday = normalized.nextMatchday;
  state.analysisCompetitionCodes = normalized.analysisCompetitionCodes;
  state.checker = loadChecker();
  elements.slateDate.textContent = payload.slate.date;
  const scope = payload.slate.analysis_scope ?? competitionScopeLabel(normalized.analysisCompetitionCodes);
  elements.slateWindow.textContent = payload.slate.window + " · 分析：" + scope;
  loadRunStatus();
  render();
}

async function loadRunStatus() {
  try {
    const response = await fetch(`./data/run_status.json?v=${APP_VERSION}-${Date.now()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderRunStatus(await response.json());
  } catch {
    renderRunStatus({ status: "unknown", run_type: "--", updated_at: null, run_id: null });
  }
}

function renderRunStatus(status) {
  const label = status.status ?? "unknown";
  elements.runStatusLabel.textContent = formatRunStatus(label);
  elements.runStatusLabel.className = `run-state ${normalizeText(label)}`;
  elements.runType.textContent = status.run_type ?? status.trigger ?? "--";
  elements.runUpdatedAt.textContent = formatRunTime(status.updated_at);
  if (status.run_id && status.run_id !== "local-seed") {
    elements.runLink.href = `https://github.com/linyinzhou/odds-analyzer/actions/runs/${status.run_id}`;
    elements.runLink.textContent = `#${status.run_id}`;
  } else {
    elements.runLink.href = "https://github.com/linyinzhou/odds-analyzer/actions";
    elements.runLink.textContent = "Actions";
  }
}

function normalizePayload(payload) {
  const analysisCompetitionCodes = normalizeAnalysisCompetitionCodes(payload.slate?.analysis_competitions);
  const inScope = (match) => matchInAnalysisScope(match, analysisCompetitionCodes);
  const allCurrentMatches = payload.current_matches ?? payload.matches ?? [];
  const currentMatches = allCurrentMatches.filter(inScope);
  const mismatchHistory = (payload.mismatch_history ?? allCurrentMatches.filter((match) => match.mismatch?.matched)).filter(inScope);
  const checkerHistory = (payload.checker_history ?? getTopCheckerCandidates(currentMatches)).filter(inScope);
  const nextMatchday = payload.next_matchday ?? { generated_at: null, competitions: [] };
  return {
    currentMatches,
    mismatchHistory,
    checkerHistory,
    nextMatchday,
    analysisCompetitionCodes,
  };
}

function normalizeAnalysisCompetitionCodes(codes) {
  const supported = ["PL", "PD", "SA", "BL1", "FL1", "CL"];
  const normalized = Array.isArray(codes) ? codes.filter((code) => supported.includes(code)) : [];
  return normalized.length ? normalized : ["PL"];
}

function matchInAnalysisScope(match, codes) {
  const snapshotCode = match.football_data_snapshot?.competition_code;
  if (snapshotCode) return codes.includes(snapshotCode);
  const labels = { PL: "英超", PD: "西甲", SA: "意甲", BL1: "德甲", FL1: "法甲", CL: "欧冠" };
  return codes.some((code) => String(match.competition ?? "").startsWith(labels[code]));
}

function competitionScopeLabel(codes) {
  const labels = { PL: "英超", PD: "西甲", SA: "意甲", BL1: "德甲", FL1: "法甲", CL: "欧冠" };
  return codes.map((code) => labels[code]).filter(Boolean).join(" + ");
}

function render() {
  renderSummary();
  renderActiveButton();
  if (state.activeView === "mismatch") {
    renderMismatchView();
    return;
  }
  if (state.activeView === "checker") {
    renderCheckerView();
    return;
  }
  if (state.activeView === "schedule") {
    renderScheduleView();
    return;
  }
  renderDetailView();
}

function renderSummary() {
  const mismatchMatches = state.mismatchHistory.length;
  const pendingMatches = state.currentMatches.filter((match) => match.status === "pending").length;
  const checkerIds = new Set(getCheckerMatches().map((match) => match.id));
  const reviews = getCheckerMatches().map(getCheckerReview).filter((review) => checkerIds.has(review.id));
  const reviewed = reviews.filter((review) => review.reviewed && !review.void).length;
  const hits = reviews.filter((review) => review.reviewed && review.hit).length;

  elements.totalMatches.textContent = String(state.currentMatches.length);
  elements.mismatchMatches.textContent = String(mismatchMatches);
  elements.pendingMatches.textContent = String(pendingMatches);
  elements.checkerCount.textContent = `${hits}/${reviewed}`;
}

function renderActiveButton() {
  elements.viewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.activeView);
  });
}

function renderDetailView() {
  const matches = [...state.currentMatches].sort(sortByKickoffAsc);
  elements.viewEyebrow.textContent = "Detail";
  elements.viewTitle.textContent = "详细栏";
  elements.viewCounter.textContent = `${matches.length} 场`;
  elements.viewBody.innerHTML = `
    <div class="report-list">
      ${matches.map(renderMatchReport).join("")}
    </div>
  `;
}

function renderMatchReport(match) {
  return `
    <details class="match-report">
      <summary class="report-head">
        <div>
          <span>${match.competition}</span>
          <h3>${match.competition} ${match.home_team} vs ${match.away_team} · ${match.kickoff_time}</h3>
        </div>
        <em class="tag ${match.status}">${match.signal_label}</em>
      </summary>

      <div class="report-content">
        <div class="info-grid">
          <div><span>场地</span><strong>${match.venue}</strong></div>
          <div><span>天气</span><strong>${match.weather}</strong></div>
          <div><span>欧赔</span><strong>${formatThreeWay(match.european_odds)}</strong></div>
          <div><span>竞彩</span><strong>${formatLottery(match.chinese_lottery)}</strong></div>
        </div>

        ${renderSideBySide(match)}
        ${renderMarkets(match)}

        <section class="recommendation">
          <h4>建议</h4>
          <p><strong>最终：</strong>${formatPrediction(match)}</p>
          <p><strong>基本面：</strong>${match.recommendation.fundamental}</p>
          <p><strong>错盘：</strong>${match.recommendation.mismatch}</p>
          <p><strong>风险：</strong>${match.risks.join("；")}</p>
        </section>

        <p class="muted">来源：${match.sources.join("；")}</p>
      </div>
    </details>
  `;
}

function renderSideBySide(match) {
  return `
    <section>
      <h4>基本面对比</h4>
      <table class="compare-table">
        <thead>
          <tr>
            <th>${match.home_team}</th>
            <th>${match.away_team}</th>
          </tr>
        </thead>
        <tbody>
          ${match.fundamentals
            .map(
              (row) => `
                <tr>
                  <td>${row.home}</td>
                  <td>${row.away}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function renderMarkets(match) {
  return `
    <section>
      <h4>盘口</h4>
      <div class="market-grid">
        <div><span>欧赔</span><strong>${formatThreeWay(match.european_odds)}</strong></div>
        <div><span>亚盘</span><strong>${formatAsian(match.asian_handicap)}</strong></div>
        <div><span>竞彩</span><strong>${formatLottery(match.chinese_lottery)}</strong></div>
      </div>
      <p class="market-read">${match.market_read}</p>
    </section>
  `;
}

function renderMismatchView() {
  const matches = [...state.mismatchHistory].sort(sortByKickoffDesc);
  const paged = paginate(matches, state.pages.mismatch);
  elements.viewEyebrow.textContent = "Mismatch";
  elements.viewTitle.textContent = "错盘栏";
  elements.viewCounter.textContent = `${matches.length} 场`;
  elements.viewBody.innerHTML =
    paged.items
      .map(
        (match) => `
          <article class="mismatch-row">
            <header>
              <span>${match.kickoff_time} · ${match.competition}</span>
              <h3>${match.home_team} vs ${match.away_team}</h3>
            </header>
            <div class="market-grid">
              <div><span>欧赔</span><strong>${formatThreeWay(match.european_odds)}</strong></div>
              <div><span>亚盘</span><strong>${formatAsian(match.asian_handicap)}</strong></div>
              <div><span>竞彩</span><strong>${formatLottery(match.chinese_lottery)}</strong></div>
            </div>
            <p>${match.mismatch.reason}</p>
            <strong class="pick">${match.mismatch.pick}</strong>
          </article>
        `,
      )
      .join("") || `<p class="empty">当前没有命中错盘规则的比赛。</p>`;
  elements.viewBody.insertAdjacentHTML("beforeend", renderPagination("mismatch", paged));
  bindPagination();
}


function renderScheduleView() {
  const currentFixtureKeys = new Set(state.currentMatches.map(fixtureIdentity));
  const competitions = (state.nextMatchday.competitions ?? []).map((competition) => ({
    ...competition,
    fixtures: (competition.fixtures ?? []).filter((fixture) => !currentFixtureKeys.has(fixtureIdentity(fixture))),
  }));
  const fixtureCount = competitions.reduce((total, competition) => total + (competition.fixtures?.length ?? 0), 0);
  elements.viewEyebrow.textContent = "Schedule";
  elements.viewTitle.textContent = "下个比赛日";
  elements.viewCounter.textContent = `${fixtureCount} 场`;
  elements.viewBody.innerHTML = `
    <div class="schedule-note">
      <span>范围</span>
      <strong>五大联赛 + 欧冠正赛</strong>
      <p>${state.nextMatchday.scope_note ?? "只显示联赛、对阵和日期；到比赛日再生成详细报告。"}</p>
    </div>
    <div class="schedule-list">
      ${competitions.map(renderCompetitionSchedule).join("") || `<p class="empty">暂无下个比赛日赛程。</p>`}
    </div>
  `;
}

function renderCompetitionSchedule(competition) {
  const fixtures = competition.fixtures ?? [];
  return `
    <article class="schedule-competition">
      <header>
        <div>
          <span>${competition.country ?? "欧洲"}</span>
          <h3>${competition.name}</h3>
        </div>
        <em class="tag ${fixtures.length ? "watch" : "pending"}">${competition.matchday ?? competition.status ?? "待更新"}</em>
      </header>
      ${fixtures.length ? `<div class="fixture-table">${fixtures.map((fixture) => renderFixtureRow(fixture, competition.name)).join("")}</div>` : `<p class="empty">${competition.status ?? "待赛程源接入。"}</p>`}
    </article>
  `;
}

function renderFixtureRow(fixture, competitionName) {
  return `
    <div class="fixture-row">
      <span>${competitionName}</span>
      <strong>${fixture.home_team} vs ${fixture.away_team}</strong>
      <em>${fixture.kickoff_time}</em>
    </div>
  `;
}
function renderCheckerView() {
  const matches = getCheckerMatches();
  const checkerIds = new Set(matches.map((match) => match.id));
  const reviews = getCheckerMatches().map(getCheckerReview).filter((review) => checkerIds.has(review.id));
  const reviewed = reviews.filter((review) => review.reviewed && !review.void).length;
  const hits = reviews.filter((review) => review.reviewed && review.hit).length;
  const paged = paginate(matches, state.pages.checker);
  const learning = buildLearningSummary();
  elements.viewEyebrow.textContent = "Checker";
  elements.viewTitle.textContent = "赛后复盘";
  elements.viewCounter.textContent = `${hits}/${reviewed} 命中`;
  elements.viewBody.innerHTML = `
    <div class="checker-tools">
      <span>只显示当前批次胜率排序靠前的 ${matches.length} 场</span>
      <strong>已复盘 ${reviewed} 场，命中 ${hits} 场</strong>
    </div>
    ${renderLearningSummary(learning)}
    <div class="checker-list">
      ${paged.items.map(renderCheckerItem).join("")}
    </div>
    ${renderPagination("checker", paged)}
  `;
  bindCheckerInputs();
  bindPagination();
}

function renderCheckerItem(match) {
  const item = getCheckerReview(match);
  return `
    <article class="checker-item">
      <header>
        <div>
          <span>${match.kickoff_time} · ${match.competition}</span>
          <h3>${match.home_team} vs ${match.away_team}</h3>
        </div>
        <em class="tag ${match.status}">${match.signal_label}</em>
      </header>
      <p>${match.checker}</p>
      <p><strong>最终建议：</strong>${formatPrediction(match)}</p>
      <div class="checker-result">
        <label>
          <span>赛果</span>
          <input data-field="score" data-id="${match.id}" value="${escapeAttribute(item.score ?? item.final_score ?? "")}" placeholder="例：1-1" />
        </label>
        <label>
          <span>复盘</span>
          <select data-field="review" data-id="${match.id}">
            <option value="" ${!item.reviewed ? "selected" : ""}>待复盘</option>
            <option value="hit" ${item.reviewed && item.hit ? "selected" : ""}>命中</option>
            <option value="miss" ${item.reviewed && !item.hit && !item.void ? "selected" : ""}>未中</option>
            <option value="void" ${item.reviewed && item.void ? "selected" : ""}>走盘</option>
          </select>
        </label>
        <label class="checker-note">
          <span>备注</span>
          <input data-field="note" data-id="${match.id}" value="${escapeAttribute(item.note ?? item.review_note ?? "")}" placeholder="盘口变化、阵容、赛果原因" />
        </label>
      </div>
    </article>
  `;
}

function bindCheckerInputs() {
  document.querySelectorAll("[data-field]").forEach((field) => {
    field.addEventListener("change", () => updateChecker(field));
  });
}

function updateChecker(field) {
  const id = field.dataset.id;
  const current = state.checker[id] ?? {};
  if (field.dataset.field === "score") current.score = field.value.trim();
  if (field.dataset.field === "note") current.note = field.value.trim();
  if (field.dataset.field === "review") {
    current.reviewed = field.value !== "";
    current.void = field.value === "void";
    current.hit = current.void ? null : field.value === "hit";
  }
  state.checker[id] = current;
  saveChecker();
  renderSummary();
  if (state.activeView === "checker") renderCheckerView();
}

function loadChecker() {
  try {
    return JSON.parse(localStorage.getItem(CHECKER_STORAGE_KEY)) ?? {};
  } catch {
    return {};
  }
}

function saveChecker() {
  localStorage.setItem(CHECKER_STORAGE_KEY, JSON.stringify(state.checker));
}

function buildLearningSummary() {
  const reviewed = state.checkerHistory
    .map((match) => ({ match, review: getCheckerReview(match) }))
    .filter((item) => item.review?.reviewed && !item.review?.void);

  const groups = [
    {
      label: "全部建议",
      rows: reviewed,
    },
    {
      label: "错盘命中规则",
      rows: reviewed.filter((item) => item.match.mismatch?.matched),
    },
    {
      label: "非错盘建议",
      rows: reviewed.filter((item) => !item.match.mismatch?.matched),
    },
  ];

  return groups.map((group) => {
    const total = group.rows.length;
    const hits = group.rows.filter((item) => item.review.hit).length;
    return {
      label: group.label,
      total,
      hits,
      rate: total ? Math.round((hits / total) * 100) : null,
    };
  });
}

function renderLearningSummary(groups) {
  return `
    <section class="learning-panel">
      <div>
        <span>学习样本</span>
        <strong>按复盘结果更新规则表现</strong>
      </div>
      <div class="learning-grid">
        ${groups
          .map(
            (group) => `
              <article>
                <span>${group.label}</span>
                <strong>${group.total ? `${group.hits}/${group.total}` : "--"}</strong>
                <em>${group.rate === null ? "待积累" : `${group.rate}%`}</em>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function getCheckerMatches() {
  return [...state.checkerHistory].sort(sortCheckerHistory);
}

function getCheckerReview(match) {
  return {
    id: match.id,
    ...(state.checker[match.id] ?? {}),
    ...(match.review ?? {}),
  };
}

function getTopCheckerCandidates(matches) {
  const sorted = [...matches].sort((a, b) => predictionConfidence(b) - predictionConfidence(a));
  const limit = matches.length <= 5 ? Math.min(3, matches.length) : Math.min(8, matches.length);
  return sorted.slice(0, limit);
}

function predictionConfidence(match) {
  return match.prediction?.confidence ?? impliedTopProbability(match) * 100;
}

function impliedTopProbability(match) {
  const odds = match.european_odds;
  if (!odds) return 0;
  return Math.max(1 / odds.home, 1 / odds.draw, 1 / odds.away);
}

function paginate(items, page, pageSize = 10) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const start = (currentPage - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page: currentPage,
    totalPages,
  };
}

function renderPagination(view, paged) {
  if (paged.totalPages <= 1) return "";
  return `
    <div class="pagination">
      <button data-page-view="${view}" data-page-dir="-1" ${paged.page === 1 ? "disabled" : ""}>上一页</button>
      <span>${paged.page} / ${paged.totalPages}</span>
      <button data-page-view="${view}" data-page-dir="1" ${paged.page === paged.totalPages ? "disabled" : ""}>下一页</button>
    </div>
  `;
}

function bindPagination() {
  document.querySelectorAll("[data-page-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const view = button.dataset.pageView;
      state.pages[view] += Number(button.dataset.pageDir);
      render();
    });
  });
}

function sortCheckerHistory(a, b) {
  return (
    historyBatchKey(b).localeCompare(historyBatchKey(a)) ||
    predictionConfidence(b) - predictionConfidence(a) ||
    kickoffKey(a).localeCompare(kickoffKey(b))
  );
}

function historyBatchKey(match) {
  return match.batch_date ?? match.generated_at ?? kickoffKey(match).slice(0, 5);
}

function fixtureIdentity(fixture) {
  return `${normalizeText(fixture.home_team)}|${normalizeText(fixture.away_team)}|${fixture.kickoff_time ?? ""}`;
}

function normalizeText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function sortByKickoffAsc(a, b) {
  return kickoffKey(a).localeCompare(kickoffKey(b));
}

function sortByKickoffDesc(a, b) {
  return kickoffKey(b).localeCompare(kickoffKey(a));
}

function kickoffKey(match) {
  return match.kickoff_time.replace(" ", "-");
}

function formatThreeWay(odds) {
  if (!odds) return "待补";
  return `${odds.home.toFixed(2)} / ${odds.draw.toFixed(2)} / ${odds.away.toFixed(2)}`;
}

function formatAsian(asian) {
  if (!asian) return "待补";
  return `${formatLine(asian.handicap)} ${asian.home_odds.toFixed(2)} / ${asian.away_odds.toFixed(2)} · ${asian.provider}`;
}

function formatLottery(lottery) {
  if (!lottery) return "待补";
  if (lottery.handicap === null) return `胜平负 ${formatThreeWay(lottery.standard)}`;
  return `让 ${formatLine(lottery.handicap)}：${formatThreeWay(lottery.handicap_odds)}`;
}

function formatPrediction(match) {
  if (!match.prediction) return "待补";
  return `${match.prediction.market}：${match.prediction.pick}（信心 ${match.prediction.confidence}%）`;
}

function formatLine(value) {
  if (value > 0) return `+${value}`;
  return String(value);
}

function formatRunStatus(value) {
  if (value === "success") return "Success";
  if (value === "failure") return "Failed";
  if (value === "cancelled") return "Cancelled";
  if (value === "in_progress") return "Running";
  return "Unknown";
}

function formatRunTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function escapeAttribute(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
}

elements.viewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.activeView = button.dataset.view;
    render();
  });
});

loadDashboard().catch((error) => {
  elements.viewBody.innerHTML = `<p class="empty">数据加载失败：${error.message}</p>`;
});
