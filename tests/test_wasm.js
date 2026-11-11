// The WebAssembly build (gui/wasm, from gui/build_wasm.py) against the native C++ solver (build/emtsim):
// every circuits/*.net, the node voltages and branch currents on the same time points.
//   node tests/test_wasm.js [netlist.net ...] [--chatter=<method>]
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const exe = ['build/emtsim.exe', 'build/Release/emtsim.exe', 'build/emtsim'].map((p) => path.join(ROOT, p)).find(fs.existsSync);
const CHATTER = { off: 0, cda: 1, detect: 2, rootmatch: 3, pscad: 4 };

function readCsv(file) {
  const rows = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/).map((l) => l.split(','));
  const names = rows[0].slice(1);
  return { names, t: rows.slice(1).map((r) => +r[0]), cols: names.map((_, k) => rows.slice(1).map((r) => +r[k + 1])) };
}

function maxDiff(a, b) {
  let d = 0, peak = 0;
  for (let k = 0; k < a.length; k++)
    for (let s = 0; s < a[k].length; s++) { d = Math.max(d, Math.abs(a[k][s] - b[k][s])); peak = Math.max(peak, Math.abs(b[k][s])); }
  return { d, peak };
}

(async () => {
  if (!exe) { console.error('Build the native solver first (build.bat).'); process.exit(2); }
  const createEmtsim = require(path.join(ROOT, 'gui/wasm/emtsim.js'));
  const M = await createEmtsim({ print: () => {}, printErr: () => {} });
  const args = process.argv.slice(2);
  const method = (args.find((a) => a.startsWith('--chatter=')) || '').split('=')[1];
  let files = args.filter((a) => !a.startsWith('--'));
  if (!files.length) files = fs.readdirSync(path.join(ROOT, 'circuits')).filter((f) => f.endsWith('.net')).map((f) => path.join(ROOT, 'circuits', f));
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'emtsim_wasm_'));
  let fails = 0;
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8');
    execFileSync(exe, [path.resolve(f)].concat(method ? ['--chatter=' + method] : []), { cwd: work, stdio: 'ignore' });
    const nv = readCsv(path.join(work, 'results.csv')), ni = readCsv(path.join(work, 'currents.csv'));
    const t0 = Date.now();
    const r = JSON.parse(M.ccall('emtsim_run', 'string', ['string', 'number', 'number'], [text, method ? CHATTER[method] : -1, -1]));
    const ms = Date.now() - t0;
    let ok = !r.error && r.t.length === nv.t.length && r.V.length === nv.cols.length && r.I.length === ni.cols.length;
    let msg = r.error || '';
    if (ok) {
      // the browser result is rounded to 7 significant digits for size; valve switching instants
      // are the ratio of two small numbers, so compilers may differ there by more than round-off
      const v = maxDiff(r.V, nv.cols), i = maxDiff(r.I, ni.cols);
      const valves = /^\s*(D|THY)\s/m.test(text);
      const tol = valves ? 1e-3 : 1e-6;
      ok = v.d <= tol * v.peak + 1e-9 && i.d <= tol * i.peak + 1e-9;
      msg = `V diff ${v.d.toExponential(1)} of ${v.peak.toPrecision(3)}, I diff ${i.d.toExponential(1)} of ${i.peak.toPrecision(3)}, ${ms} ms`;
    }
    console.log((ok ? 'PASS  ' : 'FAIL  ') + path.basename(f) + '  ' + msg);
    if (!ok) fails++;
  }
  // a second run in the same module gives the same answer (no state left over between runs)
  const t = fs.readFileSync(path.join(ROOT, 'circuits/demo_chatter.net'), 'utf8');
  const a = M.ccall('emtsim_run', 'string', ['string', 'number', 'number'], [t, -1, -1]);
  const b = M.ccall('emtsim_run', 'string', ['string', 'number', 'number'], [t, -1, -1]);
  const same = JSON.stringify(JSON.parse(a).V) === JSON.stringify(JSON.parse(b).V);
  console.log((same ? 'PASS  ' : 'FAIL  ') + 'repeated runs in one module agree');
  if (!same) fails++;
  const bad = JSON.parse(M.ccall('emtsim_run', 'string', ['string', 'number', 'number'], ['R 1 0 x\n', -1, -1]));
  const errOk = typeof bad.error === 'string' && bad.error.length > 0;
  console.log((errOk ? 'PASS  ' : 'FAIL  ') + 'a netlist error comes back as {error}: ' + bad.error);
  if (!errOk) fails++;
  fs.rmSync(work, { recursive: true, force: true });
  console.log(fails ? fails + ' FAILED' : 'all passed');
  process.exit(fails ? 1 : 0);
})();
