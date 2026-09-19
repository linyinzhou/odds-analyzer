/* Equal-unit, fixed-double Sporttery free-pass scenarios. No outcome prediction. */
(function (root) {
  function combinations(items, size) {
    const result = [];
    function visit(start, picked) {
      if (picked.length === size) { result.push(picked); return; }
      for (let i = start; i <= items.length - size + picked.length; i++) {
        visit(i + 1, [...picked, items[i]]);
      }
    }
    visit(0, []);
    return result;
  }

  // An independent, conservative direction check. It never reads Sporttery prices,
  // profit, saved results or the original pair's confidence to select a side.
  function narrowMismatch(match) {
    const keep = reason => ({ narrowed: false, reason });
    const keys = match.prediction?.selection_keys;
    if (!match.mismatch?.matched || match.prediction?.market_type !== "sporttery_handicap"
        || !Array.isArray(keys) || keys.length !== 2 || new Set(keys).size !== 2
        || keys.some(key => !["home", "draw", "away"].includes(key))) return keep("原推荐不是有效错盘双选");
    const asian = match.asian_handicap;
    const euro = match.european_odds;
    const line = match.chinese_lottery?.handicap;
    const valid = value => typeof value === "number" && Number.isFinite(value);
    if (!asian || !euro || !Number.isInteger(line)
        || !valid(asian.handicap)
        || [asian.home_odds, asian.away_odds, euro.home, euro.draw, euro.away].some(x => !valid(x) || x <= 1)) {
      return keep("欧赔或亚盘数据不足，保留双选");
    }
    if (asian.home_odds === asian.away_odds) return keep("亚盘两侧价格相同，独立方向不明确");
    const side = asian.home_odds < asian.away_odds ? "home" : "away";
    // Integer/quarter lines include pushes or partial settlements; no forced conversion.
    if (Math.abs(asian.handicap % 1) !== 0.5) return keep("亚盘含走盘或半输赢，不能直接收窄为同一竞彩结果");
    const boundary = side === "home" ? Math.floor(-asian.handicap) + 1 : Math.ceil(-asian.handicap) - 1;
    if (boundary !== (side === "home" ? 1 - line : -line - 1) || !keys.includes(side)) {
      return keep("独立亚盘方向不能等价对应原双选中的一个结果");
    }
    const raw = {home: 1 / euro.home, draw: 1 / euro.draw, away: 1 / euro.away};
    const total = raw.home + raw.draw + raw.away;
    let eventProbability;
    if (side === "home" && boundary === 0) eventProbability = (raw.home + raw.draw) / total;
    else if (side === "home" && boundary === 1) eventProbability = raw.home / total;
    else if (side === "away" && boundary === 0) eventProbability = (raw.away + raw.draw) / total;
    else if (side === "away" && boundary === -1) eventProbability = raw.away / total;
    else return keep("缺少独立净胜球分布，不能判断该单选结果");
    if (eventProbability <= 0.5) return keep("欧赔没有支持该单选方向，保留双选");
    const context = match.fundamental_context ?? {};
    const home = context.home ?? {}, away = context.away ?? {};
    if ([home, away].some(team => !Number.isInteger(team.played_games) || team.played_games < 3
        || !valid(team.points) || !valid(team.goal_difference))) {
      return keep("缺少双方至少 3 场的积分和净胜球数据，保留双选");
    }
    const ppg = home.points / home.played_games - away.points / away.played_games;
    const gd = home.goal_difference / home.played_games - away.goal_difference / away.played_games;
    const sign = side === "home" ? 1 : -1;
    if (sign * ppg <= 0 || sign * gd <= 0) return keep("积分与净胜球未同时支持独立方向，保留双选");
    const condition = side === "home" ? (boundary === 0 ? "主队不败" : "主队获胜")
      : (boundary === 0 ? "客队不败" : "客队获胜");
    const selectedPrice = side === "home" ? asian.home_odds : asian.away_odds;
    const cover = (1 / selectedPrice) / (1 / asian.home_odds + 1 / asian.away_odds);
    return { narrowed: true, selection: side, condition,
      reason: `独立判断：${condition}。亚盘去水方向约 ${(cover * 100).toFixed(1)}%，欧赔对应事件约 ${(eventProbability * 100).toFixed(1)}%；场均积分和净胜球同向。赛季样本 ${home.played_games}/${away.played_games} 场；未综合完整伤停与近期逐场表现，属于规则推断，不是校准命中率。`,
      dropped: keys.filter(key => key !== side),
    };
  }

  function calculate(matches, { mixed = false, narrow = false } = {}) {
    const eligible = [], excluded = [], seen = new Set();
    for (const match of matches) {
      if ((!mixed && !match.mismatch?.matched) || seen.has(match.id)) continue;
      seen.add(match.id);
      const prediction = match.prediction ?? {};
      const isDouble = match.mismatch?.matched === true;
      let keys = prediction.selection_keys;
      let marketType = prediction.market_type;
      let reason = "";
      if (!isDouble && prediction.betting_eligible === false) {
        excluded.push({ ...match, exclusion: "原预测不适合投注" }); continue;
      }
      // Only exact full-win equivalents; never translate an underdog cover into an outright win.
      if (!isDouble && marketType === "asian_handicap" && keys?.length === 1) {
        const side = keys[0];
        const line = prediction.home_handicap;
        const selectedLine = side === "home" ? line : -line;
        if (typeof line === "number" && Number.isFinite(line) && ["home", "away"].includes(side)) {
          if (selectedLine === -0.5) {
            marketType = "sporttery_standard";
            reason = "亚盘让半球取胜与竞彩胜平负该方胜等价";
          } else if (selectedLine < -0.5 && selectedLine % 1 === -0.5
              && match.chinese_lottery?.handicap === line + (side === "home" ? 0.5 : -0.5)) {
            marketType = "sporttery_handicap";
            reason = "亚盘获胜条件与此竞彩让球单选等价";
          }
        }
      }
      const odds = marketType === "sporttery_handicap" ? match.chinese_lottery?.handicap_odds
        : marketType === "sporttery_standard" ? match.chinese_lottery?.standard : null;
      let count = isDouble ? 2 : 1;
      if ((isDouble && marketType !== "sporttery_handicap") || !Array.isArray(keys)
          || keys.length !== count || new Set(keys).size !== count
          || keys.some(key => !["home", "draw", "away"].includes(key)
            || typeof odds?.[key] !== "number" || !Number.isFinite(odds[key]) || odds[key] <= 1)) {
        excluded.push({ ...match, exclusion: isDouble ? "缺少有效原推荐双选或赔率" : "没有可用的竞彩单选及赔率；不强行改写预测" });
        continue;
      }
      const originalKeys = [...keys];
      const narrowing = narrow && isDouble ? narrowMismatch(match) : null;
      if (narrowing) {
        reason = narrowing.reason;
        if (narrowing.narrowed) { keys = [narrowing.selection]; count = 1; }
      }
      eligible.push({ match, keys, originalKeys, narrowing, marketType, reason, count,
        minimumOdds: Math.min(...keys.map(key => odds[key])) });
    }
    // Exhaustive free-pass enumeration is exponential. Never silently truncate a slate.
    if (eligible.length > 8) return { eligible, excluded, status: "too_many", plans: [], checked: 0 };
    const plans = [];
    const bySize = [];
    let checked = 0;
    for (let size = 2; size <= eligible.length; size++) {
      for (const group of combinations(eligible, size)) {
        if (mixed && !(group.some(item => item.count === 1) && group.some(item => item.count === 2))) continue;
        const legs = [];
        for (let k = 2; k <= size; k++) {
          const tickets = combinations(group, k);
          const cost = tickets.reduce((sum, ticket) => sum + 2 * ticket.reduce((n, item) => n * item.count, 1), 0);
          const payout = tickets.reduce((sum, ticket) => sum
            + 2 * ticket.reduce((product, item) => product * item.minimumOdds, 1), 0);
          legs.push({ k, cost, payout });
          const summary = bySize[k] ??= { k, count: 0, profitable: 0, bestProfit: -Infinity };
          if (k === size) {
            summary.count++;
            summary.profitable += payout - cost > 1e-8 ? 1 : 0;
            summary.bestProfit = Math.max(summary.bestProfit, payout - cost);
          }
        }
        // One row per selected group and nonempty set of pass sizes (e.g. 2+3).
        for (let mask = 1; mask < 2 ** legs.length; mask++) {
          const selected = legs.filter((_, i) => mask & (1 << i));
          const cost = selected.reduce((sum, leg) => sum + leg.cost, 0);
          const payout = selected.reduce((sum, leg) => sum + leg.payout, 0);
          checked++;
          if (payout - cost > 1e-8) plans.push({
            ids: group.map(item => item.match.id), sizes: selected.map(leg => leg.k),
            cost, payout, profit: payout - cost, roi: (payout - cost) / cost,
          });
        }
      }
    }
    plans.sort((a, b) => b.roi - a.roi || a.cost - b.cost);
    return { eligible, excluded, plans, checked, bySize: bySize.filter(Boolean),
      status: eligible.length < 2 || (mixed && !(eligible.some(item => item.count === 1) && eligible.some(item => item.count === 2))) ? "insufficient" : "complete" };
  }
  const api = { calculate, narrowMismatch };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MismatchParlays = api;
})(globalThis);
