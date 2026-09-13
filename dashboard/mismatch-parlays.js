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

  function calculate(matches, { mixed = false, minConfidence = 65 } = {}) {
    const eligible = [], excluded = [], seen = new Set();
    for (const match of matches) {
      if ((!mixed && !match.mismatch?.matched) || seen.has(match.id)) continue;
      seen.add(match.id);
      const prediction = match.prediction ?? {};
      const isDouble = match.mismatch?.matched === true;
      let keys = prediction.selection_keys;
      let marketType = prediction.market_type;
      let reason = "";
      if (!isDouble && (!Number.isFinite(prediction.confidence) || prediction.confidence < minConfidence)) {
        excluded.push({ ...match, exclusion: "预测信心低于门槛或缺失" }); continue;
      }
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
      const count = isDouble ? 2 : 1;
      if ((isDouble && marketType !== "sporttery_handicap") || !Array.isArray(keys)
          || keys.length !== count || new Set(keys).size !== count
          || keys.some(key => !["home", "draw", "away"].includes(key)
            || typeof odds?.[key] !== "number" || !Number.isFinite(odds[key]) || odds[key] <= 1)) {
        excluded.push({ ...match, exclusion: isDouble ? "缺少有效原推荐双选或赔率" : "没有可用的竞彩单选及赔率；不强行改写预测" });
        continue;
      }
      eligible.push({ match, keys, marketType, reason, count,
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
  const api = { calculate };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MismatchParlays = api;
})(globalThis);
