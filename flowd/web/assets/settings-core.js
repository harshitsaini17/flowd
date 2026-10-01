/* flowd settings page: core helpers, save model, basic controls. F.save goes through F.api
   (settings-api.js) when the page is served by flowd, and is simulated otherwise (the mockup). */
(() => {
  const F = (window.F = {});
  F.$ = (s, r = document) => r.querySelector(s);
  F.$$ = (s, r = document) => [...r.querySelectorAll(s)];
  F.I = (n, s = 16, label) => iconSVG(n, s, label);
  F.rm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  F.esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- fill: each control registers how to show a config value without saving it
  F.fillers = new Map();
  F.onFill = (key, fn) => { if (!F.fillers.has(key)) F.fillers.set(key, []); F.fillers.get(key).push(fn); };
  // `values` is GET /api/config's `values` ({section: {key: value}}), plus `vocab`.
  F.valueOf = (values, key) => {
    const dot = key.indexOf('.');
    if (dot < 0) return values[key];
    const sec = values[key.slice(0, dot)];
    return sec ? sec[key.slice(dot + 1)] : undefined;
  };
  F.fill = (values, only) => {
    for (const [key, fns] of F.fillers) {
      if (only && key !== only) continue;
      const v = F.valueOf(values, key);
      if (v !== undefined) fns.forEach((fn) => fn(v));
    }
  };

  // ---------- announcements
  F.say = (msg) => { const a = F.$('#announce'); a.textContent = ''; setTimeout(() => (a.textContent = msg), 30); };
  F.alert = (msg) => { const a = F.$('#alert'); a.textContent = ''; setTimeout(() => (a.textContent = msg), 30); };

  // ---------- toasts: max 2 visible, undo 5 s, info 4 s, errors stay
  F.toast = (msg, { kind = 'info', action, onAction, ttl } = {}) => {
    const host = F.$('#toasts');
    const icon = { info: 'info', success: 'check', error: 'circle-alert', warn: 'triangle-alert', undo: null }[kind];
    const t = document.createElement('div');
    t.className = `toast ${kind}`;
    t.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    t.innerHTML = `${icon ? F.I(icon) : ''}<span class="msg">${msg}</span>${action ? `<button class="btn ghost sm" data-act>${action}</button>` : ''}<button class="icon-btn" aria-label="Dismiss" data-x>${F.I('x', 14)}</button>`;
    const life = ttl ?? (kind === 'error' ? 0 : kind === 'undo' ? 5000 : 4000);
    let timer, left = life, started;
    const close = () => { clearTimeout(timer); t.classList.add('out'); setTimeout(() => t.remove(), F.rm() ? 80 : 240); };
    const run = () => { if (!life) return; started = Date.now(); timer = setTimeout(close, left); };
    const pause = () => { clearTimeout(timer); if (started) left -= Date.now() - started; };
    t.addEventListener('mouseenter', pause); t.addEventListener('mouseleave', run);
    t.addEventListener('focusin', pause); t.addEventListener('focusout', run);
    t.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    t.querySelector('[data-x]').onclick = close;
    if (action) t.querySelector('[data-act]').onclick = () => { onAction?.(); close(); };
    host.appendChild(t);
    while (host.children.length > 2) host.firstElementChild.remove();
    run();
    return close;
  };

  // ---------- save model: row feedback and the header save state are shared with settings-api.js
  const saveState = () => F.$('#saveState');
  const setGlobal = (F.setGlobal = (s) => {
    const el = saveState();
    el.dataset.s = s;
    const map = { saved: ['check', 'All changes saved'], saving: ['loader-circle', 'Saving…'], error: ['circle-alert', 'Couldn’t save'], offline: ['check', 'Saved · applies when flowd starts'] };
    const [ic, tx] = map[s];
    el.innerHTML = `${F.I(ic, 14)}<span class="txt">${tx}</span>`;
    if (s === 'error') { const b = document.createElement('button'); b.className = 'link-btn'; b.textContent = 'Retry'; b.onclick = () => F.retry?.(); el.appendChild(b); }
  });
  // Row feedback: 'saving' (spinner), 'saved' (check, fades), or null (cleared).
  F.feedback = (el, s) => {
    const fb = el.closest('.ctl')?.querySelector('.feedback') || el.closest('.row')?.querySelector('.feedback');
    if (!fb) return;
    if (s === 'saving') { fb.dataset.s = 'saving'; fb.innerHTML = F.I('loader-circle', 12); return; }
    if (!s) { delete fb.dataset.s; fb.innerHTML = ''; return; }
    fb.innerHTML = `<span class="ok">${F.I('check', 12)}</span>Saved`;
    fb.dataset.s = 'saved'; fb.style.animation = 'none'; void fb.offsetWidth; fb.style.animation = '';
  };
  F.state = { failNext: false, daemon: true, cleanup: true, restartKeys: new Set(), conflict: false };
  F.save = (el, key, value, opts = {}) => (F.api ? F.api.save(el, key, value, opts) : demoSave(el, key, value, opts));
  // The mockup's save: no network, random latency, and the state gallery can make it fail.
  const demoSave = (el, key, value, { revert } = {}) => {
    const restart = !!el.closest?.('[data-restart]');
    const slow = setTimeout(() => { F.feedback(el, 'saving'); setGlobal('saving'); }, 300);
    const latency = 180 + Math.random() * 380; // sometimes > 300 ms so the spinner shows
    return new Promise((resolve) => setTimeout(() => {
      clearTimeout(slow);
      if (F.state.failNext) {
        F.state.failNext = false;
        F.feedback(el, null);
        setGlobal('error');
        F.retry = () => F.save(el, key, value, { revert });
        revert?.();
        F.alert(`Couldn’t save ${key}. The previous value is still in use.`);
        F.toast(`Couldn’t save <span class="mono">${F.esc(key)}</span>. config.toml isn’t writable.`, { kind: 'error', action: 'Retry', onAction: () => F.retry() });
        return resolve(false);
      }
      F.feedback(el, 'saved');
      setGlobal(F.state.daemon ? 'saved' : 'offline');
      F.say(restart ? 'Saved. Takes effect after restart.' : 'Saved');
      if (restart) { F.state.restartKeys.add(key); F.updateRestart(); }
      resolve(true);
    }, latency));
  };
  F.updateRestart = () => {
    const n = F.state.restartKeys.size, b = F.$('#restartBanner');
    b.hidden = n === 0;
    F.$('#restartCount').textContent = `${n} change${n === 1 ? '' : 's'}`;
    b.querySelector('.bt').lastChild.textContent = n === 1 ? ' takes effect after flowd restarts.' : ' take effect after flowd restarts.';
  };

  // ---------- validation mirrors flowd/config.py
  F.validate = (input) => {
    const raw = input.value.trim(), d = input.dataset;
    if (d.loopback !== undefined) {
      try { const u = new URL(raw); if (!['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname)) return 'Cleanup must run on this machine (127.0.0.1, localhost or ::1).'; } catch { return 'Enter a full URL, like http://127.0.0.1:8177'; }
      return null;
    }
    if (d.min === undefined && d.gt === undefined) return null;
    if (raw === '') return 'Enter a value.';
    const v = Number(raw);
    if (!Number.isFinite(v)) return 'Must be a number.';
    if (d.gt !== undefined && v <= Number(d.gt)) return `Must be above ${d.gt}.`;
    if (d.int !== undefined && !Number.isInteger(v)) return 'Must be a whole number above 0.';
    if (d.min !== undefined && v < Number(d.min)) return Number(d.min) === 1 ? 'Must be a whole number above 0.' : `Must be at least ${d.min}.`;
    if (d.max !== undefined && v > Number(d.max)) return `Must be ${d.max} or less.`;
    if (d.pair) {
      const other = document.getElementById(d.pair), ov = Number(other.value);
      if (Number.isFinite(ov)) {
        if (d.pairRole === 'min' && v > ov) return `Can’t exceed the maximum (${ov}).`;
        if (d.pairRole === 'max' && v < ov) return `Can’t be below the minimum (${ov}).`;
      }
    }
    return null;
  };
  F.showErr = (input, msg, lastGood) => {
    const row = input.closest('.lab, .ctl')?.closest('.row') || input.parentElement;
    const host = input.closest('.ctl') || input.parentElement;
    const num = input.closest('.num');
    let err = row.querySelector('.field-err');
    if (!msg) {
      input.removeAttribute('aria-invalid'); num?.classList.remove('invalid'); num?.querySelector('.err-ico')?.remove(); err?.remove();
      input.setAttribute('aria-describedby', (input.getAttribute('aria-describedby') || '').replace(/\s*err-\S+/g, '').trim());
      return;
    }
    input.setAttribute('aria-invalid', 'true');
    if (num && !num.querySelector('.err-ico')) { num.classList.add('invalid'); num.insertAdjacentHTML('afterbegin', `<span class="err-ico">${F.I('circle-alert', 14)}</span>`); }
    if (!err) {
      err = document.createElement('div'); err.className = 'field-err'; err.id = `err-${Math.random().toString(36).slice(2, 8)}`;
      (row.querySelector('.lab') || host).appendChild(err);
      input.setAttribute('aria-describedby', `${input.getAttribute('aria-describedby') || ''} ${err.id}`.trim());
    }
    err.innerHTML = `${F.I('circle-alert', 14)}<span>${msg}${lastGood != null ? ` Still using ${F.esc(lastGood)}.` : ''}</span>`;
  };

  // ---------- toggles
  F.initSwitch = (sw) => {
    sw.querySelector('.chk').innerHTML = F.I('check', 10);
    const show = (on) => { sw.setAttribute('aria-checked', String(on)); sw.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: on })); };
    if (sw.dataset.key) F.onFill(sw.dataset.key, (v) => { if ((sw.getAttribute('aria-checked') === 'true') !== !!v) show(!!v); });
    sw.addEventListener('click', async () => {
      if (sw.disabled) return;
      const prev = sw.getAttribute('aria-checked') === 'true';
      show(!prev);
      if (!sw.dataset.key) return; // UI-only (data-ui-only): its page wiring saves
      const ok = await F.save(sw, sw.dataset.key, !prev, {
        revert: () => { sw.setAttribute('aria-checked', String(prev)); sw.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: prev })); if (!F.rm()) { sw.classList.remove('shake'); void sw.offsetWidth; sw.classList.add('shake'); } },
      });
      return ok;
    });
  };

  // ---------- segmented: roving tabindex, arrows move AND select
  F.initSegmented = (seg, onPick) => {
    const bs = () => F.$$('button', seg);
    const pick = (b, silent) => {
      bs().forEach((x) => { const on = x === b; x.setAttribute('aria-checked', String(on)); x.tabIndex = on ? 0 : -1; });
      onPick?.(b.dataset.v, b);
      if (!silent && seg.dataset.key) F.save(seg, seg.dataset.key, b.dataset.v);
    };
    if (seg.dataset.key) F.onFill(seg.dataset.key, (v) => { const b = bs().find((x) => x.dataset.v === String(v)); if (b) pick(b, true); });
    seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && b.getAttribute('aria-checked') !== 'true') pick(b); });
    seg.addEventListener('keydown', (e) => {
      const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (!(e.key in keys) && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      const list = bs(), i = list.indexOf(document.activeElement);
      const n = e.key === 'Home' ? list[0] : e.key === 'End' ? list.at(-1) : list[(i + keys[e.key] + list.length) % list.length];
      n.focus(); pick(n);
    });
    return { pick: (v, silent = true) => pick(bs().find((b) => b.dataset.v === v), silent) };
  };

  // ---------- number / text inputs: validate on blur + Enter, auto-save 800 ms after typing if valid
  // Numeric inputs (data-min) save numbers; data-scale shows value × scale (e.g. 0.2 as 20 %).
  const tidy = (x) => Math.round(x * 1e9) / 1e9;
  F.initInput = (input) => {
    let last = input.value, timer;
    const d = input.dataset, scale = d.scale ? +d.scale : 1;
    const numeric = d.min !== undefined || d.gt !== undefined;
    const out = () => (!numeric ? input.value.trim() : tidy(Number(input.value.trim()) / scale));
    const unit = () => input.closest('.num')?.querySelector('.unit')?.textContent || '';
    if (d.key) F.onFill(d.key, (v) => { clearTimeout(timer); input.value = last = v == null ? '' : !numeric ? String(v) : String(tidy(v * scale)); F.showErr(input, null); });
    const commit = () => {
      clearTimeout(timer);
      if (input.value === last) { F.showErr(input, null); return; }
      const msg = F.validate(input);
      if (msg) { F.showErr(input, msg, last + (unit() ? ' ' + unit() : '')); return; }
      F.showErr(input, null);
      if (input.dataset.pair) { const o = document.getElementById(input.dataset.pair); if (o?.getAttribute('aria-invalid') && !F.validate(o)) F.showErr(o, null); }
      const prev = last; last = input.value;
      F.save(input, d.key || input.id, out(), { lastGood: prev + (unit() ? ' ' + unit() : ''), revert: () => { input.value = prev; last = prev; } });
    };
    if (numeric) {
      input.addEventListener('beforeinput', (e) => { if (e.data && /[^\d.\-]/.test(e.data)) e.preventDefault(); });
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { if (!F.validate(input)) commit(); }, 800); });
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } });
  };

  // ---------- slider with bound number input; saves on release / 400 ms after keys
  // data-min / data-max are config.py's validated bounds (no data-max: unbounded) and bound the
  // number twin. data-range-min / data-range-max are the slider's comfortable range; a value
  // outside it widens the slider rather than being clamped. Only user input saves: filling the
  // page, or the range input snapping a value to its step, never writes.
  F.initSlider = (host, onLive) => {
    const d = host.dataset, id = `sl-${Math.random().toString(36).slice(2, 7)}`;
    const lo = +(d.rangeMin ?? d.min), hi = +(d.rangeMax ?? d.max), step = +d.step, def = +d.default;
    host.innerHTML = `<div class="slider-col"><input type="range"><div class="ticks"><span class="tick">default</span></div></div>
      <div class="num"><input class="input" inputmode="numeric" data-int><span class="unit"></span></div>`;
    const r = host.querySelector('input[type=range]'), n = host.querySelector('.num input');
    Object.assign(r, { id, min: lo, max: hi, step, value: d.slider });
    r.setAttribute('aria-labelledby', d.label); if (d.desc) r.setAttribute('aria-describedby', d.desc);
    n.value = d.slider; n.dataset.min = d.min; if (d.max !== undefined) n.dataset.max = d.max;
    n.setAttribute('aria-label', `${document.getElementById(d.label)?.firstChild?.textContent.trim() || ''} value`);
    host.querySelector('.unit').textContent = d.unit;
    let cur = +d.slider, saved = cur, keyT;
    const pct = (v) => ((v - +r.min) / (+r.max - +r.min)) * 100;
    // A value outside the slider's normal range widens it. While widened, step is 'any', so the
    // browser does not snap an off-grid value (5 ms, 8000 ms) to the authored step.
    const fit = (v) => { const wide = v < lo || v > hi; r.min = Math.min(lo, v); r.max = Math.max(hi, v); r.step = wide ? 'any' : step; r.value = v; };
    const paint = () => {
      r.style.setProperty('--p', `${pct(+r.value)}%`);
      r.setAttribute('aria-valuetext', `${cur} ${d.unit === 'ms' ? 'milliseconds' : d.unit}`);
      host.querySelector('.tick').style.left = `calc(8px + (100% - 16px) * ${pct(def) / 100})`;
    };
    const warn = () => {
      const row = host.closest('.row'); let w = row.querySelector('.field-warn.sl');
      const over = d.warnAbove && cur > +d.warnAbove;
      n.style.borderColor = over ? 'var(--warn)' : '';
      if (over && !w) {
        w = document.createElement('div'); w.className = 'field-warn sl';
        w.innerHTML = F.I('triangle-alert', 14);
        const t = document.createElement('span'); t.textContent = d.warn; w.appendChild(t);
        row.querySelector('.lab').appendChild(w);
      }
      if (!over) w?.remove();
    };
    // Called only from user events, after `cur` was set from what the user did.
    const commit = () => {
      clearTimeout(keyT);
      if (cur === saved) return;
      const prev = saved; saved = cur;
      F.save(host, d.key, cur, { revert: () => { cur = saved = prev; n.value = prev; fit(prev); paint(); warn(); onLive?.(prev); } });
    };
    let moved = false;
    r.addEventListener('input', () => { moved = true; cur = +r.value; n.value = cur; F.showErr(n, null); paint(); warn(); onLive?.(cur); });
    r.addEventListener('change', () => { if (moved) { moved = false; commit(); } }); // pointer release
    r.addEventListener('keydown', (e) => {
      if (e.key === 'PageUp' || e.key === 'PageDown') { e.preventDefault(); r.value = Math.min(+r.max, Math.max(+r.min, +r.value + (e.key === 'PageUp' ? 10 : -10) * step)); r.dispatchEvent(new Event('input')); }
      // Tab and other keys that don't move the slider leave `moved` false: nothing is saved.
      clearTimeout(keyT); keyT = setTimeout(() => { if (moved) { moved = false; commit(); } }, 400);
    });
    const numCommit = () => {
      if (n.value.trim() === String(cur)) { F.showErr(n, null); return; }
      const msg = F.validate(n);
      if (msg) { F.showErr(n, msg, `${saved} ${d.unit}`); return; }
      F.showErr(n, null);
      cur = Number(n.value.trim()); fit(cur); paint(); warn(); onLive?.(cur); commit();
    };
    n.addEventListener('blur', numCommit);
    n.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); numCommit(); } });
    paint();
    const set = (v) => { cur = saved = +v; n.value = String(v); moved = false; clearTimeout(keyT); fit(cur); F.showErr(n, null); paint(); warn(); onLive?.(cur); };
    if (d.key) F.onFill(d.key, set);
    return { set };
  };

  // ---------- select (native)
  F.initSelect = (sel, onPick) => {
    let prev = sel.value;
    if (sel.dataset.key) F.onFill(sel.dataset.key, (v) => {
      v = String(v);
      if (![...sel.options].some((o) => o.value === v)) { const o = document.createElement('option'); o.value = o.textContent = v; sel.appendChild(o); }
      sel.value = prev = v; onPick?.(v);
    });
    sel.addEventListener('change', () => { const p = prev; prev = sel.value; onPick?.(sel.value); F.save(sel, sel.dataset.key, sel.value, { revert: () => { sel.value = prev = p; onPick?.(p); } }); });
  };

  // ---------- copy button: check + "Copied" 1.5 s; failure selects text
  F.initCopy = (btn, getText, label) => {
    const orig = btn.innerHTML;
    btn.setAttribute('aria-label', label || 'Copy');
    btn.addEventListener('click', async () => {
      const text = getText();
      try {
        if (!navigator.clipboard) throw new Error('no clipboard');
        await navigator.clipboard.writeText(text);
        btn.dataset.s = 'ok'; btn.innerHTML = `${F.I('check', 14)}<span>Copied</span>`; F.say('Copied');
      } catch {
        btn.dataset.s = 'err'; btn.innerHTML = `${F.I('circle-alert', 14)}<span>Select and copy manually</span>`;
        const pre = btn.closest('.snippet')?.querySelector('pre');
        if (pre) { const range = document.createRange(); range.selectNodeContents(pre); getSelection().removeAllRanges(); getSelection().addRange(range); }
        F.say('Copy failed. The text is selected; press Ctrl+C.');
      }
      setTimeout(() => { delete btn.dataset.s; btn.innerHTML = orig; }, 1500);
    });
  };
})();
