// A small CDP driver for the Studio walk. Keeps nothing alive itself: the
// browser runs separately with --remote-debugging-port and every invocation
// attaches to the same page, so state survives between shell calls.
//
// Clicks are real Input.dispatchMouseEvent pairs and assert
// elementFromPoint at the point they press, because el.click() skips hit
// testing and a clamped popover reads green under it (wiki tooling.md
// § Headless browser).
const PORT = process.env.CDP_PORT || 9444;

async function target() {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  const list = await res.json();
  const page = list.find((t) => t.type === 'page');
  if (!page) throw new Error('no page target');
  return page.webSocketDebuggerUrl;
}

class Session {
  constructor(ws) { this.ws = ws; this.id = 0; this.waiting = new Map(); }
  static async open() {
    const ws = new WebSocket(await target());
    const s = new Session(ws);
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && s.waiting.has(msg.id)) { s.waiting.get(msg.id)(msg); s.waiting.delete(msg.id); }
    });
    await new Promise((ok, no) => { ws.addEventListener('open', ok); ws.addEventListener('error', no); });
    return s;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve) => {
      this.waiting.set(id, (msg) => resolve(msg));
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const msg = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    const r = msg.result;
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception?.description ?? r.exceptionDetails));
    return r.result.value;
  }
  close() { this.ws.close(); }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const s = await Session.open();
  try {
    if (cmd === 'goto') {
      await s.send('Page.enable');
      await s.send('Page.navigate', { url: rest[0] });
      await sleep(Number(rest[1] ?? 1500));
      console.log(JSON.stringify({ url: await s.eval('location.href'), title: await s.eval('document.title') }));
    } else if (cmd === 'eval') {
      console.log(JSON.stringify(await s.eval(rest.join(' ')), null, 2));
    } else if (cmd === 'evalfile') {
      const src = await (await import('node:fs/promises')).readFile(rest[0], 'utf8');
      console.log(JSON.stringify(await s.eval(src), null, 2));
    } else if (cmd === 'click') {
      const selector = rest[0];
      const dwell = Number(rest[1] ?? 120);
      const hit = await s.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return {ok: false, why: 'no such element'};
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return {ok: false, why: 'zero-sized', rect: {x: r.x, y: r.y, w: r.width, h: r.height}};
        const cx = Math.round(r.x + r.width / 2), cy = Math.round(r.y + r.height / 2);
        const at = document.elementFromPoint(cx, cy);
        const reachable = at && (at === el || el.contains(at) || at.contains(el));
        return {ok: !!reachable, cx, cy, why: reachable ? null : 'elementFromPoint is ' + (at ? at.tagName + '.' + at.className : 'null'),
                rect: {x: r.x, y: r.y, w: r.width, h: r.height},
                vis: getComputedStyle(el).visibility, disabled: el.disabled ?? null};
      })()`);
      if (!hit.ok) { console.log(JSON.stringify({ clicked: false, ...hit })); process.exitCode = 2; }
      else {
        const p = { x: hit.cx, y: hit.cy, button: 'left', clickCount: 1, buttons: 1 };
        await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: hit.cx, y: hit.cy, buttons: 0 });
        await s.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...p });
        await sleep(dwell);
        await s.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...p, buttons: 0 });
        await sleep(120);
        console.log(JSON.stringify({ clicked: true, dwell, ...hit }));
      }
    } else if (cmd === 'drag') {
      // drag <selector> <fromFrac> <toFrac> [dwell] — horizontal, inside the element
      const [selector, from, to] = rest;
      const dwell = Number(rest[3] ?? 120);
      const box = await s.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null;
        const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()`);
      if (!box) { console.log(JSON.stringify({ dragged: false, why: 'no element' })); process.exitCode = 2; return; }
      const y = Math.round(box.y + box.h / 2);
      const x1 = Math.round(box.x + box.w * Number(from));
      const x2 = Math.round(box.x + box.w * Number(to));
      await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x1, y, buttons: 0 });
      await s.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y, button: 'left', clickCount: 1, buttons: 1 });
      const steps = 12;
      for (let i = 1; i <= steps; i++) {
        await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: Math.round(x1 + ((x2 - x1) * i) / steps), y, button: 'left', buttons: 1 });
        await sleep(dwell / steps);
      }
      await s.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y, button: 'left', clickCount: 1, buttons: 0 });
      await sleep(150);
      console.log(JSON.stringify({ dragged: true, from: x1, to: x2, y }));
    } else if (cmd === 'dragxy') {
      const [x1, y1, x2, y2] = rest.slice(0, 4).map(Number);
      const dwell = Number(rest[4] ?? 120);
      await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x1, y: y1, buttons: 0 });
      await s.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y: y1, button: 'left', clickCount: 1, buttons: 1 });
      const steps = 10;
      for (let i = 1; i <= steps; i++) {
        await s.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: Math.round(x1 + ((x2 - x1) * i) / steps), y: Math.round(y1 + ((y2 - y1) * i) / steps), button: 'left', buttons: 1 });
        await sleep(dwell / steps);
      }
      await s.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y: y2, button: 'left', clickCount: 1, buttons: 0 });
      await sleep(200);
      console.log(JSON.stringify({ dragged: [x1, y1, x2, y2], dwell }));
    } else if (cmd === 'viewport') {
      const [w, h] = rest.slice(0, 2).map(Number);
      await s.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await sleep(400);
      const probe = await s.eval(`(() => {
        const over = [...document.querySelectorAll('body *')]
          .filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
          .map((e) => (e.id || e.className || e.tagName) + '@' + Math.round(e.getBoundingClientRect().right));
        return {innerWidth, scrollWidth: document.body.scrollWidth, overflowing: over.slice(0, 6)};
      })()`);
      console.log(JSON.stringify(probe));
    } else if (cmd === 'shot') {
      const msg = await s.send('Page.captureScreenshot', { format: 'png' });
      const fs = await import('node:fs/promises');
      await fs.writeFile(rest[0], Buffer.from(msg.result.data, 'base64'));
      console.log(JSON.stringify({ saved: rest[0] }));
    } else if (cmd === 'console') {
      // attach, collect console + page errors for N ms
      await s.send('Runtime.enable');
      await s.send('Log.enable');
      const lines = [];
      s.ws.addEventListener('message', (ev) => {
        const m = JSON.parse(ev.data);
        if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type))
          lines.push({ type: m.params.type, text: m.params.args.map((a) => a.value ?? a.description).join(' ') });
        if (m.method === 'Runtime.exceptionThrown')
          lines.push({ type: 'exception', text: m.params.exceptionDetails.exception?.description });
        // `url` is the whole value of this branch: a failed request logs
        // "Failed to load resource: ... 400" and names no route, and
        // guessing which one from a plausible-looking endpoint has already
        // cost a wrong diagnosis here (lucid HISTORY.md § The two console
        // 400s). CDP hands it over; only dropping it made it a mystery.
        if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error')
          lines.push({ type: 'log', text: m.params.entry.text, url: m.params.entry.url });
      });
      await sleep(Number(rest[0] ?? 3000));
      console.log(JSON.stringify(lines, null, 2));
    } else throw new Error(`unknown command: ${cmd}`);
  } finally { s.close(); }
}

main().catch((e) => { console.error(String(e)); process.exit(1); });
