/* flowd settings page: the daemon client (ADR 0014). Loaded by settings.js only when the page is
   served by flowd (<html data-api>). Defines F.api before the page wiring boots, so the wiring
   skips its demo data; F.api.start() then loads the real config, vocab, status and stats.

   Every request carries the page's bearer token. flowctl settings opens the page with it in the
   URL fragment; it is moved to sessionStorage and taken out of the address bar at once. */
(() => {
  const F = window.F;
  const { $, $$, I, esc, say, toast } = F;

  // ---------- token
  const TOKEN_KEY = 'flowd-token';
  let token = '';
  const fromHash = /^#token=([\w-]+)$/.exec(location.hash);
  if (fromHash) {
    token = fromHash[1];
    try { sessionStorage.setItem(TOKEN_KEY, token); } catch {}
    history.replaceState(null, '', location.pathname + location.search);
  } else {
    try { token = sessionStorage.getItem(TOKEN_KEY) || ''; } catch {}
  }

  // ---------- requests
  class NetworkError extends Error {}
  // Resolves { status, data } for any HTTP reply; rejects with NetworkError when flowd is unreachable.
  const req = async (method, path, body) => {
    const init = { method, cache: 'no-store', headers: { Authorization: `Bearer ${token}` } };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    let r;
    try { r = await fetch(path, init); } catch (e) { throw new NetworkError(String(e)); }
    let data = {};
    try { data = await r.json(); } catch {}
    return { status: r.status, data };
  };
  const errText = (res) => esc(res.data?.error || `HTTP ${res.status}`);

  // ---------- state
  let cfg = null; // last GET /api/config reply: { etag, values, defaults, applies, in_file }
  let vocab = null; // { etag, terms, replace }
  let lastModes = {}; // the effective app → mode map last saved, to diff the apps table against
  let started = false;

  // Writes run one at a time: each needs the etag the previous one returned.
  let queue = Promise.resolve();
  const serial = (fn) => { const p = queue.then(fn, fn); queue = p.catch(() => {}); return p; };

  // ---------- read-only
  let ro = null; // null | 'token' | 'session' | 'daemon'
  const RO_TEXT = {
    token: 'Open this page with <span class="mono">flowctl settings</span>.',
    session: 'This page’s session has ended. Open it again with <span class="mono">flowctl settings</span>.',
    daemon: 'flowd isn’t running. Start it with <span class="mono">systemctl --user start flowd</span>.',
  };
  const RO_SEL = ['.content [data-key]', '.content [data-ui-only]', '.content [data-reset]', '.content .segmented[data-key] button', '[data-tags] input', '[data-tags] button', '#repTable input', '#repTable button', '#appTable input', '#appTable button', '#order button', '#devPicker button', '[data-slider] input', '#resetAll', '#detectApp', '#resetPos', '#micTest', '#restartNow', '#checkNow'].join(', ');
  // Disables the editable controls under `root`. Widgets call F.rendered after each re-render,
  // so rows drawn later (a filtered table, a new tag) are covered too.
  const lock = (root) => {
    const els = $$(RO_SEL, root);
    if (root !== document && root.matches(RO_SEL)) els.push(root);
    els.forEach((el) => { if (!el.disabled && 'disabled' in el) { el.disabled = true; el.dataset.ro = ''; } });
  };
  F.rendered = (root) => { if (ro) lock(root); };
  const setRo = (why) => {
    ro = why;
    $('#roBanner').hidden = !why;
    $('#roText').innerHTML = why ? RO_TEXT[why] : '';
    if (why) {
      lock(document);
      F.setGlobal('offline');
      $('#saveState .txt').textContent = 'Read-only';
    } else {
      $$('[data-ro]').forEach((el) => { el.disabled = false; delete el.dataset.ro; });
      F.setGlobal('saved');
    }
  };

  // ---------- filling the page from the daemon
  const restartBadge = () => `<span class="badge restart">${I('power', 12)}Requires restart</span>`;
  const markRestartKeys = (applies) => {
    $$('[data-key], [data-list-key]').forEach((el) => {
      const key = el.dataset.key || el.dataset.listKey;
      if (applies[key] !== 'restart') return;
      const t = el.closest('.row')?.querySelector('.lab .t');
      if (t && !t.querySelector('.badge.restart')) t.insertAdjacentHTML('beforeend', ` ${restartBadge()}`);
    });
  };
  const setPending = (keys) => { if (keys) { F.state.restartKeys = new Set(keys); F.updateRestart(); } };
  const modeRows = (values, defaults) => {
    const builtins = Object.entries(defaults.modes || {});
    const rows = builtins.map(([k, orig]) => ({ k, v: values.modes?.[k] ?? orig, orig }));
    for (const [k, v] of Object.entries(values.modes || {})) if (!(k in (defaults.modes || {}))) rows.push({ k, v });
    return { builtins, rows };
  };
  const applyConfig = (reply) => {
    cfg = reply;
    const { values, defaults } = reply;
    F.fill(values);
    const w = F.w;
    w.cues.set(values.chunking.correction_cues);
    w.termTags.set(values.inject.terminal_apps);
    w.order.set(values.inject.order);
    w.dev.set(values.audio.device);
    w.defaults = { cues: defaults.chunking.correction_cues, terminals: defaults.inject.terminal_apps, order: defaults.inject.order };
    const { builtins, rows } = modeRows(values, defaults);
    if (!w.apps) w.apps = w.makeApps(builtins);
    w.apps.set(rows);
    lastModes = { ...values.modes };
    try { $('#llmWhere').textContent = new URL(values.llm.url).host; } catch { $('#llmWhere').textContent = values.llm.url; }
    markRestartKeys(reply.applies || {});
    setPending(reply.restart_pending);
  };
  const applyVocab = (reply) => {
    vocab = { etag: reply.etag, terms: reply.terms, replace: reply.replace };
    F.w.terms.set(reply.terms);
    F.w.rep.set(Object.entries(reply.replace).map(([k, v]) => ({ k, v })));
    tryIt();
  };

  // Loads config and vocab. Returns false (and goes read-only) when that is not possible.
  const loadConfig = async () => {
    const [c, v] = await Promise.all([req('GET', '/api/config'), req('GET', '/api/vocab')]);
    if (c.status === 403 || v.status === 403) { setRo('session'); return false; }
    if (c.status !== 200) { toast(`Couldn’t read config.toml: ${errText(c)}`, { kind: 'error' }); return false; }
    applyConfig(c.data);
    if (v.status === 200) applyVocab(v.data);
    else toast(`Couldn’t read vocab.toml: ${errText(v)}`, { kind: 'error' });
    return true;
  };

  // ---------- status, stats, devices, paste tools
  let desktopSet = false;
  const applyStatus = (s) => {
    const w = F.w, d = s.daemon || {};
    w.setDaemon(true);
    w.setCleanup(d.cleanup || 'offline');
    $('#st-models').innerHTML = `Speech ${w.badge('ok', 'circle-check', esc(d.stt_model || 'Ready'))}`;
    const mb = (s.memory || []).reduce((a, m) => a + (Number(m.anon_mb) || 0), 0);
    w.memory = { mb, budget: Number(s.budget_mb) || 1600 };
    $('#st-mem').innerHTML = `${I('memory-stick', 14)}<span class="tnum">${w.fmtMem(mb)} memory</span>`;
    $('#st-mem').title = (s.memory || []).map((m) => `${m.name}: ${w.fmtMem(m.anon_mb)}`).join(', ') || 'Memory flowd is using';
    $('#hcAgo').textContent = d.health_checked_s_ago == null ? 'not checked yet' : `checked ${Math.round(d.health_checked_s_ago)} s ago`;
    if (!desktopSet && s.desktop) { desktopSet = true; w.setDesktop(s.desktop); }
    w.renderPerfCards();
    F.renderOverview();
  };
  const loadStats = async () => {
    const r = await req('GET', '/api/stats');
    if (r.status !== 200) return;
    const list = (r.data.sessions || []).filter((s) => typeof s.ts === 'number').map((s) => ({
      ts: s.ts * 1000, app: String(s.app_id || 'unknown'), name: String(s.app_id || 'Unknown app'), mode: String(s.mode || 'default'),
      words: Number(s.words) || 0, speak: Number(s.speak_s) || 0, ms: Number(s.paste_ms) || 0, fb: !!s.fallback, via: String(s.backend || '—'),
    }));
    const lat = r.data.latency || {};
    const num = (v) => (v == null || !Number.isFinite(Number(v)) ? null : Number(v));
    F.w.setSessions(list, { p50: num(lat.p50), p95: num(lat.p95), fbRate: num(r.data.fallback_rate) });
  };
  const loadDevices = async () => {
    const r = await req('GET', '/api/status?devices=1');
    const base = { id: 'default', name: 'System default', node: 'PipeWire default source' };
    // 409: the microphone is held (a dictation, or audio.always_open keeps it open).
    if (r.status !== 200 || !Array.isArray(r.data.devices)) { F.w.dev.setOptions([base], false); F.w.dev.set(cfg?.values.audio.device ?? 'default'); return; }
    const opts = [base, ...r.data.devices.filter((d) => d.name !== 'default').map((d) => ({ id: String(d.name), name: String(d.name), node: d.default ? 'System default input' : 'Input device' }))];
    F.w.dev.setOptions(opts);
    F.w.dev.set(cfg?.values.audio.device ?? 'default');
  };
  const loadBackends = async () => {
    const r = await req('GET', '/api/inject-backends');
    if (r.status !== 200) return;
    const list = r.data.backends || [];
    F.w.order.setStatus(list);
    $('#ydoBanner').hidden = !list.some((b) => b.name === 'ydotool' && b.status === 'stopped');
  };

  // ---------- status poll: every 5 s while the page is visible
  let restarting = false, pollT;
  const poll = async () => {
    clearTimeout(pollT);
    if (document.visibilityState === 'visible' && !restarting && ro !== 'token' && ro !== 'session') {
      try {
        const r = await req('GET', '/api/status');
        if (r.status === 403) setRo('session');
        else if (r.status === 200) {
          applyStatus(r.data);
          if (ro === 'daemon' && (await loadConfig())) { setRo(null); loadStats(); loadBackends(); say('flowd is running again'); }
        }
      } catch (e) {
        if (!(e instanceof NetworkError)) throw e;
        if (ro !== 'daemon') { setRo('daemon'); F.w.setDaemon(false); }
      }
    }
    pollT = setTimeout(poll, 5000);
  };
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });

  // ---------- saving
  const modeChanges = (rows) => {
    const builtin = cfg.defaults.modes || {}, next = Object.fromEntries(rows.map(({ k, v }) => [k, v])), changes = {};
    for (const k of Object.keys(lastModes)) if (!(k in next)) changes[`modes.${k}`] = null;
    for (const [k, v] of Object.entries(next)) if (lastModes[k] !== v) changes[`modes.${k}`] = builtin[k] === v ? null : v;
    return changes;
  };
  // One write: { status, data } of the PATCH, or null when there was nothing to send.
  const send = (key, value) => {
    if (key === 'vocab.terms' || key === 'vocab.replace') {
      const terms = key === 'vocab.terms' ? value : vocab.terms;
      const replace = key === 'vocab.replace' ? Object.fromEntries(value.map(({ k, v }) => [k, v])) : vocab.replace;
      return req('PATCH', '/api/vocab', { etag: vocab.etag, terms, replace }).then((r) => {
        if (r.data.etag && r.status !== 409) vocab.etag = r.data.etag;
        // 200, or a 500 that carries an etag ("saved, but flowd could not apply it"): written.
        if (r.status === 200 || (r.status >= 500 && r.data.etag)) { vocab.terms = terms; vocab.replace = replace; }
        return r;
      });
    }
    const changes = key === 'modes' ? modeChanges(value) : { [key]: value };
    if (!Object.keys(changes).length) return Promise.resolve(null);
    return req('PATCH', '/api/config', { etag: cfg.etag, changes }).then((r) => {
      if (r.data.etag && r.status !== 409) cfg.etag = r.data.etag;
      if (r.data.in_file && r.status !== 409) cfg.in_file = r.data.in_file; // the base for group-reset Undo
      if (r.status === 200) {
        cfg.values = r.data.values;
        lastModes = { ...r.data.values.modes };
        setPending(r.data.restart_pending);
      }
      return r;
    });
  };

  // Refreshes cfg from the file without refilling the controls (the user's edit stays shown).
  const refetchConfig = async () => {
    const c = await req('GET', '/api/config').catch(() => null);
    if (c?.status !== 200) return;
    cfg = c.data; lastModes = { ...c.data.values.modes }; setPending(c.data.restart_pending);
  };

  // Writes stopped by a 409 (saves and resets), replayed by "Keep my changes".
  let conflicted = [];
  const showConflict = () => {
    if ($('#conflictBanner')) return;
    $('#restartBanner').insertAdjacentHTML('beforebegin', `<div class="banner" id="conflictBanner" role="alert">${I('triangle-alert', 16)}<div class="bt"><b>config.toml was edited outside this page.</b> Reload to see those changes, or keep yours and overwrite the file.</div><div class="ba"><button class="btn sm primary" id="cfReload">Reload page</button><button class="btn sm" id="cfKeep">Keep my changes</button></div></div>`);
    $('#cfReload').addEventListener('click', () => location.reload());
    $('#cfKeep').addEventListener('click', keepMine);
    scrollTo({ top: 0, behavior: F.rm() ? 'auto' : 'smooth' });
  };
  const keepMine = () => serial(async () => {
    $('#conflictBanner')?.remove();
    const [c, v] = await Promise.all([req('GET', '/api/config'), req('GET', '/api/vocab')]);
    if (c.status === 200) { cfg.etag = c.data.etag; cfg.defaults = c.data.defaults; }
    if (v.status === 200) vocab.etag = v.data.etag;
    const todo = conflicted; conflicted = [];
    todo.forEach((replay) => replay());
  });

  const save = (el, key, value, opts = {}) => serial(async () => {
    if (ro || !cfg) {
      opts.revert?.();
      toast(ro ? RO_TEXT[ro] : 'Still loading your settings. Try again in a moment.', { kind: 'info' });
      return false;
    }
    const slow = setTimeout(() => { F.feedback(el, 'saving'); F.setGlobal('saving'); }, 300);
    let r;
    try {
      r = await send(key, value);
    } catch (e) {
      clearTimeout(slow);
      if (!(e instanceof NetworkError)) throw e;
      F.feedback(el, null);
      F.retry = () => save(el, key, value, opts);
      F.setGlobal('error');
      F.alert(`Couldn’t save ${key}.`);
      toast(`Couldn’t reach flowd to save <span class="mono">${esc(key)}</span>.`, { kind: 'error', action: 'Retry', onAction: () => F.retry() });
      return false;
    }
    clearTimeout(slow);
    if (r === null || r.status === 200) {
      F.feedback(el, 'saved');
      F.setGlobal('saved');
      const restart = r && key !== 'modes' && !key.startsWith('vocab.') && r.data.applied?.[key] === 'restart';
      say(restart ? 'Saved. Takes effect after restart.' : 'Saved');
      if (key === 'logging.recordings_dir') F.fill(cfg.values, key);
      return true;
    }
    F.feedback(el, null);
    if (r.status === 409) {
      conflicted.push(() => save(el, key, value, opts));
      F.setGlobal('error');
      showConflict();
      return false;
    }
    if (r.status === 403) { opts.revert?.(); setRo('session'); return false; }
    if (r.status === 422) {
      const isInput = el.matches?.('input');
      if (isInput) F.showErr(el, errText(r), opts.lastGood);
      else toast(`Couldn’t save <span class="mono">${esc(key)}</span>: ${errText(r)}`, { kind: 'error' });
      F.alert(`Couldn’t save ${key}: ${r.data.error || ''}`);
      opts.revert?.();
      F.setGlobal('saved');
      return false;
    }
    if (r.status >= 500 && r.data.etag) {
      // Written to disk, but the daemon's reload failed: the file is ahead of the running config.
      // Re-read it so values, the modes baseline and the restart banner follow the file.
      if (!key.startsWith('vocab.')) await refetchConfig();
      F.feedback(el, 'saved');
      F.setGlobal('saved');
      toast(errText(r), { kind: 'warn', ttl: 8000 });
      return true;
    }
    F.retry = () => save(el, key, value, opts);
    F.setGlobal('error');
    toast(`Couldn’t save <span class="mono">${esc(key)}</span>: ${errText(r)}`, { kind: 'error', action: 'Retry', onAction: () => F.retry() });
    return false;
  });

  // ---------- resets
  // A group's "Reset to defaults" removes exactly the keys its controls edit (one PATCH of nulls),
  // so the defaults apply; Undo writes back what the file held for those keys. "Reset all" empties
  // the file through /api/config/reset, which keeps config.toml.bak.
  const groupKeys = (btn) => [...new Set($$('[data-key], [data-list-key]', btn.closest('.group')).map((el) => el.dataset.key || el.dataset.listKey))];
  const fileValue = (key) => { const [sec, name] = [key.slice(0, key.indexOf('.')), key.slice(key.indexOf('.') + 1)]; return cfg.in_file?.[sec]?.[name]; };
  const written = (r) => r.status === 200 || (r.status >= 500 && r.data.etag);
  const reset = (btn, keys, label) => serial(async () => {
    if (ro || !cfg) { toast(ro ? RO_TEXT[ro] : 'Still loading your settings.', { kind: 'info' }); return; }
    const all = keys === null;
    const undo = all ? null : Object.fromEntries(keys.map((k) => [k, fileValue(k) ?? null]));
    let r;
    try {
      r = all ? await req('POST', '/api/config/reset', { etag: cfg.etag, section: null }) : await req('PATCH', '/api/config', { etag: cfg.etag, changes: Object.fromEntries(keys.map((k) => [k, null])) });
    } catch (e) {
      if (!(e instanceof NetworkError)) throw e;
      toast('Couldn’t reach flowd to reset.', { kind: 'error' }); return;
    }
    if (r.status === 409) { conflicted.push(() => reset(btn, keys, label)); showConflict(); return; }
    if (r.status === 403) { setRo('session'); return; }
    if (!written(r)) { toast(`Couldn’t reset: ${errText(r)}`, { kind: 'error' }); return; }
    cfg.etag = r.data.etag;
    await loadConfig(); // refills every control and in_file, the base for the next Undo
    if (r.status >= 500) toast(errText(r), { kind: 'warn', ttl: 8000 });
    if (all) { toast('All settings reset. Backup saved as config.toml.bak.', { kind: 'success' }); return; }
    const changed = Object.values(undo).some((v) => v !== null);
    if (!changed) { toast(`${esc(label)} already uses the defaults.`, { kind: 'info' }); return; }
    toast(`${esc(label)} reset to defaults.`, { kind: 'undo', action: 'Undo', onAction: () => serial(async () => {
      const u = await req('PATCH', '/api/config', { etag: cfg.etag, changes: undo }).catch(() => null);
      if (u && written(u)) { cfg.etag = u.data.etag; await loadConfig(); say('Previous values restored'); }
      else { if (u?.status === 409) showConflict(); toast(`Couldn’t undo: ${u ? errText(u) : 'flowd is unreachable'}`, { kind: 'error' }); }
    }) });
  });

  // ---------- vocabulary "Try it"
  let tryT, trySeq = 0;
  const tryIt = () => {
    clearTimeout(tryT);
    tryT = setTimeout(async () => {
      const text = $('#tryIn').value.slice(0, 2000), seq = ++trySeq;
      if (!text.trim() || !token || ro === 'token') { $('#tryOut').textContent = ''; return; }
      const replace = Object.fromEntries(F.w.rep.get().map(({ k, v }) => [k, v]));
      try {
        const r = await req('POST', '/api/vocab/test', { text, replace });
        if (seq === trySeq && r.status === 200) $('#tryOut').textContent = r.data.text;
      } catch {}
    }, 300);
  };

  // ---------- microphone test (server-sent events over a POST)
  let micAbort = null;
  const micTest = async () => {
    if (micAbort) { micAbort.abort(); return; }
    const ctl = (micAbort = new AbortController());
    let res;
    try {
      res = await fetch('/api/mic-test', { method: 'POST', cache: 'no-store', signal: ctl.signal, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ seconds: 15 }) });
    } catch {
      micAbort = null;
      // Stop pressed before the stream opened is not a failure.
      if (!ctl.signal.aborted) toast('Couldn’t reach flowd to test the microphone.', { kind: 'error' });
      return;
    }
    if (res.status === 403) { micAbort = null; setRo('session'); return; }
    if (res.status !== 200) {
      micAbort = null;
      let msg = `HTTP ${res.status}`; try { msg = (await res.json()).error || msg; } catch {}
      toast(res.status === 409 ? `The microphone is busy: ${esc(msg)}` : `Couldn’t test the microphone: ${esc(msg)}`, { kind: res.status === 409 ? 'info' : 'error' });
      return;
    }
    F.w.micUi(true);
    $('#micCap').textContent = 'Listening…';
    const reader = res.body.getReader(), dec = new TextDecoder();
    const rms = []; let peak = -90, capAt = 0, end = null, buf = '';
    const onEvent = (name, data) => {
      if (name === 'level') {
        F.w.meter(data.rms);
        rms.push(data.rms); if (rms.length > 20) rms.shift();
        peak = Math.max(data.peak, peak - 1.5);
        if (Date.now() - capAt > 500) { capAt = Date.now(); F.w.micCaption(rms.reduce((a, b) => a + b, 0) / rms.length, peak); }
      } else if (name === 'end') end = data;
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, i); buf = buf.slice(i + 2);
          const name = /^event: (.*)$/m.exec(frame)?.[1], data = /^data: (.*)$/m.exec(frame)?.[1];
          if (name && data) { try { onEvent(name, JSON.parse(data)); } catch {} }
        }
      }
    } catch {
      // Aborted by the Stop button, or the connection dropped.
    }
    micAbort = null;
    if (ctl.signal.aborted) F.w.micUi(false, 'Test stopped.');
    else if (end?.reason === 'dictation') F.w.micUi(false, 'Stopped: a dictation started.');
    else if (end?.reason === 'error') F.w.micUi(false, `Couldn’t test the microphone: ${end.error || 'unknown error'}.`);
    else if (end?.reason === 'done') { F.w.micUi(false, rms.length ? false : 'No audio came from the microphone.'); say('Microphone test finished'); }
    else F.w.micUi(false, 'The test ended early.');
  };

  // ---------- restart
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const restartDaemon = async () => {
    const b = $('#restartNow'), label = b.innerHTML;
    b.disabled = true; F.w.spin(b, 'Restarting…');
    const done = (msg, kind) => { restarting = false; b.disabled = false; b.innerHTML = label; if (msg) toast(msg, { kind }); poll(); };
    let r;
    try { r = await req('POST', '/api/restart', { target: 'daemon' }); } catch { return done('Couldn’t reach flowd to restart it.', 'error'); }
    if (r.status === 409) return done(`flowd is busy: ${errText(r)}`, 'info');
    if (r.status !== 200) return done(`Couldn’t restart flowd: ${errText(r)}`, 'error');
    restarting = true; F.w.setDaemon('restarting');
    await sleep(600); // the daemon goes down 0.3 s after replying
    for (const t0 = Date.now(); Date.now() - t0 < 20000; await sleep(500)) {
      try {
        const s = await req('GET', '/api/status');
        if (s.status === 200) {
          applyStatus(s.data);
          await loadConfig();
          loadBackends();
          return done('flowd restarted. All changes are active.', 'success');
        }
        if (s.status === 403) { setRo('session'); return done(null); }
      } catch {}
    }
    F.w.setDaemon(false);
    done('flowd didn’t come back. Check <span class="mono">journalctl --user -u flowd</span>.', 'error');
  };
  const resetPosition = async () => {
    let r;
    try { r = await req('POST', '/api/restart', { target: 'ui', reset_position: true }); } catch { toast('Couldn’t reach flowd.', { kind: 'error' }); return; }
    if (r.status === 200) toast('Indicator moved back to the centre.', { kind: 'success' });
    else toast(r.status === 409 ? `Busy: ${errText(r)}` : `Couldn’t reset the indicator: ${errText(r)}`, { kind: r.status === 409 ? 'info' : 'error' });
  };

  // ---------- detect app
  const detectApp = () => {
    const b = $('#detectApp');
    let id, failed = null, ticks = false;
    const finish = () => {
      if (!ticks || id === undefined) return;
      if (failed) toast(`Couldn’t detect the app: ${failed}`, { kind: 'error' });
      else if (id) { F.w.apps.add(id); say(`Detected ${id}. Choose a mode and press Add.`); }
      else toast('This desktop can’t tell which app is focused. Type the app id instead.', { kind: 'info', ttl: 6000 });
    };
    req('POST', '/api/detect-app').then((r) => { if (r.status === 200) id = r.data.app_id ?? null; else { id = null; failed = errText(r); } finish(); })
      .catch(() => { id = null; failed = 'flowd is unreachable'; finish(); });
    F.w.countdown(b, 3, () => { ticks = true; finish(); });
  };

  // ---------- wiring, once the page's widgets exist
  const wire = () => {
    $('#restartNow').addEventListener('click', restartDaemon);
    $('#resetPos').addEventListener('click', resetPosition);
    $('#micTest').addEventListener('click', micTest);
    $('#detectApp').addEventListener('click', detectApp);
    $('#checkNow').addEventListener('click', async () => {
      const b = $('#checkNow'); F.w.spin(b, 'Checking');
      try { const r = await req('GET', '/api/status'); if (r.status === 200) { applyStatus(r.data); say(F.state.cleanup ? 'Cleanup model is online' : 'Cleanup model is offline'); } } catch {}
      b.textContent = 'Check now';
    });
    $('#tryIn').addEventListener('input', tryIt);
    $('#repTable').addEventListener('click', tryIt);
    $$('[data-reset]').forEach((b) => b.addEventListener('click', () => reset(b, groupKeys(b), b.closest('.group')?.querySelector('h3')?.textContent || 'Settings')));
    $('#rdOk').addEventListener('click', () => { $('#resetDlg').close(); reset($('#resetAll'), null, 'All settings'); });
    // "Save recordings" is on exactly when logging.recordings_dir is set.
    const rec = $('#recSwitch');
    F.onFill('logging.recordings_dir', (v) => {
      const on = !!v;
      if ((rec.getAttribute('aria-checked') === 'true') !== on) { rec.setAttribute('aria-checked', String(on)); rec.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: on })); }
    });
    rec.addEventListener('click', () => {
      if (rec.disabled) return;
      if (rec.getAttribute('aria-checked') === 'true') { $('#recDir').focus(); return; }
      if (!cfg?.values.logging.recordings_dir) return; // nothing saved yet
      save(rec, 'logging.recordings_dir', null, { revert: () => F.fill(cfg.values, 'logging.recordings_dir') });
    });
  };

  const start = async () => {
    if (started) return; started = true;
    wire();
    if (!token) { setRo('token'); return; }
    try {
      if (!(await loadConfig())) return;
    } catch (e) {
      if (!(e instanceof NetworkError)) throw e;
      setRo('daemon'); F.w.setDaemon(false); poll(); return;
    }
    poll();
    loadStats().catch(() => {});
    loadDevices().catch(() => {});
    loadBackends().catch(() => {});
  };

  F.api = { save, start, req };
})();
