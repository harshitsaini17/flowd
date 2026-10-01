/* flowd settings page: page wiring. Loads settings-core.js and settings-widgets.js first, then
   settings-api.js when the page is served by flowd (<html data-api>). Without it (the design
   mockup in docs/design) the page runs on demo data and simulated saves. Widget handles and
   renderers are exposed on F.w for settings-api.js. */
(() => {
  const boot = () => {
    const { $, $$, I, esc, say, toast, save, rm } = window.F;
    const demo = !F.api;
    const w = (F.w = {});
    renderIcons();

    // ---------- theme: System → Light → Dark, shared with the Appearance segmented control
    const root = document.documentElement;
    const themes = ['system', 'light', 'dark'];
    const setTheme = (v, fromBtn) => {
      root.dataset.theme = v;
      $('#themeBtn').setAttribute('aria-label', `Theme: ${v[0].toUpperCase() + v.slice(1)}. Change theme`);
      if (fromBtn) { themeSeg.pick(v); save($('#themeSeg'), 'ui.theme', v); }
      try { localStorage.setItem('flowd-theme', v); } catch {}
    };
    const themeSeg = F.initSegmented($('#themeSeg'), (v) => setTheme(v, false));
    $('#themeBtn').addEventListener('click', () => setTheme(themes[(themes.indexOf(root.dataset.theme) + 1) % 3], true));
    try { const t = localStorage.getItem('flowd-theme'); if (t) { root.dataset.theme = t; themeSeg.pick(t); } } catch {}
    // A shared theme resolver so "system" still gets explicit dark overrides in CSS that key on [data-theme="dark"].
    const mq = matchMedia('(prefers-color-scheme: dark)');
    const resolve = () => root.toggleAttribute('data-dark', root.dataset.theme === 'dark' || (root.dataset.theme === 'system' && mq.matches));
    new MutationObserver(resolve).observe(root, { attributes: true, attributeFilter: ['data-theme'] }); mq.addEventListener('change', resolve); resolve();

    // ---------- unit slot width follows the unit text (ms, s, words, sent.)
    const sizeUnits = (r = document) => $$('.num', r).forEach((n) => n.style.setProperty('--u', Math.max(1, n.querySelector('.unit')?.textContent.length || 0)));

    // ---------- generic controls
    $$('.switch').forEach(F.initSwitch);
    $$('input.input[data-key], input.input[data-min]').forEach((i) => { if (!i.closest('[data-slider]') && !i.closest('.tags') && !i.readOnly) F.initInput(i); });
    $$('select.input[data-key]').forEach((s) => F.initSelect(s, s.id === 'logLevel' ? (v) => ($('#dbgWarn').hidden = v !== 'debug') : null));
    $$('.segmented[data-key]').forEach((s) => { if (s.id !== 'themeSeg') F.initSegmented(s, s.dataset.key === 'hotkey.mode' ? onMode : null); });

    // ---------- navigation: active section, mobile sheet
    const links = $$('.nav a');
    // Scroll-spy: the active section is the last one whose top has passed 40% of the viewport.
    const secs = $$('section.sec');
    let spyRaf;
    const spy = () => {
      const line = Math.min(innerHeight * 0.4, 240);
      let cur = secs[0];
      for (const s of secs) if (s.getBoundingClientRect().top <= line) cur = s;
      if (innerHeight + scrollY >= document.documentElement.scrollHeight - 2) cur = secs.at(-1);
      links.forEach((a) => (a.getAttribute('href') === `#${cur.id}` ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    };
    addEventListener('scroll', () => { cancelAnimationFrame(spyRaf); spyRaf = requestAnimationFrame(spy); }, { passive: true });
    addEventListener('resize', spy); spy();
    const nav = $('#nav'), menu = $('#menuBtn'), scrim = $('#scrim');
    const sheet = (open) => { nav.classList.toggle('open', open); menu.setAttribute('aria-expanded', String(open)); scrim.hidden = !open; if (open) nav.querySelector('a[aria-current]')?.focus() || nav.querySelector('a').focus(); };
    menu.addEventListener('click', () => sheet(!nav.classList.contains('open')));
    scrim.addEventListener('click', () => { sheet(false); menu.focus(); });
    nav.addEventListener('keydown', (e) => {
      const ls = links, i = ls.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); ls[(i + (e.key === 'ArrowDown' ? 1 : ls.length - 1)) % ls.length].focus(); }
      if (e.key === 'Escape' && nav.classList.contains('open')) { sheet(false); menu.focus(); }
      if (e.key === 'Tab' && nav.classList.contains('open')) { // focus trap in the sheet
        if (!e.shiftKey && i === ls.length - 1) { e.preventDefault(); ls[0].focus(); }
        if (e.shiftKey && i === 0) { e.preventDefault(); ls.at(-1).focus(); }
      }
    });
    links.forEach((a) => a.addEventListener('click', (e) => {
      const target = document.querySelector(a.getAttribute('href')); if (!target) return;
      e.preventDefault(); history.replaceState(null, '', a.getAttribute('href'));
      target.scrollIntoView({ behavior: rm() ? 'auto' : 'smooth', block: 'start' });
      target.querySelector('h2')?.focus({ preventScroll: true });
      if (nav.classList.contains('open')) sheet(false);
    }));
    // The status strip collapses into one badge on narrow screens; this spells it out.
    w.statusLine = () => `flowd ${F.state.daemon ? 'running' : 'stopped'} · Cleanup ${F.state.cleanup ? 'ready' : 'offline'}`;
    $('#compactStatus').addEventListener('click', () => toast(w.statusLine(), { kind: 'info', ttl: 6000 }));
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !e.target.closest('input, textarea, select, [contenteditable]')) {
        const f = $('#appFilter'), r = f.getBoundingClientRect();
        if (r.top < innerHeight && r.bottom > 0) { e.preventDefault(); f.focus(); }
      }
    });

    // ---------- restart banner (settings-api.js replaces the Restart flowd handler)
    $('#restartLater').addEventListener('click', () => { $('#restartBanner').hidden = true; });
    w.spin = (b, label) => { b.innerHTML = `${I('loader-circle', 14)}${label}`; b.querySelector('svg').style.animation = 'spin 800ms linear infinite'; };
    if (demo) $('#restartNow').addEventListener('click', () => {
      const b = $('#restartNow'); b.disabled = true; w.spin(b, 'Restarting…');
      setDaemon('restarting');
      setTimeout(() => { F.state.restartKeys.clear(); F.updateRestart(); b.disabled = false; b.innerHTML = `${I('rotate-ccw', 14)}Restart flowd`; setDaemon(true); toast('flowd restarted. All changes are active.', { kind: 'success' }); }, 1600);
    });

    // ---------- header status
    const badge = (w.badge = (cls, ic, txt) => `<span class="badge ${cls}">${I(ic, 12)}${txt}</span>`);
    // s: true (running), false (stopped), 'restarting'
    const setDaemon = (w.setDaemon = (s) => {
      F.state.daemon = s === true;
      $('#st-daemon').innerHTML = s === true ? badge('ok', 'circle-check', 'Running') : s === 'restarting' ? badge('neutral', 'loader-circle', 'Restarting…') : badge('danger', 'circle-alert', 'Stopped');
      if (demo && s === false) {
        $('#st-daemon').insertAdjacentHTML('beforeend', ' <button class="link-btn" id="startD">Start</button>');
        $('#startD').addEventListener('click', () => { setDaemon('restarting'); setTimeout(() => setDaemon(true), 1200); });
      }
      compact();
    });
    // st: 'ready' | 'offline' | 'disabled' (true/false accepted for the mockup)
    const setCleanup = (w.setCleanup = (st) => {
      if (st === true) st = 'ready'; if (st === false) st = 'offline';
      const on = st === 'ready';
      F.state.cleanup = on; F.state.cleanupState = st;
      $('#st-cleanup').innerHTML = 'Cleanup ' + (on ? badge('ok', 'circle-check', 'Ready') : st === 'disabled' ? badge('neutral', 'circle-dashed', 'Off') : badge('warn', 'triangle-alert', 'Offline, pasting as heard'));
      $('#cleanBadge').outerHTML = on ? `<span class="badge ok" id="cleanBadge">${I('circle-check', 12)}Ready</span>` : st === 'disabled' ? `<span class="badge neutral" id="cleanBadge">${I('circle-dashed', 12)}Disabled</span>` : `<span class="badge warn" id="cleanBadge">${I('triangle-alert', 12)}Offline</span>`;
      const help = $('#offlineHelp'), offline = st === 'offline'; help.hidden = !offline;
      help.innerHTML = !offline ? '' : `<div class="field-warn">${I('triangle-alert', 14)}<span>Not responding. Start it with <span class="mono">systemctl --user start flowd-llm</span></span></div><button class="copy u-mt4">${I('copy', 14)}<span>Copy command</span></button>`;
      if (offline) F.initCopy(help.querySelector('.copy'), () => 'systemctl --user start flowd-llm', 'Copy start command');
      const nl = $('#nav-cleanup');
      nl.querySelector('.attn')?.remove(); nl.querySelector('.sr-only')?.remove();
      if (offline) nl.insertAdjacentHTML('beforeend', '<span class="attn" aria-hidden="true"></span><span class="sr-only">(needs attention)</span>');
      const sim = $('#simCleanup'); if (sim) sim.textContent = on ? 'Take cleanup offline' : 'Bring cleanup online';
      F.renderOverview?.();
      compact();
    });
    const compact = () => {
      const c = $('#compactStatus');
      const [cls, ic, txt] = !F.state.daemon ? ['danger', 'circle-alert', 'flowd stopped'] : F.state.cleanupState === 'offline' ? ['warn', 'triangle-alert', 'Cleanup offline'] : ['ok', 'circle-check', 'All ok'];
      c.className = `badge ${cls} hdr-compact`; c.innerHTML = `${I(ic, 12)}<span>${txt}</span>`; c.setAttribute('aria-label', `Status: ${txt}. Show details`);
    };
    if (demo) {
      let hc = 12; setInterval(() => { hc = (hc + 1) % 30; $('#hcAgo').textContent = `${hc} s`; }, 1000);
      $('#checkNow').addEventListener('click', () => {
        const b = $('#checkNow'); w.spin(b, 'Checking');
        setTimeout(() => { b.textContent = 'Check now'; hc = 0; $('#hcAgo').textContent = '0 s'; say(F.state.cleanup ? 'Cleanup model is online' : 'Cleanup model is still offline'); }, 700);
      });
    }

    // ---------- overview: user-facing value first, performance details on demand
    // Sessions: { ts (ms), app, name, mode, words, speak (s), ms (paste latency), fb, via }.
    // settings-api.js converts /api/stats sessions to this shape and calls w.setSessions.
    const DAY = 86400000;
    let all = [];
    if (demo) {
      let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      const APPS = [['code', 'VS Code', 'code', 0.34], ['kitty', 'Terminal (kitty)', 'code', 0.22], ['slack', 'Slack', 'chat', 0.18], ['thunderbird', 'Thunderbird', 'email', 0.11], ['org.mozilla.firefox', 'Firefox', 'default', 0.09], ['obsidian', 'Obsidian', 'default', 0.06]];
      const pickApp = () => { let r = rnd(), a = 0; for (const x of APPS) { a += x[3]; if (r <= a) return x; } return APPS[0]; };
      const now = Date.now();
      for (let d = 89; d >= 0; d--) {
        const weekday = new Date(now - d * DAY).getDay() % 6 !== 0;
        const n = Math.round((weekday ? 9 : 3) * (0.5 + rnd()) * (1 + (89 - d) / 120)); // usage grows over time
        for (let k = 0; k < n; k++) {
          const [app, name, mode] = pickApp();
          const speak = 4 + rnd() * (mode === 'email' ? 70 : mode === 'chat' ? 20 : 35); // seconds of speech
          const words = Math.max(3, Math.round((speak / 60) * (120 + rnd() * 50)));
          const fb = rnd() < 0.04;
          const ms = Math.round(fb ? 780 + rnd() * 260 : 380 + rnd() * 320 + (rnd() > 0.92 ? 300 : 0));
          all.push({ ts: now - d * DAY - Math.round(rnd() * 9 * 3600000), app, name, mode, words, speak, ms, fb, via: rnd() < 0.1 ? 'wtype' : 'clipboard' });
        }
      }
      all.sort((a, b) => a.ts - b.ts);
    }
    // Memory line for the health list and the perf card; settings-api.js fills it from /api/status.
    w.memory = demo ? { mb: 1229, budget: 1600 } : null;
    const fmtMem = (mb) => (mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`);
    w.fmtMem = fmtMem;
    let wpm = 40;
    try { wpm = +localStorage.getItem('flowd-wpm') || 40; } catch {}
    const fmtDur = (min) => min >= 60 ? `${Math.floor(min / 60)} h ${Math.floor(min % 60)} min` : min <= 0 ? '0 min' : `${Math.max(1, Math.floor(min))} min`;
    const fmtN = (n) => n.toLocaleString('en-US');
    const ago = (ts) => { const m = Math.round((Date.now() - ts) / 60000); if (m < 1) return 'Just now'; if (m < 60) return `${m} min ago`; const h = Math.round(m / 60); if (h < 24) return `${h} h ago`; const d = Math.round(h / 24); return d === 1 ? 'Yesterday' : `${d} days ago`; };
    // Saved = time to type those words at your speed, minus time spent speaking and waiting for the paste.
    const savedOne = (s) => Math.max(0, s.words / wpm - (s.speak + s.ms / 1000) / 60);
    const savedMin = (list) => list.reduce((a, s) => a + savedOne(s), 0);
    const mIcon = { code: 'code', chat: 'message-square', email: 'mail', default: 'file-text' };
    const mName = { code: 'Code', chat: 'Chat', email: 'Email', default: 'Writing' };
    let period = '30';
    const renderOverview = () => {
      const now = Date.now();
      const days = period === 'all' ? Math.max(7, Math.ceil((now - (all[0]?.ts ?? now)) / DAY)) : +period;
      const cur = period === 'all' ? all : all.filter((s) => s.ts > now - days * DAY);
      const prev = period === 'all' ? [] : all.filter((s) => s.ts <= now - days * DAY && s.ts > now - 2 * days * DAY);
      const saved = savedMin(cur), prevSaved = savedMin(prev);
      const words = cur.reduce((a, s) => a + s.words, 0), speakMin = cur.reduce((a, s) => a + s.speak, 0) / 60;
      const label = { 7: 'in the last 7 days', 30: 'in the last 30 days', all: 'since you started' }[period];
      $('#savedV').textContent = cur.length ? fmtDur(saved) : '—';
      const delta = prev.length ? Math.round(((saved - prevSaved) / Math.max(1, prevSaved)) * 100) : null;
      $('#savedS').innerHTML = !cur.length ? `No dictations ${label}. Press your hotkey to start one.` : `${label}` + (delta != null ? `<br><span class="${delta >= 0 ? 'up' : ''}">${delta >= 0 ? '↑' : '↓'} ${Math.abs(delta)}% vs the ${days} days before</span>` : '') +
        `<span class="words">That’s ${fmtN(words)} words you didn’t have to type.</span>`;
      const longest = cur.reduce((a, s) => (s.words > (a?.words || 0) ? s : a), null);
      $('#cWords').innerHTML = longest ? `${fmtN(longest.words)}<small>words</small>` : '—';
      $('#cWordsS').textContent = longest ? `in ${longest.name}, ${ago(longest.ts).toLowerCase()} · ${fmtDur(savedOne(longest))} saved` : '';
      const speakWpm = Math.round(words / Math.max(0.1, speakMin));
      $('#cWpm').innerHTML = cur.length ? `${speakWpm}<small>words a minute</small>` : '—';
      $('#cWpmS').textContent = cur.length ? `${(speakWpm / wpm).toFixed(1)}× your typing speed` : '';
      $('#cSess').textContent = fmtN(cur.length);
      const activeDays = new Set(cur.map((s) => new Date(s.ts).toDateString())).size;
      $('#cSessS').textContent = cur.length ? `about ${Math.round(cur.length / Math.max(1, activeDays))} a day, on ${activeDays} of ${days} days` : '';
      // bar chart: minutes saved per day (week/month) or per week (all)
      const buckets = period === 'all' ? Math.min(52, Math.max(2, Math.ceil(days / 7))) : days, span = period === 'all' ? 7 * DAY : DAY;
      const bars = Array.from({ length: buckets }, (_, i) => {
        const hi = now - (buckets - 1 - i) * span, lo = hi - span;
        const inB = cur.filter((s) => s.ts > lo && s.ts <= hi);
        return { m: savedMin(inB), d: new Date(hi) };
      });
      const max = Math.max(1, ...bars.map((b) => b.m));
      const peak = bars.reduce((a, b) => (b.m > a.m ? b : a), bars[0]);
      $('#scTitle').textContent = `Minutes saved per ${period === 'all' ? 'week' : 'day'}`;
      const dl = (d) => period === '7' ? d.toLocaleDateString('en-US', { weekday: 'short' }) : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      $('#scPeak').innerHTML = `<span class="sbar-key"><i class="k-peak"></i>Best: ${Math.round(peak.m)} min on ${dl(peak.d)}</span><span class="sbar-key u-ml16"><i class="k-today"></i>Today, so far</span>`;
      $('#savedChart').innerHTML = `<div aria-labelledby="scTitle" class="sbars${buckets > 14 ? ' dense' : ''}" role="list">${bars.map((b, i) => `<div class="sbar${b === peak && b.m > 0 ? ' peak' : ''}" role="listitem" tabindex="${i === bars.length - 1 ? 0 : -1}" aria-label="${dl(b.d)}: ${Math.round(b.m)} minutes saved" data-tip="${dl(b.d)} · ${Math.round(b.m)} min"><span></span></div>`).join('')}</div><div class="sbar-axis" aria-hidden="true"><span>${dl(bars[0].d)}</span><span>${period === 'all' ? 'This week' : 'Today'}</span></div>`;
      // Bar heights are runtime values: set through CSSOM, which the page's CSP allows (inline style attributes it blocks).
      $$('#savedChart .sbar > span').forEach((sp, i) => (sp.style.height = `${Math.max(2, (bars[i].m / max) * 100)}%`));
      // apps
      const byApp = {};
      cur.forEach((s) => { (byApp[s.app] ||= { name: s.name, mode: s.mode, words: 0, n: 0 }); byApp[s.app].words += s.words; byApp[s.app].n++; });
      const rows = Object.values(byApp).sort((a, b) => b.words - a.words).slice(0, 8);
      const topW = Math.max(1, rows[0]?.words || 1);
      $('#appsBars').innerHTML = rows.length ? rows.map((r) => `<li><span class="an">${esc(r.name)}<span class="am">${I(mIcon[r.mode] || 'file-text', 12)}${mName[r.mode] || esc(r.mode)}</span></span><span class="ab" aria-hidden="true"><span></span></span><span class="aw tnum">${fmtN(r.words)} words</span></li>`).join('') : '<li><span class="an">No dictations yet.</span></li>';
      $$('#appsBars .ab > span').forEach((sp, i) => (sp.style.width = `${(rows[i].words / topW) * 100}%`));
      // health, in plain words
      const last50 = all.slice(-50), sorted = last50.map((s) => s.ms).sort((a, b) => a - b);
      const med = sorted.length ? sorted[Math.ceil(sorted.length / 2) - 1] : null;
      const fbN = cur.filter((s) => s.fb).length, fbPct = (fbN / Math.max(1, cur.length)) * 100;
      const cst = F.state.cleanupState || (F.state.cleanup ? 'ready' : 'offline');
      const mem = w.memory;
      const H = [
        med == null ? ['timer', 'ok', 'Text appears', 'No dictations yet', 'Waiting'] : ['timer', med < 700 ? 'ok' : 'warn', 'Text appears', `${(med / 1000).toFixed(1)} s after you stop talking`, med < 700 ? 'Feels instant' : 'A bit slow'],
        cst === 'disabled' ? ['sparkles', 'ok', 'Cleanup is off', 'Text is typed as you said it, with basic punctuation', 'Off']
          : ['sparkles', cst !== 'ready' ? 'warn' : fbPct <= 10 ? 'ok' : 'warn', `Tidied up ${cst === 'ready' ? Math.round(100 - fbPct) + '%' : 'none'} of dictations`, cst !== 'ready' ? 'Cleanup is offline, so text is typed as you said it' : 'The rest were typed exactly as you said them', cst !== 'ready' ? 'Offline' : fbPct <= 10 ? 'Working well' : 'Often skipped'],
        mem ? ['memory-stick', mem.mb <= mem.budget ? 'ok' : 'warn', 'Memory in use', `${fmtMem(mem.mb)} of your RAM`, mem.mb <= mem.budget ? 'Normal' : 'Above budget'] : ['memory-stick', 'ok', 'Memory in use', 'Checking…', '—'],
        ['lock', 'ok', 'Stayed on this machine', 'No audio or text was sent anywhere', 'Private'],
      ];
      $('#health').innerHTML = H.map(([ic, st, t, d, b]) => `<li><span class="hi ${st}">${I(st === 'ok' ? ic : 'triangle-alert', 16)}</span><span class="ht"><b>${t}</b><span>${d}</span></span><span class="badge ${st}">${I(st === 'ok' ? 'circle-check' : 'triangle-alert', 12)}${b}</span></li>`).join('');
      // recent dictations: time, app, words, saved; no text
      $('#recent').innerHTML = all.length ? all.slice(-6).reverse().map((s) => { const sv = savedOne(s) * 60; return `<li><span class="rt">${ago(s.ts)}</span><span class="ra"><b>${esc(s.name)}</b><span>${I(mIcon[s.mode] || 'file-text', 12)}${mName[s.mode] || esc(s.mode)}</span></span><span class="rw tnum">${s.words} words</span><span class="rs tnum">${s.fb ? `<span class="badge warn" title="Typed exactly as you said it, without cleanup">${I('triangle-alert', 12)}Not tidied</span>` : ''}${sv >= 1 ? `saved ${sv >= 120 ? Math.round(sv / 60) + ' min' : sv >= 60 ? '1 min ' + Math.round(sv - 60) + ' s' : Math.round(sv) + ' s'}` : '—'}</span></li>`; }).join('')
        : `<li><span class="ra"><b>No dictations yet.</b><span>Press your hotkey or click the indicator to try it.</span></span></li>`;
    };
    F.initSegmented($('#periodSeg'), (v) => { period = v; renderOverview(); });
    // editable typing speed: the one assumption behind "time saved"
    const pop = $('#wpmPop'), wb = $('#wpmBtn');
    const closePop = (focus = true) => { pop.hidden = true; wb.setAttribute('aria-expanded', 'false'); if (focus) wb.focus(); };
    wb.addEventListener('click', () => { const open = pop.hidden; pop.hidden = !open; wb.setAttribute('aria-expanded', String(open)); if (open) { $('#wpmIn').value = wpm; $('#wpmIn').select(); } });
    const applyWpm = () => {
      const msg = F.validate($('#wpmIn'));
      if (msg) { F.showErr($('#wpmIn'), msg); return; }
      F.showErr($('#wpmIn'), null);
      wpm = +$('#wpmIn').value; $('#wpmV').textContent = wpm; try { localStorage.setItem('flowd-wpm', wpm); } catch {}
      renderOverview(); closePop(); say(`Typing speed set to ${wpm} words per minute. Time saved updated.`);
    };
    $('#wpmOk').addEventListener('click', applyWpm);
    $('#wpmIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyWpm(); } if (e.key === 'Escape') closePop(); });
    document.addEventListener('pointerdown', (e) => { if (!pop.hidden && !pop.contains(e.target) && !wb.contains(e.target)) closePop(false); });
    $('#wpmV').textContent = wpm;
    // tooltips + roving focus on the saved-time bars
    $('#savedChart').addEventListener('keydown', (e) => {
      const bs = $$('.sbar', $('#savedChart')), i = bs.indexOf(document.activeElement);
      const n = e.key === 'ArrowLeft' ? i - 1 : e.key === 'ArrowRight' ? i + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? bs.length - 1 : null;
      if (n == null || !bs[n]) return; e.preventDefault(); bs[i].tabIndex = -1; bs[n].tabIndex = 0; bs[n].focus();
    });
    F.renderOverview = renderOverview;

    // performance details (collapsed): the engineering view, still available
    let sessions = [], perf = { p50: null, p95: null, fbRate: null };
    let perfDrawn = false;
    const perfBtn = $('#perfBtn'), perfBody = $('#perfBody');
    const fmtMs = (v) => (v == null ? '—' : `${Math.round(v)} ms`);
    const drawPerf = () => {
      if (perfDrawn) return; perfDrawn = true;
      $('#chartTable').innerHTML = '';
      if (!sessions.length) { $('#chartWrap').innerHTML = `<div class="empty">${I('audio-lines', 20)}<div><b>No dictations yet.</b><p>Press your hotkey or click the indicator to try it.</p></div></div>`; renderIcons($('#chartWrap')); return; }
      const st = F.initChart($('#chartWrap'), sessions);
      const p50 = perf.p50 ?? st.p50, p95 = perf.p95 ?? st.p95;
      $('#pP50').textContent = fmtMs(p50); $('#pP95').textContent = fmtMs(p95);
      const lg = $$('.legend > span');
      lg[0].lastChild.textContent = `p50 ${Math.round(p50)} ms`; lg[1].lastChild.textContent = `p95 ${Math.round(p95)} ms`;
    };
    const renderPerfCards = () => {
      $('#pP50').textContent = fmtMs(perf.p50); $('#pP95').textContent = fmtMs(perf.p95);
      // Not in the older design mockup, hence the guards.
      const fb = $('#pFb'), mem = $('#pMem');
      if (fb) fb.textContent = perf.fbRate == null ? '—' : `${(perf.fbRate * 100).toFixed(1)}%`;
      if (mem) mem.textContent = w.memory ? fmtMem(w.memory.mb) : '—';
    };
    w.renderPerfCards = renderPerfCards;
    perfBtn.addEventListener('click', () => { const open = perfBtn.getAttribute('aria-expanded') !== 'true'; perfBtn.setAttribute('aria-expanded', String(open)); perfBody.hidden = !open; if (open) drawPerf(); });
    $('#chartTableBtn').addEventListener('click', (e) => {
      const t = $('#chartTable'), open = t.hidden; t.hidden = !open; e.target.setAttribute('aria-expanded', String(open)); e.target.textContent = open ? 'Hide table' : 'Show as table';
      if (open && !t.innerHTML) t.innerHTML = `<div class="chart-table"><table class="kv"><caption class="sr-only">Release to paste latency per dictation</caption><thead><tr><th>#</th><th>Time</th><th>Latency</th><th>Mode</th><th>Fallback</th></tr></thead><tbody>${sessions.map((s) => `<tr><td class="tnum">${s.n}</td><td class="tnum">${s.t}</td><td class="tnum">${s.ms} ms</td><td>${esc(s.mode)}</td><td>${s.fb ? 'Yes' : 'No'}</td></tr>`).join('')}</tbody></table></div>`;
    });
    // list: sessions in the shape above; stats: { p50, p95, fbRate } from /api/stats (optional)
    const setSessions = (w.setSessions = (list, stats = {}) => {
      all = [...list].sort((a, b) => a.ts - b.ts);
      sessions = all.slice(-50).map((s, i) => ({ n: i + 1, ms: Math.round(s.ms), fb: s.fb, mode: String(s.mode || 'default')[0].toUpperCase() + String(s.mode || 'default').slice(1), via: s.via || '—', t: new Date(s.ts).toTimeString().slice(0, 5) }));
      const sorted = sessions.map((s) => s.ms).sort((a, b) => a - b);
      const pc = (p) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)] : null);
      perf = { p50: stats.p50 ?? pc(50), p95: stats.p95 ?? pc(95), fbRate: stats.fbRate ?? (all.length ? all.filter((s) => s.fb).length / all.length : null) };
      renderOverview(); renderPerfCards();
      perfDrawn = false; if (!perfBody.hidden) drawPerf();
    });
    setSessions(all);

    // ---------- hotkey: mode + snippets
    function onMode(v) {
      $('#d-mode').textContent = v === 'ptt' ? 'Hold to speak, release to paste.' : 'Press once to start, again to stop.';
      $('#kdePtt').hidden = !(v === 'ptt' && currentDE === 'kde');
      renderSnips();
    }
    let currentDE = 'hyprland';
    const SN = {
      hyprland: { path: '~/.config/hypr/hyprland.conf', toggle: '# Toggle\nbind = SUPER, D, exec, flowctl toggle', ptt: '# Push-to-talk: bindr fires on release\nbind  = SUPER, D, exec, flowctl start\nbindr = SUPER, D, exec, flowctl stop', extra: '# Optional: full rewrite on stop\nbind = SUPER SHIFT, D, exec, flowctl stop --rewrite' },
      sway: { path: '~/.config/sway/config', toggle: '# Toggle\nbindsym $mod+d exec flowctl toggle', ptt: '# Push-to-talk\nbindsym $mod+d exec flowctl start\nbindsym --release $mod+d exec flowctl stop' },
      kde: { path: 'System Settings → Shortcuts → Add New → Command', toggle: 'flowctl toggle', ptt: '# Plasma custom shortcuts fire on press only.\n# Use toggle instead:\nflowctl toggle', note: 'Paste the command into a new custom shortcut and assign your key.' },
      gnome: { path: 'Terminal', toggle: "path=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flowd/\ngsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings \\\n  \"['$path']\"\ngsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \\\n  name 'flowd dictation'\ngsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \\\n  command 'flowctl toggle'\ngsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$path \\\n  binding '<Super>d'", warn: 'On GNOME under Wayland the live preview is off. GNOME doesn’t support the protocol that lets it promise never to take keyboard focus, and a preview that took focus would swallow your text. Dictation works normally.' },
      x11: { path: '~/.config/sxhkd/sxhkdrc', toggle: '# Toggle\nsuper + d\n    flowctl toggle', ptt: '# Push-to-talk\nsuper + d\n    flowctl start\n@super + d\n    flowctl stop' },
    };
    const hl = (code) => esc(code).split('\n').map((l) => (l.trim().startsWith('#') ? `<span class="c">${l}</span>` : l)).join('\n');
    const renderSnips = () => {
      const s = SN[currentDE], mode = $('[data-key="hotkey.mode"] [aria-checked="true"]').dataset.v;
      const blocks = [[s.path, mode === 'ptt' && s.ptt ? s.ptt : s.toggle]];
      if (s.extra) blocks.push([s.path, s.extra]);
      $('#snippets').innerHTML = (s.warn ? `<div class="banner">${I('triangle-alert', 16)}<div class="bt">${s.warn}</div></div>` : '') +
        blocks.map(([p, c], i) => `<div class="snippet${i ? ' u-mt12' : ''}"><div class="snippet-head"><span class="path">${esc(p)}</span><button class="copy">${I('copy', 14)}<span>Copy</span></button></div><pre tabindex="0" aria-label="${currentDE} snippet">${hl(c)}</pre></div>`).join('') +
        (s.note ? `<p class="field-note">${s.note}</p>` : '');
      $$('#snippets .copy').forEach((b, i) => F.initCopy(b, () => blocks[i][1], `Copy ${currentDE} snippet`));
    };
    const deSeg = F.initSegmented($('#deTabs'), (v) => { currentDE = v; onMode($('[data-key="hotkey.mode"] [aria-checked="true"]').dataset.v); });
    // /api/status reports the desktop; "other" keeps the current tab.
    w.setDesktop = (de) => { if (SN[de]) deSeg.pick(de); };
    w.setDesktop('hyprland');
    if (demo) $('#resetPos').addEventListener('click', () => toast('Indicator moved back to the centre.', { kind: 'success' }));

    // ---------- microphone
    w.dev = F.initListbox($('#devPicker'), demo ? [
      { id: 'default', name: 'System default', node: 'PipeWire default source' },
      { id: 'yeti', name: 'Blue Yeti', node: 'alsa_input.usb-Blue_Microphones_Yeti-00.analog-stereo' },
      { id: 'internal', name: 'Built-in microphone', node: 'alsa_input.pci-0000_00_1f.3.analog-stereo' },
      { id: 'hs', name: 'WH-1000XM4 headset', node: 'bluez_input.CC_98_8B_00_00_00.0' },
    ] : [{ id: 'default', name: 'System default', node: 'PipeWire default source' }], 'default');
    // Meter and caption, shared with the real test in settings-api.js. Levels in dBFS.
    const meter = (w.meter = (db) => {
      const v = Math.max(-60, Math.min(0, db));
      $('#mtrFill').style.width = `${((v + 60) / 60) * 100}%`; $('#mtr').setAttribute('aria-valuenow', Math.round(v)); $('#mtrDb').textContent = `${v < 0 ? '−' : ''}${Math.abs(Math.round(v))} dB`;
    });
    // design.md: average RMS below −45 dB is too quiet, −35…−12 good, a peak above −6 dB too loud.
    w.micCaption = (avg, peak) => {
      $('#micCap').innerHTML = peak > -6 ? `<span class="cap-warn">${I('triangle-alert', 14)}</span>Too loud, may clip. Move back a little.`
        : avg < -45 ? `${I('info', 14)}Too quiet. Speak up or move closer.`
        : avg >= -35 && avg <= -12 ? `<span class="cap-ok">${I('check', 14)}</span>Good level`
        : `${I('info', 14)}${avg < -35 ? 'A little quiet.' : 'A little loud.'}`;
    };
    w.micUi = (on, msg) => {
      const b = $('#micTest');
      b.innerHTML = on ? `${I('square', 14)}<span>Stop test</span>` : `${I('mic', 14)}<span>Test microphone</span>`;
      if (on) { $('#micMeter').hidden = false; $('#st-privacy').innerHTML = '<span class="badge rec">Mic open</span>'; }
      else { $('#mtrFill').style.width = '0'; if (msg !== false) $('#micCap').textContent = msg ?? 'Test stopped.'; w.micOn = false; privacyBadge(); }
      if (on) w.micOn = true;
    };
    if (demo) {
      let micT;
      const micStop = () => { clearInterval(micT); micT = null; w.micUi(false); };
      $('#micTest').addEventListener('click', () => {
        if (micT) return micStop();
        w.micUi(true);
        const t0 = Date.now(); let peak = -60; const avgs = [];
        micT = setInterval(() => {
          const t = (Date.now() - t0) / 1000;
          const speaking = Math.sin(t * 2.1) > -0.3;
          const db = speaking ? -34 + 16 * Math.abs(Math.sin(t * 7.3)) * (0.6 + 0.4 * Math.random()) + (t > 6 && t < 7.5 ? 14 : 0) : -58 + Math.random() * 4;
          meter(db);
          avgs.push(db); if (avgs.length > 20) avgs.shift(); peak = Math.max(db, peak - 1.5);
          if (Math.round(t * 20) % 10 === 0) w.micCaption(avgs.reduce((a, b) => a + b, 0) / avgs.length, peak);
          if (t > 15) micStop();
        }, rm() ? 100 : 50);
      });
    }

    // ---------- recognition, appearance sliders
    w.sliders = {};
    $$('[data-slider]').forEach((h) => { if (!['linesSlider', 'fadeSlider'].includes(h.id)) w.sliders[h.dataset.key] = F.initSlider(h); });
    const pv = { lines: 4, fade: 1000, foot: true };
    F.initSlider($('#linesSlider'), (v) => { pv.lines = v; drawPreview(); });
    F.initSlider($('#fadeSlider'), (v) => (pv.fade = v));
    $('#footSwitch').addEventListener('change', (e) => { pv.foot = e.detail; drawPreview(); });

    // ---------- cleanup
    // Defaults come from /api/config's `defaults` when served; these are the mockup's copy.
    w.defaults = {
      cues: ['no wait', 'no no', 'actually', 'i mean', 'sorry', 'scratch that', 'let me rephrase'],
      terminals: ['kitty', 'Alacritty', 'foot', 'org.wezfurlong.wezterm', 'konsole', 'org.gnome.Terminal'],
      order: ['clipboard', 'wtype', 'ydotool', 'xdotool'],
    };
    w.cues = F.initTags($('[data-tags="cues"]'), demo ? w.defaults.cues : []);
    $('[data-key="llm.enabled"]').addEventListener('change', (e) => { if (demo) setTimeout(() => setCleanup(e.detail ? (F.state.cleanup ? 'ready' : 'offline') : 'disabled'), 0); });

    // ---------- vocabulary
    w.terms = F.initTags($('[data-tags="terms"]'), demo ? ['Hyprland', 'PipeWire', 'flowd', 'LLM', 'Wayland'] : []);
    w.rep = F.initKV($('#repTable'), { rows: demo ? [{ k: 'hyper land', v: 'Hyprland' }, { k: 'pipe wire', v: 'PipeWire' }, { k: 'flow d', v: 'flowd' }] : [], keyLabel: 'When you say', valLabel: 'Write', key: 'vocab.replace', empty: { icon: 'book-a', title: 'No replacement rules.', text: 'Fix a mishearing that keeps coming back: spoken → written.' }, dupMsg: (k) => `“${esc(k)}” already has a rule.` });
    if (demo) {
      const tryIt = () => {
        let s = $('#tryIn').value;
        $$('#repTable tbody tr[data-i]').forEach((tr) => { const tds = tr.querySelectorAll('td.k'); if (tds.length < 2) return; const k = tds[0].textContent.trim(), v = tds[1].textContent.trim(); s = s.replace(new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), v); });
        s = s.trim(); s = s.charAt(0).toUpperCase() + s.slice(1); if (s && !/[.!?]$/.test(s)) s += '.';
        $('#tryOut').textContent = s;
      };
      $('#tryIn').addEventListener('input', tryIt); $('#repTable').addEventListener('click', () => setTimeout(tryIt, 0)); tryIt();
    }

    // ---------- apps & modes
    const BUILTIN = [['code', 'code'], ['code-oss', 'code'], ['codium', 'code'], ['dev.zed.zed', 'code'], ['jetbrains-idea', 'code'], ['jetbrains-pycharm', 'code'], ['neovide', 'code'], ['org.telegram.desktop', 'chat'], ['slack', 'chat'], ['discord', 'chat'], ['vesktop', 'chat'], ['signal', 'chat'], ['element', 'chat'], ['whatsapp-for-linux', 'chat'], ['thunderbird', 'email'], ['org.gnome.evolution', 'email'], ['geary', 'email']];
    // builtins: [[app, mode]], from /api/config's defaults.modes when served.
    w.makeApps = (builtins, extra = []) => F.initKV($('#appTable'), { rows: [...builtins.map(([k, v]) => ({ k, v, orig: v })), ...extra], keyLabel: 'App id', valLabel: 'Mode', type: 'mode', builtins: new Set(builtins.map((b) => b[0])), key: 'modes', filter: $('#appFilter'), empty: { icon: 'app-window', title: 'Using built-in modes only.', text: `${builtins.length} apps are mapped by default. Add one to override.` }, dupMsg: (k, v) => `${esc(k)} is already mapped${v ? ` to ${v}` : ''}.` });
    // Served, the table is built once /api/config has sent the built-in modes (settings-api.js).
    w.apps = demo ? w.makeApps(BUILTIN, [{ k: 'obsidian', v: 'default' }]) : null;
    // The countdown before the focused window is read (the daemon waits 3 s too).
    w.countdown = (b, n, done) => {
      const tick = () => { if (n === 0) { b.innerHTML = `${I('app-window', 14)}<span>Detect focused app</span>`; b.disabled = false; done?.(); return; } b.innerHTML = `<span class="tnum">Switch to the app… ${n}</span>`; say(`${n}`); n--; setTimeout(tick, 1000); };
      b.disabled = true; tick();
    };
    if (demo) $('#detectApp').addEventListener('click', () => w.countdown($('#detectApp'), 3, () => { w.apps.add('org.mozilla.firefox'); say('Detected org.mozilla.firefox. Choose a mode and press Add.'); }));
    w.termTags = F.initTags($('[data-tags="terminals"]'), demo ? w.defaults.terminals : []);

    // ---------- typing
    const CAPS = { clipboard: 'wl-copy, then Ctrl+V. Restores your clipboard after.', wtype: 'Types the text as key events (wlroots compositors).', ydotool: 'Kernel-level typing through /dev/uinput.', xdotool: 'X11 and XWayland only.' };
    const ORDER = [
      { name: 'clipboard', cap: CAPS.clipboard, status: demo ? 'available' : undefined },
      { name: 'wtype', cap: CAPS.wtype, status: demo ? 'available' : undefined },
      { name: 'ydotool', cap: CAPS.ydotool, status: demo ? 'stopped' : undefined },
      { name: 'xdotool', cap: CAPS.xdotool, status: demo ? 'missing' : undefined },
    ];
    w.order = F.initReorder($('#order'), ORDER);
    $$('#ydoBanner .copy').forEach((b) => F.initCopy(b, () => b.dataset.copy, 'Copy ydotoold start command'));
    if (demo) $('#ydoBanner').hidden = false;

    // ---------- appearance preview (reuses the overlay CSS)
    F.initSegmented($('#wallSeg'), (v) => ($('#pvStage').dataset.wall = v));
    const pvPop = $('#pvPopup'), pvPill = $('#pvPill');
    const pvText = ['I was thinking we should move the meeting to Thursday.', 'Can you send the invite to the platform list,', 'and attach the notes from last week?', 'Thanks.'];
    const drawPreview = (phase = 'stream') => {
      const lines = pvText.slice(0, Math.max(pvText.length, pv.lines));
      const body = phase === 'listen' ? '<span class="z-listening">Listening…</span>' : `<span class="z-polished">${lines.slice(0, 2).join(' ')} </span><span class="z-pending">and attach the notes </span><span class="z-live">from last<span class="caret"></span></span>`;
      const foot = !pv.foot && phase !== 'done' ? '' : phase === 'done' ? `<div class="foot"><span class="ok">${I('check', 14)}</span><span class="msg">Pasted into kitty</span></div>` : `<div class="foot"><span class="chip">${I('code', 12)}Code</span><span>kitty</span><span class="end">0:04</span></div>`;
      pvPop.innerHTML = `<div class="body${pv.lines < 3 && phase !== 'listen' ? ' scrolled' : ''}"><div class="scroller"><div>${phase === 'done' ? `<span class="z-polished">${pvText.slice(0, 3).join(' ')}</span>` : body}</div></div></div>${foot}`;
      pvPop.querySelector('.body').style.setProperty('--lines', pv.lines);
      pvPop.hidden = false;
    };
    const setPv = (st) => {
      pvPill.dataset.state = st;
      pvPill.innerHTML = st === 'recording' ? `<span class="btn-disc"><span class="stop"></span></span><span class="meter">${'<b></b>'.repeat(5)}</span>` : st === 'hover' ? `<span class="btn-disc">${I('mic')}</span><span class="lbl">Dictate</span>` : st === 'finishing' ? `<span class="btn-disc">${I('loader-circle')}</span><span class="dots"><b></b><b></b><b></b></span>` : '';
    };
    setPv('recording'); drawPreview();
    setInterval(() => $$('.meter b', pvPill).forEach((b, i) => (b.style.height = `${4 + 16 * Math.abs(Math.sin(Date.now() / 250 + i))}px`)), 50);
    $('#pvPlay').addEventListener('click', () => {
      const steps = [[0, () => { pvPop.hidden = true; setPv('idle'); $('#pvState').textContent = 'Idle'; }], [400, () => { setPv('hover'); $('#pvState').textContent = 'Hover'; }], [800, () => { setPv('recording'); drawPreview('listen'); $('#pvState').textContent = 'Recording'; }], [1500, () => { drawPreview('stream'); $('#pvState').textContent = 'Streaming'; }], [2600, () => { setPv('finishing'); $('#pvState').textContent = 'Finishing'; }], [3000, () => { setPv('idle'); drawPreview('done'); $('#pvState').textContent = `Pasted, fading after ${pv.fade} ms`; }]];
      steps.forEach(([t, fn]) => setTimeout(fn, t));
      setTimeout(() => { pvPop.style.transition = 'opacity var(--dur-fade-out) var(--ease-exit)'; pvPop.style.opacity = '0'; setTimeout(() => { pvPop.hidden = true; pvPop.style.transition = pvPop.style.opacity = ''; $('#pvState').textContent = 'Idle'; }, 260); }, 3000 + pv.fade);
    });

    // ---------- privacy
    const privacyBadge = (w.privacyBadge = () => {
      if (w.micOn) return;
      const rec = $('#recSwitch').getAttribute('aria-checked') === 'true', log = $('#logSwitch').getAttribute('aria-checked') === 'true';
      $('#st-privacy').innerHTML = rec || log ? `<span class="badge warn">${I('triangle-alert', 12)}${rec && log ? 'Saving audio + text' : rec ? 'Recordings saved' : 'Logging text'}</span>` : `${I('eye-off', 14)}No audio or text kept`;
    });
    // "Save recordings" has no config key of its own: it is on when recordings_dir is set.
    $('#recSwitch').addEventListener('change', (e) => { $('#recMore').hidden = !e.detail; privacyBadge(); });
    $('#logSwitch').addEventListener('change', (e) => { $('#logMore').hidden = !e.detail; privacyBadge(); });
    $('#pageSwitch')?.addEventListener('change', (e) => { $('#pageOffWarn').hidden = e.detail; });

    // ---------- advanced disclosure (remembered)
    const adv = $('#advBtn'), advBody = $('#advBody');
    const setAdv = (open) => { adv.setAttribute('aria-expanded', String(open)); advBody.hidden = !open; adv.querySelector('span').textContent = open ? 'Hide advanced settings' : 'Show advanced settings'; try { localStorage.setItem('flowd-adv', open ? '1' : ''); } catch {} };
    adv.addEventListener('click', () => setAdv(adv.getAttribute('aria-expanded') !== 'true'));
    try { if (localStorage.getItem('flowd-adv')) setAdv(true); } catch {}
    if (location.hash === '#advanced') setAdv(true);

    // ---------- reset to defaults (settings-api.js does the real resets)
    const dlg = $('#resetDlg');
    $('#resetAll').addEventListener('click', () => dlg.showModal());
    $('#rdCancel').addEventListener('click', () => dlg.close());
    dlg.addEventListener('close', () => $('#resetAll').focus());
    if (demo) {
      $$('[data-reset]').forEach((b) => b.addEventListener('click', () => {
        const which = b.dataset.reset;
        const done = { cues: () => w.cues.reset(w.defaults.cues), terms: () => w.termTags.reset(w.defaults.terminals), order: () => w.order.reset(w.defaults.order) }[which];
        done ? done() : save(b, `${which}.*`, 'defaults');
        toast(`${b.closest('.group').querySelector('h3').textContent} reset to defaults.`, { kind: 'undo', action: 'Undo', onAction: () => say('Previous values restored') });
      }));
      $('#rdOk').addEventListener('click', () => { dlg.close(); save($('#resetAll'), '*', 'defaults'); toast('All settings reset. Backup saved as config.toml.bak.', { kind: 'undo', action: 'Undo', onAction: () => say('Restored from config.toml.bak') }); });
    }

    // ---------- simulations (design mockup only; the shipped page has none of these buttons)
    $('#simCleanup')?.addEventListener('click', () => setCleanup(!F.state.cleanup));
    $('#simDaemon')?.addEventListener('click', () => { setDaemon(!F.state.daemon); $('#simDaemon').textContent = F.state.daemon ? 'Stop daemon' : 'Start daemon'; });
    $('#simSaveErr')?.addEventListener('click', () => { F.state.failNext = true; toast('The next change will fail to save.', { kind: 'info' }); });
    $('#simConflict')?.addEventListener('click', () => {
      if ($('#conflictBanner')) return;
      $('#restartBanner').insertAdjacentHTML('beforebegin', `<div class="banner" id="conflictBanner" role="alert">${I('triangle-alert', 16)}<div class="bt"><b>config.toml was edited outside this page.</b> Reload to see those changes, or keep yours and overwrite the file.</div><div class="ba"><button class="btn sm primary" id="cfReload">Reload page</button><button class="btn sm" id="cfKeep">Keep my changes</button></div></div>`);
      const rm_ = () => $('#conflictBanner').remove();
      $('#cfReload').addEventListener('click', () => { rm_(); toast('Reloaded from disk.', { kind: 'success' }); });
      $('#cfKeep').addEventListener('click', () => { rm_(); save(document.body, 'config.toml', 'overwrite'); });
      window.scrollTo({ top: 0, behavior: rm() ? 'auto' : 'smooth' });
    });

    sizeUnits();
    if (demo) { setDaemon(true); setCleanup('ready'); }
    if (location.hash && /^#[\w-]+$/.test(location.hash)) document.querySelector(location.hash)?.scrollIntoView();
    F.api?.start();
  };
  const load = (src) => new Promise((ok, bad) => { const s = document.createElement('script'); s.src = src; s.addEventListener('load', ok); s.addEventListener('error', bad); document.head.appendChild(s); });
  const base = document.currentScript.src.replace(/settings\.js.*$/, '');
  const api = document.documentElement.hasAttribute('data-api');
  load(base + 'settings-core.js').then(() => load(base + 'settings-widgets.js')).then(() => (api ? load(base + 'settings-api.js') : null)).then(boot);
})();
