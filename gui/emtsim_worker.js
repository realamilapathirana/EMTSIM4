// Runs the C++ solver compiled to WebAssembly (wasm/emtsim.js, built by gui/build_wasm.py) in a
// background thread, so the page stays responsive and a run can be stopped (worker.terminate()).
//   postMessage({ id, text, chatter, interp })  ->  { id, result }   (result as the server's C++ result)
'use strict';
const CHATTER = { off: 0, cda: 1, detect: 2, rootmatch: 3, pscad: 4 };
let ready = null;
let lines = [];

function solver() {
  if (!ready) {
    importScripts('wasm/emtsim.js');
    ready = createEmtsim({ print: (s) => lines.push(s), printErr: (s) => lines.push(s), locateFile: (f) => 'wasm/' + f });
  }
  return ready;
}

onmessage = async (e) => {
  const { id, text, chatter, interp } = e.data;
  try {
    const M = await solver();
    lines = [];
    const json = M.ccall('emtsim_run', 'string', ['string', 'number', 'number'],
      [text, chatter in CHATTER ? CHATTER[chatter] : -1, interp == null ? -1 : interp ? 1 : 0]);
    const result = JSON.parse(json);
    result.log = lines.filter((l) => l.startsWith('t = ') || l.startsWith('Warning')).join('\n');
    postMessage({ id, result });
  } catch (err) {
    ready = null;   // a trap (out of memory, ...) leaves the module unusable: start a new one next time
    postMessage({ id, result: { error: 'The browser solver failed: ' + (err && err.message ? err.message : err) } });
  }
};
