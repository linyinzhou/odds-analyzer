const APP_VERSION = "20260913-mismatch-parlays-1";
const CHECKER_STORAGE_KEY = "odds-analyzer-checker-v1";

const state = {
  currentMatches: [],
  mismatchHistory: [],
  checkerHistory: [],
  adhocHistory: [],
  fallbackRequests: [],
  strategyPerformance: { minimum_sample: 20, strategies: {} },
  learningEvaluation: null,
  nextMatchday: { generated_at: null, competitions: [] },
  analysisCompetitionCodes: ["PL", "PD", "SA"],
  activeView: "detail",
  checker: {},
  pages: {
    mismatch: 1,
    checker: 1,
    adhoc: 1,
  },
};

const elements = {
  slateDate: document.querySelector("#slateDate"),
  slateWindow: document.querySelector("#slateWindow"),
  totalMatches: document.querySelector("#totalMatches"),
  mismatchMatches: document.querySelector("#mismatchMatches"),
  pendingMatches: document.querySelector("#pendingMatches"),
  checkerCount: document.querySelector("#checkerCount"),
  fallbackCount: document.querySelector("#fallbackCount"),
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
  state.adhocHistory = normalized.adhocHistory;
  state.fallbackRequests = normalized.fallbackRequests;
  state.strategyPerformance = normalized.strategyPerformance;
  state.learningEvaluation = normalized.learningEvaluation;
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
  const mismatchHistory = currentMatches.filter((match) => match.mismatch?.matched === true);
  const checkerHistory = (payload.checker_history ?? getTopCheckerCandidates(currentMatches)).filter(inScope);
  const adhocHistory = payload.adhoc_history ?? [];
  const fallbackRequests = payload.fallback_requests ?? [];
  const nextMatchday = payload.next_matchday ?? { generated_at: null, competitions: [] };
  const strategyPerformance = payload.strategy_performance ?? { minimum_sample: 20, strategies: {} };
  return {
    currentMatches,
    mismatchHistory,
    checkerHistory,
    adhocHistory,
    fallbackRequests,
    strategyPerformance,
    learningEvaluation: payload.learning_evaluation ?? null,
    nextMatchday,
    analysisCompetitionCodes,
  };
}

function normalizeAnalysisCompetitionCodes(codes) {
  const supported = ["PL", "PD", "SA", "BL1", "FL1", "CL"];
  const normalized = Array.isArray(codes) ? codes.filter((code) => supported.includes(code)) : [];
  return normalized.length ? normalized : ["PL", "PD", "SA"];
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
  if (state.activeView === "adhoc") {
    renderAdhocView();
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
  elements.fallbackCount.textContent = String(state.fallbackRequests.filter((item) => item.status === "pending").length);
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

function renderAdhocView() {
  const matches = [...state.adhocHistory].sort(
    (a, b) => String(b.generated_at ?? "").localeCompare(String(a.generated_at ?? "")) || sortByKickoffDesc(a, b),
  );
  const paged = paginate(matches, state.pages.adhoc);
  elements.viewEyebrow.textContent = "Ad Hoc";
  elements.viewTitle.textContent = "自选比赛";
  elements.viewCounter.textContent = `${matches.length} 场`;
  elements.viewBody.innerHTML = `
    <div class="report-list">
      ${paged.items.map(renderMatchReport).join("") || `<p class="empty">暂无自选比赛报告。请从“手动更新”选择 adhoc-report 生成。</p>`}
    </div>
    ${renderPagination("adhoc", paged)}
  `;
  bindPagination();
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
        ${renderTeamNews(match)}
        ${renderMarkets(match)}

        <section class="recommendation">
          <h4>建议</h4>
          <p><strong>最终：</strong>${formatPrediction(match)}</p>
          ${renderStakingPlan(match)}
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

function renderTeamNews(match) {
  if (!match.team_news) return "";
  return `
    <section>
      <h4>伤停与官方阵容</h4>
      <table class="compare-table">
        <thead>
          <tr>
            <th>${match.home_team}</th>
            <th>${match.away_team}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>${formatTeamNewsSide(match.team_news.home)}</td>
            <td>${formatTeamNewsSide(match.team_news.away)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  `;
}

function formatTeamNewsSide(side) {
  if (!side) return "本次查询未取得";
  const absences = side.absences?.length
    ? `确认缺阵：${side.absences.map((item) => `${item.player}（${item.reason}）`).join("、")}`
    : "API 未返回已确认缺阵";
  const lineup = side.lineup
    ? `官方首发：${side.lineup.formation ?? "阵型待定"}；${side.lineup.starting_xi.join("、")}`
    : "本次查询未取得官方首发";
  return `${absences}<br>${lineup}`;
}

function renderMarkets(match) {
  return `
    <section>
      <h4>盘口</h4>
      <div class="market-grid">
        <div><span>欧赔</span><strong>${formatThreeWay(match.european_odds)}</strong></div>
        <div><span>亚盘</span><strong>${formatAsian(match.asian_handicap)}</strong></div>
        <div><span>竞彩</span><strong>${formatLottery(match.chinese_lottery)}</strong></div>
        <div><span>Polymarket</span><strong>${formatPolymarket(match.polymarket)}</strong></div>
      </div>
      <p class="market-read">${match.market_read}</p>
    </section>
  `;
}

function renderStakingPlan(match) {
  const prediction = match.prediction ?? {};
  const keys = prediction.selection_keys ?? [];
  if (prediction.market_type !== "sporttery_handicap" || keys.length !== 2 || new Set(keys).size !== 2) {
    return `<p class="muted">原分析未推荐竞彩让球双选，不另选组合计算配比。</p>`;
  }
  const matchesSelection = (plan) => {
    const selections = Object.keys(plan?.selection_odds ?? {});
    return selections.length === keys.length && keys.every(key => selections.includes(key));
  };
  const primary = prediction.staking_plan ?? match.mismatch?.staking_plan;
  const plan = [primary, ...(match.staking_references ?? [])].find(item => item && matchesSelection(item));
  if (!plan) return `<p class="muted">原推荐双选组合尚缺有效配比数据。</p>`;
  return renderStakingCard(plan);
}

function renderStakingCard(plan) {
  const money = (value) => Number.isFinite(value) ? value.toFixed(2) : "--";
  const feasible = plan.status === "feasible";
  const rows = feasible ? plan.scenarios : plan.equal_stake_scenarios;
  return `<section class="staking-plan">
    <h4>${feasible ? "推荐组合配比" : "原推荐组合暂无可行配比"}</h4>
    <p>${escapeAttribute(plan.note_zh)}</p>
    ${!feasible && rows?.length ? `<p>以下仅演示各买1倍、共4元的结果。</p>` : ""}
    ${rows?.length ? `<div class="table-wrap"><table><thead><tr><th>让球结果</th><th>倍数</th><th>投入</th><th>净收益</th></tr></thead>
    <tbody>${rows.map((row) => {
      const allocation = plan.allocations?.find(item => item.selection === row.selection);
      const units = feasible ? (allocation?.units ?? 0) : (row.covered ? 1 : 0);
      const stake = feasible ? (allocation?.stake ?? 0) : units * 2;
      return `<tr><td>${escapeAttribute(row.label)}${row.covered ? "" : "（未覆盖）"}</td><td>${units}倍</td><td>${money(stake)}元</td><td>${row.net_profit > 0 ? "+" : ""}${money(row.net_profit)}元</td></tr>`;
    }).join("")}</tbody></table></div>` : ""}
  </section>`;
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
            ${renderStakingPlan(match)}
          </article>
        `,
      )
      .join("") || `<p class="empty">当前没有命中错盘规则的比赛。</p>`;
  elements.viewBody.insertAdjacentHTML("beforeend", renderPagination("mismatch", paged));
  elements.viewBody.insertAdjacentHTML("beforeend", renderMismatchParlays(matches));
  const updateParlays = () => {
    const value = Number(document.querySelector("#parlayMultiplier").value);
    const threshold = Number(document.querySelector("#parlayConfidence").value);
    const mixed = document.querySelector("#parlayMode").value === "mixed";
    const checkerIds = new Set(state.checkerHistory.map(match => match.id));
    const candidates = mixed ? state.currentMatches.filter(match => match.mismatch?.matched || checkerIds.has(match.id)) : matches;
    document.querySelector("#parlayResults").innerHTML = Number.isInteger(value) && value >= 1 && value <= 10000
      && Number.isFinite(threshold) && threshold >= 0 && threshold <= 100
      ? renderParlayResults(MismatchParlays.calculate(candidates, { mixed, minConfidence: threshold }), value)
      : "<p>倍数须为 1～10000 的整数，信心门槛须为 0～100。</p>";
  };
  for (const id of ["#parlayMultiplier", "#parlayConfidence", "#parlayMode"]) {
    document.querySelector(id).addEventListener("input", updateParlays);
  }
  updateParlays();
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
      <span>按信心排序选取非错盘推荐与配比可行的错盘推荐</span>
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
      <p><strong>推荐：</strong>${match.prediction?.market ?? "待补"}：${match.prediction?.pick ?? "待补"}（信心 ${match.prediction?.confidence ?? "--"}%）</p>
      ${match.mismatch?.matched ? `<p class="muted">错盘推荐 · ${match.prediction?.staking_plan?.status === "feasible" ? "配比可行" : "历史记录，配比未通过或未计算"}${match.chinese_lottery?.single_handicap === false ? " · 串关参考" : ""}</p>` : ""}
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

function renderFrozenEvaluation() {
  const report = state.learningEvaluation;
  if (!report) return `<p>冻结预测评估尚未开始；历史命中率仅供参考。</p>`;
  const summary = report.overall;
  const value = (number) => Number.isFinite(number) ? number.toFixed(4) : "--";
  const market = summary.market_paired;
  return `<div class="frozen-evaluation">
    <p>全部比赛与自选报告 · 每场首次有效赛前预测 · ${report.selected_fixtures} 场入档，${summary.settled} 场完成对照，${report.pending_results} 场待赛果。</p>
    <div class="learning-grid">
      <article><span>原始评分 Brier</span><strong>${value(summary.base.brier)}</strong><em>${summary.base.n} 场，排除走盘</em></article>
      <article><span>校准评分 Brier</span><strong>${value(summary.calibrated.brier)}</strong><em>差值 ${value(summary.brier_delta)}，负值较好</em></article>
      <article><span>同口径市场 Brier</span><strong>${value(market.market.brier)}</strong><em>${market.market.n} 场；该子集原始 / 校准 ${value(market.base.brier)} / ${value(market.calibrated.brier)}</em></article>
    </div>
    <p>置信度仍是规则评分，以上为概率评分诊断。仅调信心不会改变选边、命中率或收益；旧记录不补算成冻结样本。</p>
  </div>`;
}

function renderLearningSummary(groups) {
  const strategies = Object.values(state.strategyPerformance.strategies ?? {});
  const active = strategies.filter((strategy) => strategy.active);
  const largestSample = Math.max(0, ...strategies.map((strategy) => strategy.sample_size ?? 0));
  const minimumSample = state.strategyPerformance.minimum_sample ?? 20;
  const calibrationStatus = active.length
    ? `已启用 ${active.length} 类策略校准，单场信心最多修正 ±5 个百分点`
    : `策略校准样本积累中：最多 ${largestSample}/${minimumSample}，当前不调权`;

  return `
    <section class="learning-panel">
      <div>
        <span>冻结样本校准</span>
        <strong>${calibrationStatus}</strong>
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
      ${renderFrozenEvaluation()}
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
  const candidates = matches.filter(match => {
    const prediction = match.prediction ?? {};
    if (!(prediction.confidence > 0) || !prediction.market || prediction.market === "无推荐") return false;
    if (!match.mismatch?.matched) return prediction.betting_eligible !== false;
    const plan = prediction.staking_plan;
    const keys = prediction.selection_keys ?? [];
    const allocations = plan?.allocations ?? [];
    return prediction.market_type === "sporttery_handicap" && keys.length === 2 && new Set(keys).size === 2
      && plan?.status === "feasible" && plan.minimum_covered_profit > 0 && allocations.length === 2
      && keys.every(key => allocations.some(row => row.selection === key));
  });
  candidates.sort((a, b) => predictionConfidence(b) - predictionConfidence(a));
  return candidates.slice(0, candidates.length >= 5 ? 8 : 3);
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

function formatPolymarket(market) {
  if (!market) return "无对应市场";
  const probabilities = [market.home, market.draw, market.away];
  const moneyline = probabilities.every((value) => Number.isFinite(value))
    ? `主/平/客 ${probabilities.map(formatProbability).join(" / ")}`
    : "胜平负待补";
  const spread = market.favorite_spread;
  const spreadText = spread && Number.isFinite(spread.probability)
    ? `${spread.team} ${formatLine(spread.line)} ${formatProbability(spread.probability)}${market.spread_signal_eligible ? "" : "（仅展示）"}`
    : "-1.5 暂无";
  const quality = market.signal_eligible ? "有效市场" : "低流动性，仅展示";
  const volume = Number.isFinite(market.volume)
    ? `Vol $${Math.round(market.volume).toLocaleString("en-US")}`
    : "Vol --";
  return `${moneyline}；${spreadText}；${volume} · ${quality}`;
}

function formatProbability(value) {
  return `${Math.round(value * 100)}%`;
}

function formatPrediction(match) {
  if (!match.prediction) return "待补";
  const prefix = match.chinese_lottery?.single_handicap === false
    ? "盘路分析，可作串关选场参考；不支持让球单关，串关收益须按整组另算。"
    : match.prediction.betting_eligible === false ? "仅作方向观察，不建议按单关双选方案购买。" : "";
  return `${prefix}${match.prediction.market}：${match.prediction.pick}（信心 ${match.prediction.confidence}%）`;
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

function renderMismatchParlays(matches) {
  return `<section class="staking-plan" aria-label="错盘双选串关盈亏">
    <h3>预测＋错盘串关盈利组合</h3>
    <p>错盘保留原推荐双选；从当前批次 Checker 选入高信心的竞彩单选预测。假设所选预测全部命中，双选按较低赔率计算。每注 2 元，各注同倍；不采用上方单场配比。</p>
    <p>枚举当前批次任意 2～8 场，以及同组选场的各关数全组合与混合购买（例如全部 2串1＋3串1）。不含单关、自定义删注和各注不同倍数。</p>
    <label>方案 <select id="parlayMode"><option value="mixed">高信心单选＋错盘双选</option><option value="double">仅错盘双选</option></select></label>
    <label>单选信心门槛 <input id="parlayConfidence" type="number" min="0" max="100" value="65"> / 100</label>
    <p class="muted">默认门槛 65 是筛选设置，不是经验证的命中率。错盘双选不会自动压成单选；亚盘仅在获胜条件完全等价时转换为竞彩选项。</p>
    <label>统一倍数 <input id="parlayMultiplier" type="number" min="1" max="10000" step="1" value="1"></label>
    <p class="muted">加倍只放大盈亏。理论奖金以出票赔率、取整及奖金限额为准；全中假设不代表收益保证。</p>
    <div id="parlayResults">${renderParlayResults(MismatchParlays.calculate(matches), 1)}</div>
  </section>`;
}

function renderParlayResults(result, multiplier) {
  const money = value => (value * multiplier).toFixed(2);
  const labels = { home: "让胜", draw: "让平", away: "让负" };
  const source = result.eligible.map(({ match, minimumOdds, count, keys, marketType, reason }, i) =>
    `<li>${i + 1}. ${escapeAttribute(match.home_team)} vs ${escapeAttribute(match.away_team)}：${keys.map(key => marketType === "sporttery_standard" ? ({home:"主胜",draw:"平",away:"客胜"})[key] : labels[key]).join("＋")}，${count === 1 ? "预测单选 · 信心 " + match.prediction.confidence : "错盘双选"}，最低赔率 ${minimumOdds.toFixed(2)}${reason ? "（" + reason + "）" : ""}</li>`).join("");
  const excluded = result.excluded.length ? `<p>以下 ${result.excluded.length} 场未计算：${result.excluded.map(match => escapeAttribute(match.home_team + " vs " + match.away_team + "：" + match.exclusion)).join("；")}。结果仅覆盖有效场次。</p>` : "";
  const prefix = `<ul>${source}</ul>${excluded}`;
  if (result.status === "too_many") return `${prefix}<p>有效错盘超过 8 场，暂不执行全量枚举；未生成盈利结论。</p>`;
  if (result.status === "insufficient") return `${prefix}<p>当前可用 ${result.eligible.length} 场。仅双选模式至少需要两场；混合模式至少需要一场高信心竞彩单选和一场错盘双选。暂不能生成组合。</p>`;
  const summary = `<p>已检查 ${result.checked} 种方案，${result.plans.length} 种在全中最低赔率情景下盈利。</p>`;
  if (!result.plans.length) return `${prefix}${summary}<strong>无盈利组合：即使全部命中，最低奖金也不能超过投入；增加倍数无法改变结果。</strong>
    <div class="table-wrap"><table><thead><tr><th>关数</th><th>选场组合数</th><th>最佳净利润</th></tr></thead><tbody>${result.bySize.map(row => `<tr><td>${row.k}串1</td><td>${row.count}</td><td>${money(row.bestProfit)} 元</td></tr>`).join("")}</tbody></table></div>`;
  const names = new Map(result.eligible.map((item, i) => [item.match.id, i + 1]));
  return `${prefix}${summary}<p>按收益率排序；编号对应上方比赛。每行是独立方案，混合关数包含该组选场下每个关数的全部组合。</p>
    <div class="table-wrap parlay-table"><table><thead><tr><th>场次</th><th>串关</th><th>倍数</th><th>总注数</th><th>投入</th><th>最低奖金</th><th>净利润</th><th>收益率</th></tr></thead><tbody>${result.plans.map(plan => `<tr><td>${plan.ids.map(id => names.get(id)).join("、")}</td><td>${plan.sizes.map(k => k + "串1").join("＋")}</td><td>${multiplier}</td><td>${plan.cost / 2 * multiplier}</td><td>${money(plan.cost)}</td><td>${money(plan.payout)}</td><td>+${money(plan.profit)}</td><td>${(plan.roi * 100).toFixed(2)}%</td></tr>`).join("")}</tbody></table></div>`;
}
