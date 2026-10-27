const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const elements = new Map();
const document = {querySelector: s => { if (!elements.has(s)) elements.set(s, {textContent:'',innerHTML:'',classList:{toggle(){}}});return elements.get(s);},querySelectorAll:()=>[]};
const context = vm.createContext({document, console, localStorage:{getItem(){return null}}, MismatchParlays:{calculate(matches, options){assert.equal(options, undefined);return {plans:[]};}}});
let source=fs.readFileSync('dashboard/app.js','utf8');
source=source.replace(/loadDashboard\(\)\.catch\(\(error\) => \{[\s\S]*?\n\}\);/,'');
vm.runInContext(source,context);
vm.runInContext(`
state.checkerHistory = [
{id:'yes',kickoff_time:'2026-10-27 20:00',prediction:{confidence:60},mismatch:{matched:true},review:{reviewed:true,hit:true}},
{id:'no',kickoff_time:'2026-10-27 20:00',prediction:{confidence:60},mismatch:{matched:false},review:{reviewed:true,hit:false}},
{id:'void',kickoff_time:'2026-10-27 20:00',prediction:{confidence:60},mismatch:{matched:true},review:{reviewed:true,hit:null,void:true}}
];
renderSummary();
if (getCheckerMatches().length !== 2) throw Error('non-mismatch leaked');
if (elements.checkerCount.textContent !== '1/1') throw Error('wrong denominator');
if (renderMismatchParlays([]) !== '') throw Error('empty combination shown');
`,context);
console.log('Mismatch-only UI checks passed');

