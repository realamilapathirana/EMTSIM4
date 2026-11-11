// The editor in a real browser (headless Edge or Chrome, through the DevTools protocol), in its
// three ways of working: the static site (WebAssembly solver), the local server, a group server.
//   python gui/build_wasm.py && node tests/test_web.js      (rebuilds site/ itself)
// Set BROWSER to the browser's executable if it is not found.
'use strict';
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const PY = fs.existsSync(path.join(ROOT, '.venv/Scripts/python.exe')) ? path.join(ROOT, '.venv/Scripts/python.exe') : 'python';
const BROWSER = process.env.BROWSER || [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(fs.existsSync);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (ok, what, detail) => { console.log((ok ? 'PASS  ' : 'FAIL  ') + what + (ok || detail === undefined ? '' : '\n      ' + detail)); if (!ok) fails++; };

const freePort = () => new Promise((r) => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
async function waitPort(port) {
  for (let i = 0; i < 100; i++) {
    const ok = await new Promise((r) => { const c = net.connect(port, '127.0.0.1', () => { c.end(); r(true); }); c.on('error', () => r(false)); });
    if (ok) return; await sleep(100);
  }
  throw new Error('port ' + port + ' did not open');
}

async function browser() {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'emtsim_web_'));
  const port = await freePort();
  const proc = spawn(BROWSER, ['--headless=new', '--disable-gpu', '--remote-debugging-port=' + port, '--user-data-dir=' + prof,
    '--window-size=1500,1000', 'about:blank'], { stdio: 'ignore' });
  let targets;
  for (let i = 0; i < 60 && !targets; i++) { try { targets = await (await fetch('http://127.0.0.1:' + port + '/json')).json(); } catch { await sleep(250); } }
  const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception ? d.params.exceptionDetails.exception.description : d.params.exceptionDetails.text);
    if (d.method === 'Log.entryAdded' && d.params.entry.level === 'error' && !/favicon/.test(d.params.entry.url || '')) errors.push(d.params.entry.text + ' ' + (d.params.entry.url || ''));
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception ? r.result.exceptionDetails.exception.description : r.result.exceptionDetails.text);
    return r.result.result.value;
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
  const open = async (url) => {
    await send('Page.navigate', { url });
    for (let i = 0; i < 80 && !(await ev('typeof info !== "undefined" && document.readyState === "complete"').catch(() => false)); i++) await sleep(100);
    await sleep(400);
    await ev('window.confirm = () => true');
  };
  const runAndWait = async () => {
    await ev('run()');
    return ev('({ status: document.getElementById("status").innerText, n: results && results.cpp && results.cpp.t ? results.cpp.t.length : 0, err: results && results.cpp && results.cpp.error })');
  };
  const close = () => {   // the browser may hold its profile for a moment after it is killed
    proc.kill();
    setTimeout(() => { try { fs.rmSync(prof, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }); } catch (e) { /* left in temp */ } }, 500);
  };
  return { ev, open, runAndWait, errors, close };
}

function serve(args, env) {
  const p = spawn(PY, args, { cwd: ROOT, stdio: 'ignore', env: Object.assign({}, process.env, env || {}) });
  return p;
}

(async () => {
  if (!BROWSER) { console.error('No Edge or Chrome found: set BROWSER'); process.exit(2); }
  if (!fs.existsSync(path.join(ROOT, 'gui/wasm/emtsim.wasm'))) { console.error('Build the WebAssembly solver first: python gui/build_wasm.py'); process.exit(2); }
  const procs = [];
  try {
    // ---------------------------------------------------------------- static site
    let port = await freePort();
    procs.push(serve(['gui/make_site.py', '--serve', String(port)]));
    await waitPort(port);
    let b = await browser();
    await b.open('http://127.0.0.1:' + port + '/');
    check(await b.ev('info.mode') === 'static', 'static site: no server found, solver in the browser');
    const shown = await b.ev('[...document.getElementById("engine").options].filter(o => !o.hidden).map(o => o.value).join(",")');
    check(shown === 'wasm', 'static site: only the browser engine is offered', shown);
    let opened = false;
    for (let i = 0; i < 50 && !opened; i++) { opened = await b.ev('model.components.length > 0'); if (!opened) await sleep(100); }
    check(opened, 'static site: the first example opens');
    const listed = await b.ev('listCircuits().then(f => f.map(x => x.name))');
    check(listed.includes('demo_chatter.net') && listed.length === 14, 'static site: Open lists the 14 examples', listed.join(' '));
    await b.ev('readCircuit("demo_chatter.net").then(r => loadText(r.name, r.text))');
    let r = await b.runAndWait();
    check(r.n === 50 && !r.err && /finished/.test(r.status), 'static site: demo_chatter runs in the browser (50 points)', JSON.stringify(r));
    const v = await b.ev('Math.max(...results.cpp.V[2].map(Math.abs))');
    check(Math.abs(v - 187) < 1, 'static site: the chattering voltage is there (' + v.toFixed(1) + ' V)');
    await b.ev('save()');
    const lib = await b.ev('listCircuits().then(f => f.filter(x => x.mine).map(x => x.name).join(","))');
    check(lib === 'demo_chatter.net', 'static site: Save keeps the circuit in this browser', lib);
    await b.ev('readCircuit("grid1000.net").then(r => loadText(r.name, r.text))');
    await b.ev('run(); new Promise(r => setTimeout(r, 200))');
    const stopping = await b.ev('document.getElementById("btnRun").textContent');
    await b.ev('run()');      // the button is Stop while a browser run is going
    let st = '';
    for (let i = 0; i < 30 && !/stopped/.test(st); i++) { await sleep(100); st = await b.ev('document.getElementById("status").innerText'); }
    check(/■ Stop/.test(stopping) && /stopped/.test(st), 'static site: a long run can be stopped', stopping + ' / ' + st);
    r = await (async () => { await b.ev('readCircuit("demo_breaker.net").then(r => loadText(r.name, r.text))'); return b.runAndWait(); })();
    check(r.n > 0 && !r.err, 'static site: runs again after a stop', JSON.stringify(r));
    check(b.errors.length === 0, 'static site: no page errors', b.errors.join('\n'));
    b.close();

    // ---------------------------------------------------------------- local server (with its security headers)
    port = await freePort();
    procs.push(serve(['gui/server.py', '--no-browser', '--port', String(port)]));
    await waitPort(port);
    b = await browser();
    await b.open('http://127.0.0.1:' + port + '/');
    const eng = await b.ev('info.engines.join(",")');
    check(/cpp/.test(eng) && /wasm/.test(eng), 'local server: C++ on the server and in the browser', eng);
    await b.ev('readCircuit("rectifier.net").then(r => loadText(r.name, r.text))');
    await b.ev('document.getElementById("engine").value = "cpp"');
    await b.runAndWait();
    const server = await b.ev('results.cpp.V');
    await b.ev('document.getElementById("engine").value = "wasm"');
    r = await b.runAndWait();
    const inBrowser = await b.ev('results.cpp.V');
    let d = 0, peak = 0;
    server.forEach((col, k) => col.forEach((x, s) => { d = Math.max(d, Math.abs(x - inBrowser[k][s])); peak = Math.max(peak, Math.abs(x)); }));
    check(!r.err && d <= 1e-3 * peak, 'local server: rectifier, browser and server C++ agree (' + d.toExponential(1) + ' V of ' + peak.toFixed(0) + ' V)');
    check(b.errors.length === 0, 'local server: no page errors (WebAssembly allowed by the CSP)', b.errors.join('\n'));
    b.close();

    // ---------------------------------------------------------------- group server
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'emtsim_group_'));
    const users = path.join(tmp, 'users.json');
    execFileSync(PY, ['gui/server.py', '--users', users, '--add-user', 'alice'], { cwd: ROOT, env: Object.assign({}, process.env, { EMTSIM_PASSWORD: 'correct horse' }) });
    port = await freePort();
    procs.push(serve(['gui/server.py', '--no-browser', '--port', String(port), '--users', users, '--data', path.join(tmp, 'data')]));
    await waitPort(port);
    b = await browser();
    await b.open('http://127.0.0.1:' + port + '/');
    check(await b.ev('!document.getElementById("loginDialog").classList.contains("hidden")'), 'group server: the sign-in dialog opens');
    await b.ev('document.getElementById("loginUser").value = "alice"; document.getElementById("loginPass").value = "wrong"; document.getElementById("loginForm").requestSubmit(); new Promise(r => setTimeout(r, 1500))');
    const msg = await b.ev('document.getElementById("loginMsg").innerText');
    check(/Wrong user name or password/.test(msg), 'group server: a wrong password is refused', msg);
    await b.ev('document.getElementById("loginPass").value = "correct horse"; document.getElementById("loginForm").requestSubmit()');
    await sleep(1500);
    for (let i = 0; i < 50 && !(await b.ev('typeof info !== "undefined" && info.user === "alice"').catch(() => false)); i++) await sleep(100);
    check(await b.ev('info.user') === 'alice', 'group server: signed in after the page reloads');
    check(/signed in as/.test(await b.ev('document.getElementById("userBox").innerText')), 'group server: the user is shown');
    await b.ev('readCircuit("demo_chatter.net").then(r => loadText(r.name, r.text))');
    await b.ev('document.getElementById("engine").value = "cpp"');
    r = await b.runAndWait();
    check(r.n === 50 && !r.err, 'group server: runs on the server', JSON.stringify(r));
    await b.ev('document.getElementById("fileName").value = "my_test"; save()');
    for (let i = 0; i < 30 && !fs.existsSync(path.join(tmp, 'data/alice/my_test.net')); i++) await sleep(100);
    check(fs.existsSync(path.join(tmp, 'data/alice/my_test.net')), 'group server: Save goes to the user\'s folder');
    check(!fs.existsSync(path.join(ROOT, 'circuits/my_test.net')), 'group server: circuits/ is left alone');
    check(b.errors.filter((e) => !/401/.test(e)).length === 0, 'group server: no page errors', b.errors.join('\n'));
    b.close();
    fs.rmSync(tmp, { recursive: true, force: true });
  } finally {
    procs.forEach((p) => p.kill());
  }
  console.log(fails ? fails + ' FAILED' : 'all passed');
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
