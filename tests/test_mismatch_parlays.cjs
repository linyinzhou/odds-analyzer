const assert = require('node:assert/strict');
const { calculate } = require('../dashboard/mismatch-parlays.js');
function match(id, low, high = 3.85) {
  return { id, kickoff_time: '09-13 20:00', home_team: id, away_team: 'Away', mismatch: { matched: true },
    prediction: { market_type: 'sporttery_handicap', selection_keys: ['draw', 'away'] },
    chinese_lottery: { handicap_odds: { home: 1.01, draw: high, away: low } } };
}
const example = [1.73, 1.43, 1.57, 1.59].map((x, i) => match(String(i), x));
const before = JSON.stringify(example);
const losing = calculate(example);
assert.equal(losing.status, 'complete');
assert.equal(losing.plans.length, 0);
assert.equal(losing.checked, 25);
assert.equal(losing.bySize[0].count, 6);
assert.ok(Math.abs(losing.bySize[2].bestProfit - (12.35119314 - 32)) < 1e-8);
assert.equal(JSON.stringify(example), before);
assert.equal(calculate([match('a', 2), match('b', 2)]).plans.length, 0);
const winning = calculate([match('a', 2.5), match('b', 2.5), match('c', 2.5)]);
assert.equal(winning.plans.length, 6);
const mixed = winning.plans.find(p => p.sizes.length === 2);
assert.equal(mixed.cost, 40);
assert.equal(mixed.payout, 68.75);
assert.equal(mixed.profit, 28.75);
const offset = calculate([match('a', 3), match('b', 3), match('c', 1.01)]);
assert.ok(offset.plans.some(p => p.sizes.length === 2));
const bad = match('bad', null);
assert.equal(calculate([bad, example[0]]).status, 'insufficient');
assert.equal(calculate([bad, ...example]).excluded.length, 1);
assert.equal(calculate([example[0], example[0]]).eligible.length, 1);
for (const value of [NaN, Infinity, true, '1.7', 0, 1]) {
  assert.equal(calculate([match('bad', value)]).excluded.length, 1);
}
const single = match('single', 2.5);
single.prediction.selection_keys = ['away'];
assert.equal(calculate([single]).excluded.length, 1);
assert.equal(calculate(Array.from({length: 9}, (_, i) => match(String(i), 2.5))).status, 'too_many');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const node = key => {
  if (!nodes.has(key)) nodes.set(key, { innerHTML: '', value: '1',
    insertAdjacentHTML(_, html) { this.innerHTML += html; },
    addEventListener(event, fn) { this[event] = fn; } });
  return nodes.get(key);
};
const context = vm.createContext({ MismatchParlays: { calculate },
  document: { querySelector: node, querySelectorAll: () => [] } });
let app = fs.readFileSync('dashboard/app.js', 'utf8');
app = app.replace(/\nelements\.viewButtons\.forEach\([\s\S]*?function renderMismatchParlays/, 'function renderMismatchParlays');
vm.runInContext(app, context);
node('#parlayMode').value = 'double';
context.matches = example;
vm.runInContext('state.mismatchHistory = matches; renderMismatchView()', context);
assert.match(node('#viewBody').innerHTML, /没有盈利组合/);
node('#parlayMultiplier').value = '2';
node('#parlayMultiplier').input();
assert.match(node('#parlayResults').innerHTML, /没有盈利组合/);
context.matches = [match('a', 2.5), match('b', 2.5)];
vm.runInContext('state.mismatchHistory = matches; renderMismatchView()', context);
node('#parlayMultiplier').value = '2';
node('#parlayMultiplier').input();
assert.match(node('#parlayResults').innerHTML, /25.00/);
assert.match(node('#parlayResults').innerHTML, /\+9.00/);
node('#parlayMultiplier').value = '1.5';
node('#parlayMultiplier').input();
assert.match(node('#parlayResults').innerHTML, /倍数须为/);
console.log('Mismatch parlay calculation and dashboard integration checks passed.');


const confident = match('single-high', 2.5);
confident.mismatch.matched = false;
confident.prediction.selection_keys = ['away'];
confident.prediction.confidence = 70;
let combined = calculate([confident, match('double', 1.73)], { mixed: true });
assert.equal(combined.plans[0].cost, 4);
assert.equal(combined.plans[0].payout, 8.65);
assert.equal(combined.plans[0].profit, 4.65);
confident.prediction.confidence = 54;
assert.equal(calculate([confident, match('double', 1.73)], {mixed:true}).plans.length, 1);
delete confident.prediction.confidence;
assert.equal(calculate([confident, match('double', 1.73)], {mixed:true}).plans.length, 1);
confident.prediction.confidence = 54;
assert.equal(calculate([confident], {mixed:true}).status, 'insufficient');
const asian = structuredClone(confident);
asian.prediction.market_type = 'asian_handicap';
asian.prediction.home_handicap = 0.5;
asian.chinese_lottery.standard = {home: 2, draw: 3, away: 2.1};
assert.equal(calculate([asian], {mixed:true}).eligible[0].marketType, 'sporttery_standard');
asian.prediction.home_handicap = -0.5;
assert.equal(calculate([asian], {mixed:true}).eligible.length, 0);
context.matches = [confident, match('double', 1.73)];
node('#parlayMultiplier').value = '1';
node('#parlayMode').value = 'mixed';
vm.runInContext('state.currentMatches = matches; state.checkerHistory = [matches[0]]; state.mismatchHistory = [matches[1]]; renderMismatchView()', context);
assert.match(node('#parlayResults').innerHTML, /预测单选/);
assert.match(node('#parlayResults').innerHTML, /4.65/);
vm.runInContext('state.checkerHistory = []; renderMismatchView()', context);
assert.match(node('#parlayResults').innerHTML, /4.65/);
assert.doesNotMatch(node('#viewBody').innerHTML, /parlayConfidence/);
vm.runInContext('state.currentMatches = [matches[1]]; renderMismatchView()', context);
assert.match(node('#parlayResults').innerHTML, /可用预测不足/);
console.log('Mixed prediction and mismatch checks passed.');

const { narrowMismatch } = require('../dashboard/mismatch-parlays.js');
const narrowable = match('narrow-away', 1.73);
narrowable.chinese_lottery.handicap = -1;
narrowable.asian_handicap = {handicap: -0.5, home_odds: 2.02, away_odds: 1.91};
narrowable.european_odds = {home: 2.01, draw: 3.79, away: 3.73};
narrowable.fundamental_context = {
  home: {played_games: 3, points: 1, goal_difference: -5},
  away: {played_games: 3, points: 5, goal_difference: 2}
};
const frozen = JSON.stringify(narrowable);
assert.equal(narrowMismatch(narrowable).selection, 'away');
const narrowed = calculate([narrowable, match('double', 1.59)], {narrow:true});
assert.equal(narrowed.plans[0].cost, 4);
assert.ok(Math.abs(narrowed.plans[0].profit - 1.5014) < 1e-8);
assert.equal(JSON.stringify(narrowable), frozen);
const repriced = structuredClone(narrowable);
repriced.chinese_lottery.handicap_odds = {home: 9, draw: 1.1, away: 20};
repriced.review = {hit:false, final_score:'5-0'};
repriced.prediction.confidence = 1;
assert.deepEqual(narrowMismatch(repriced), narrowMismatch(narrowable));
for (const change of [
  m => { m.asian_handicap.handicap = -0.25; },
  m => { m.asian_handicap.home_odds = m.asian_handicap.away_odds; },
  m => { m.fundamental_context.home.points = 9; },
  m => { m.fundamental_context.away.played_games = 2; },
  m => { m.european_odds.home = 1.1; },
  m => { m.chinese_lottery.handicap = 0; },
  m => { m.prediction.selection_keys = ['home','draw']; },
  m => { delete m.fundamental_context; },
]) {
  const value = structuredClone(narrowable); change(value);
  assert.equal(narrowMismatch(value).narrowed, false);
}
const homeNarrow = structuredClone(narrowable);
homeNarrow.id = 'home-narrow';
homeNarrow.prediction.selection_keys = ['home','draw'];
homeNarrow.chinese_lottery.handicap = 1;
homeNarrow.asian_handicap = {handicap:0.5, home_odds:1.91, away_odds:2.02};
homeNarrow.european_odds = {home:3.73, draw:3.79, away:2.01};
[homeNarrow.fundamental_context.home, homeNarrow.fundamental_context.away] =
  [homeNarrow.fundamental_context.away, homeNarrow.fundamental_context.home];
assert.equal(narrowMismatch(homeNarrow).selection, 'home');
assert.ok(calculate([narrowable,homeNarrow],{narrow:true}).eligible.every(x=>x.count===1));
node('#parlayMode').value = 'narrow';
context.matches = [narrowable, match('double',1.59)];
vm.runInContext('state.currentMatches = matches; state.mismatchHistory = matches; renderMismatchView()', context);
assert.match(node('#parlayResults').innerHTML, /错盘收窄单选/);
assert.match(node('#parlayResults').innerHTML, /原双选信心不沿用/);
assert.match(node('#parlayResults').innerHTML, /1.50/);
console.log('Independent mismatch narrowing checks passed.');

