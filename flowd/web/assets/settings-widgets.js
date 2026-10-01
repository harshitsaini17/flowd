/* flowd settings mockup: composite widgets (tags, reorder list, key/value table, listbox, chart). */
(() => {
  const { $, $$, I, esc, say, toast, save, rm } = window.F;

  // ================================================================ tag input
  F.initTags = (host, initial) => {
    let tags = [...initial];
    const d = host.dataset;
    const render = (focusIdx) => {
      host.innerHTML = tags.map((t, i) => `<span class="tag${d.mono !== undefined ? ' mono' : ''}" tabindex="-1" data-i="${i}">${esc(t)}<button type="button" aria-label="Remove ${esc(t)}" tabindex="-1">${I('x', 12)}</button></span>`).join('') +
        `<input type="text" aria-labelledby="${d.label}" aria-describedby="${d.desc || ''}" placeholder="${tags.length ? '' : d.placeholder}" autocomplete="off" spellcheck="false">`;
      const input = host.querySelector('input');
      if (focusIdx === 'input') input.focus();
      else if (focusIdx != null) host.querySelector(`.tag[data-i="${focusIdx}"]`)?.focus();
    };
    const persist = () => save(host, d.tags, tags);
    const remove = (i, focusAfter) => {
      const [gone] = tags.splice(i, 1);
      render(focusAfter);
      persist();
      toast(`Removed “${esc(gone)}”`, { kind: 'undo', action: 'Undo', onAction: () => { tags.splice(i, 0, gone); render('input'); persist(); say(`Restored ${gone}`); } });
    };
    const add = (raw) => {
      const v = raw.trim().replace(/,$/, '').trim();
      if (!v) return true;
      if (d.nocomma !== undefined && v.includes(',')) { showErr('Terms can’t contain commas.'); return false; }
      const dup = tags.findIndex((t) => t.toLowerCase() === v.toLowerCase());
      if (dup >= 0) {
        const chip = host.querySelector(`.tag[data-i="${dup}"]`);
        chip.classList.remove('flash'); void chip.offsetWidth; chip.classList.add('flash');
        say(`“${v}” is already in the list`);
        return true;
      }
      tags.push(v); render('input'); persist(); return true;
    };
    const showErr = (msg) => {
      let e = host.parentElement.querySelector('.field-err');
      if (!msg) { e?.remove(); host.querySelector('input')?.removeAttribute('aria-invalid'); return; }
      if (!e) { e = document.createElement('div'); e.className = 'field-err'; e.id = `te-${d.tags}`; host.after(e); }
      e.innerHTML = `${I('circle-alert', 14)}<span>${msg}</span>`;
      const input = host.querySelector('input'); input.setAttribute('aria-invalid', 'true'); input.setAttribute('aria-describedby', `${d.desc || ''} ${e.id}`);
    };
    host.addEventListener('click', (e) => {
      const b = e.target.closest('.tag button'); if (b) { remove(+b.parentElement.dataset.i, 'input'); return; }
      if (e.target === host) host.querySelector('input').focus();
    });
    host.addEventListener('keydown', (e) => {
      const input = host.querySelector('input'), chip = e.target.closest('.tag');
      if (e.target === input) {
        if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); if (add(input.value)) { host.querySelector('input').value = ''; showErr(null); } }
        else if (e.key === 'Backspace' && !input.value && tags.length) { e.preventDefault(); render(tags.length - 1); }
        else if (e.key === 'ArrowLeft' && !input.selectionStart && tags.length) { e.preventDefault(); render(tags.length - 1); }
        else if (e.key !== 'Tab') showErr(null);
      } else if (chip) {
        const i = +chip.dataset.i;
        if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); remove(i, tags.length > 1 ? Math.max(0, i - (e.key === 'Backspace' ? 1 : 0)) : 'input'); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); host.querySelector(`.tag[data-i="${Math.max(0, i - 1)}"]`)?.focus(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); const n = host.querySelector(`.tag[data-i="${i + 1}"]`); (n || input).focus(); }
        else if (e.key.length === 1) input.focus();
      }
    });
    render();
    return { reset: (v) => { tags = [...v]; render(); persist(); } };
  };

  // ================================================================ reorderable list
  F.initReorder = (ul, items) => {
    let order = [...items], grabbed = null, before = null;
    const status = { available: ['ok', 'circle-check', 'Available'], missing: ['neutral', 'circle-dashed', 'Not installed'], stopped: ['warn', 'triangle-alert', 'Installed, not running'] };
    const render = (focusName) => {
      ul.innerHTML = order.map((it, i) => {
        const [cls, ic, txt] = status[it.status];
        return `<li data-name="${it.name}" class="${it.status === 'missing' ? 'na' : ''}${grabbed === it.name ? ' grabbed' : ''}" draggable="false">
          <button class="handle" aria-label="Reorder ${it.name}, position ${i + 1} of ${order.length}" aria-pressed="${grabbed === it.name}" aria-describedby="d-order">${I('grip-vertical')}</button>
          <span class="pos">${i + 1}</span>
          <div class="meta"><div class="name">${it.name}</div><div class="cap">${it.cap}</div></div>
          <span class="moves"><button class="icon-btn" data-mv="-1" aria-label="Move ${it.name} up"${i === 0 ? ' disabled' : ''}>${I('chevron-down', 14)}</button><button class="icon-btn" data-mv="1" aria-label="Move ${it.name} down"${i === order.length - 1 ? ' disabled' : ''}>${I('chevron-down', 14)}</button></span>
          <span class="badge ${cls}">${I(ic, 12)}${txt}</span></li>`;
      }).join('');
      $$('[data-mv="-1"] svg', ul).forEach((s) => (s.style.transform = 'rotate(180deg)'));
      if (focusName) ul.querySelector(`li[data-name="${focusName}"] .handle`)?.focus();
    };
    const move = (name, delta, announce = true) => {
      const i = order.findIndex((x) => x.name === name), j = i + delta;
      if (j < 0 || j >= order.length) return;
      [order[i], order[j]] = [order[j], order[i]];
      render(name);
      if (announce) say(`${name}, moved to position ${j + 1} of ${order.length}`);
      if (!grabbed) save(ul, 'inject.order', order.map((x) => x.name));
    };
    ul.addEventListener('click', (e) => {
      const mv = e.target.closest('[data-mv]'); if (mv) { const name = mv.closest('li').dataset.name; move(name, +mv.dataset.mv); ul.querySelector(`li[data-name="${name}"] [data-mv="${mv.dataset.mv}"]`)?.focus(); }
    });
    ul.addEventListener('keydown', (e) => {
      const h = e.target.closest('.handle'); if (!h) return;
      const name = h.closest('li').dataset.name;
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        if (grabbed) { const n = grabbed; grabbed = null; render(n); say(`${n} dropped at position ${order.findIndex((x) => x.name === n) + 1}`); save(ul, 'inject.order', order.map((x) => x.name)); }
        else { grabbed = name; before = order.map((x) => x.name); render(name); say(`${name} grabbed. Use arrow keys to move, Space to drop, Escape to cancel.`); }
      } else if (grabbed && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); move(name, e.key === 'ArrowUp' ? -1 : 1); }
      else if (grabbed && e.key === 'Escape') { e.preventDefault(); order = before.map((n) => order.find((x) => x.name === n)); const n = grabbed; grabbed = null; render(n); say('Reorder cancelled'); }
    });
    // pointer drag on the handle
    ul.addEventListener('pointerdown', (e) => {
      const h = e.target.closest('.handle'); if (!h || e.button !== 0) return;
      const li = h.closest('li'), name = li.dataset.name, startY = e.clientY;
      const rows = $$('li', ul), hRow = li.offsetHeight;
      let line, target = order.findIndex((x) => x.name === name);
      h.setPointerCapture(e.pointerId);
      li.classList.add('grabbed');
      const onMove = (ev) => {
        const dy = ev.clientY - startY;
        li.style.transform = `translateY(${dy}px)`;
        const from = order.findIndex((x) => x.name === name);
        target = Math.max(0, Math.min(order.length - 1, from + Math.round(dy / hRow)));
        rows.forEach((r, k) => { if (r === li) return; let s = 0; if (from < target && k > from && k <= target) s = -hRow; if (from > target && k < from && k >= target) s = hRow; r.style.transform = s ? `translateY(${s}px)` : ''; });
        if (!line) { line = document.createElement('div'); line.className = 'drop-line'; ul.parentElement.style.position = 'relative'; ul.parentElement.appendChild(line); }
        line.style.top = `${(target + (target > from ? 1 : 0)) * hRow - 1}px`;
      };
      const onUp = () => {
        h.removeEventListener('pointermove', onMove); h.removeEventListener('pointerup', onUp); line?.remove();
        rows.forEach((r) => (r.style.transform = ''));
        const from = order.findIndex((x) => x.name === name);
        if (target !== from) { const [it] = order.splice(from, 1); order.splice(target, 0, it); say(`${name}, moved to position ${target + 1} of ${order.length}`); save(ul, 'inject.order', order.map((x) => x.name)); }
        render(name);
      };
      h.addEventListener('pointermove', onMove); h.addEventListener('pointerup', onUp);
    });
    render();
    return { reset: (v) => { order = v.map((n) => items.find((x) => x.name === n)); render(); save(ul, 'inject.order', v); } };
  };

  // ================================================================ key/value table
  // cols: { key: 'When you say', val: 'Write', type: 'text'|'mode' }
  F.initKV = (host, { rows, keyLabel, valLabel, type = 'text', builtins = new Set(), key, empty, filter, dupMsg }) => {
    let data = rows.map((r) => ({ ...r })), editing = null, q = '';
    const MODES = [['default', 'file-text', 'Default'], ['code', 'code', 'Code'], ['chat', 'message-square', 'Chat'], ['email', 'mail', 'Email']];
    const modeSeg = (v, id) => `<span class="segmented" role="radiogroup" aria-label="Mode for ${esc(id)}" data-mode-for="${esc(id)}">${MODES.map(([m, ic, t]) => `<button role="radio" aria-checked="${m === v}" tabindex="${m === v ? 0 : -1}" data-v="${m}" title="${t}">${I(ic, 14)}<span class="mt">${t}</span></button>`).join('')}</span>`;
    const persist = () => save(host, key, data);
    const render = (focusSel) => {
      const shown = data.filter((r) => !q || r.k.toLowerCase().includes(q) || String(r.v).toLowerCase().includes(q));
      const body = shown.map((r) => {
        const i = data.indexOf(r), isB = builtins.has(r.k);
        if (editing === i) return `<tr data-i="${i}"><td><input class="input sm" value="${esc(r.k)}" aria-label="${keyLabel}" data-f="k"></td>${type === 'text' ? '<td class="arrow">→</td>' : ''}<td>${type === 'text' ? `<input class="input sm" value="${esc(r.v)}" aria-label="${valLabel}" data-f="v">` : modeSeg(r.v, r.k)}</td><td class="acts"><button class="btn sm primary" data-a="ok">Save</button> <button class="btn sm" data-a="cancel">Cancel</button></td></tr>`;
        return `<tr data-i="${i}"${r.fresh ? ' class="new"' : ''}><td class="k">${esc(r.k)} ${isB ? `<span class="badge neutral" style="margin-left:6px">Built-in</span>` : ''}</td>${type === 'text' ? '<td class="arrow" aria-hidden="true">→</td>' : ''}<td${type === 'text' ? ' class="k"' : ''}>${type === 'text' ? esc(r.v) : modeSeg(r.v, r.k)}</td><td class="acts">${type === 'text' ? `<button class="icon-btn" data-a="edit" aria-label="Edit rule ‘${esc(r.k)}’">${I('pencil', 14)}</button>` : ''}${isB ? (r.v !== r.orig ? `<button class="icon-btn" data-a="reset" aria-label="Reset ${esc(r.k)} to built-in">${I('rotate-ccw', 14)}</button>` : '') : `<button class="icon-btn" data-a="del" aria-label="Delete ${type === 'text' ? 'rule' : 'app'} ‘${esc(r.k)}’">${I('trash-2', 14)}</button>`}</td></tr>`;
      }).join('');
      const emptyRow = !data.length ? `<tr><td colspan="4"><div class="empty">${I(empty.icon, 20)}<div><b>${empty.title}</b><p>${empty.text}</p></div></div></td></tr>` : !shown.length ? `<tr><td colspan="4"><div class="empty">${I('search', 20)}<div><b>No matches for “${esc(q)}”.</b><p>Try part of the app id, like “term”.</p></div></div></td></tr>` : '';
      host.innerHTML = `<table class="kv sticky"><thead><tr><th scope="col">${keyLabel}</th>${type === 'text' ? '<th aria-hidden="true"></th>' : ''}<th scope="col">${valLabel}</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>${body}${emptyRow}</tbody>
        <tfoot><tr><td><input class="input sm" placeholder="${type === 'text' ? 'spoken phrase' : 'app id'}" aria-label="New ${keyLabel.toLowerCase()}" data-new="k" style="font-family:var(--font-mono);font-size:.8125rem"></td>${type === 'text' ? '<td class="arrow" aria-hidden="true">→</td>' : ''}<td>${type === 'text' ? `<input class="input sm" placeholder="written form" aria-label="New ${valLabel.toLowerCase()}" data-new="v" style="font-family:var(--font-mono);font-size:.8125rem">` : `<span class="select-wrap"><select class="input sm" data-new="v" aria-label="Mode for new app">${MODES.map(([m, , t]) => `<option value="${m}">${t}</option>`).join('')}</select>${I('chevron-down', 14)}</span>`}</td><td class="acts"><button class="btn sm" data-a="add">${I('plus', 14)}Add</button></td></tr></tfoot></table>`;
      data.forEach((r) => delete r.fresh);
      $$('[data-mode-for]', host).forEach((seg) => F.initSegmented(seg, (v) => { const r = data.find((x) => x.k === seg.dataset.modeFor); r.v = v; persist(); if (builtins.has(r.k)) setTimeout(() => render(`[data-mode-for="${CSS.escape(r.k)}"] [aria-checked="true"]`), 0); }));
      if (focusSel) host.querySelector(focusSel)?.focus();
    };
    const err = (input, msg) => {
      const td = input.closest('td'); td.querySelector('.field-err')?.remove();
      if (!msg) { input.removeAttribute('aria-invalid'); return; }
      input.setAttribute('aria-invalid', 'true');
      td.insertAdjacentHTML('beforeend', `<div class="field-err" id="kve-${Date.now()}">${I('circle-alert', 14)}<span>${msg}</span></div>`);
      input.setAttribute('aria-describedby', td.querySelector('.field-err').id); input.focus();
    };
    const addRow = () => {
      const k = host.querySelector('[data-new="k"]'), v = host.querySelector('[data-new="v"]');
      const kv = k.value.trim(), vv = v.value.trim();
      if (!kv) return err(k, `Enter ${type === 'text' ? 'what you say' : 'an app id'}.`);
      if (data.some((r) => r.k.toLowerCase() === kv.toLowerCase())) return err(k, dupMsg(kv, data.find((r) => r.k.toLowerCase() === kv.toLowerCase()).v));
      if (type === 'text' && !vv) return err(v, 'Enter what to write.');
      data.push({ k: kv, v: vv || 'default', fresh: true }); persist(); render('[data-new="k"]'); say(`Added ${kv}`);
    };
    host.addEventListener('click', (e) => {
      const b = e.target.closest('[data-a]'); if (!b) return;
      const tr = b.closest('tr'), i = tr?.dataset.i != null ? +tr.dataset.i : null;
      const a = b.dataset.a;
      if (a === 'add') addRow();
      if (a === 'edit') { editing = i; render(`tr[data-i="${i}"] input`); }
      if (a === 'cancel') { editing = null; render(`tr[data-i="${i}"] [data-a="edit"]`); }
      if (a === 'ok') {
        const k = tr.querySelector('[data-f="k"]'), v = tr.querySelector('[data-f="v"]');
        if (!k.value.trim()) return err(k, 'Enter what you say.');
        if (data.some((r, j) => j !== i && r.k.toLowerCase() === k.value.trim().toLowerCase())) return err(k, dupMsg(k.value.trim(), ''));
        data[i] = { k: k.value.trim(), v: v.value.trim() }; editing = null; persist(); render(`tr[data-i="${i}"] [data-a="edit"]`);
      }
      if (a === 'del') {
        const [gone] = data.splice(i, 1); persist(); render('[data-new="k"]');
        toast(`Deleted “${esc(gone.k)}”`, { kind: 'undo', action: 'Undo', onAction: () => { data.splice(i, 0, gone); persist(); render(); say(`Restored ${gone.k}`); } });
      }
      if (a === 'reset') { data[i].v = data[i].orig; persist(); render(); say(`${data[i].k} reset to built-in`); }
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('[data-new]')) { e.preventDefault(); addRow(); }
      if (e.target.matches('tr[data-i] input')) {
        if (e.key === 'Enter') { e.preventDefault(); e.target.closest('tr').querySelector('[data-a="ok"]').click(); }
        if (e.key === 'Escape') { e.preventDefault(); e.target.closest('tr').querySelector('[data-a="cancel"]').click(); }
      }
    });
    host.addEventListener('input', (e) => { if (e.target.getAttribute('aria-invalid')) err(e.target, null); });
    if (filter) filter.addEventListener('input', () => { q = filter.value.trim().toLowerCase(); render(); filter.focus(); });
    render();
    return { reset: () => { data = rows.map((r) => ({ ...r })); render(); persist(); }, add: (k) => { const f = host.querySelector('[data-new="k"]'); f.value = k; f.focus(); } };
  };

  // ================================================================ device listbox (2-line options)
  F.initListbox = (host, options, selected) => {
    let sel = selected, open = false, active = 0;
    const id = 'devlb';
    const cur = () => options.find((o) => o.id === sel) || { name: sel, node: 'Not connected', missing: true };
    const render = () => {
      const c = cur();
      host.innerHTML = `<button class="lb-btn" aria-haspopup="listbox" aria-expanded="${open}" aria-controls="${id}" aria-labelledby="l-dev lbv" id="lbBtn"><span class="two" id="lbv"><b>${esc(c.name)}</b><small>${esc(c.node)}</small></span>${c.missing ? '<span class="badge warn">' + I('triangle-alert', 12) + 'Not connected</span>' : ''}${I('chevron-down', 14)}</button>` +
        (open ? `<ul class="lb" role="listbox" id="${id}" aria-labelledby="l-dev" tabindex="-1" aria-activedescendant="opt-${active}">${options.map((o, i) => `<li role="option" id="opt-${i}" aria-selected="${o.id === sel}" class="${i === active ? 'active' : ''}" data-i="${i}">${I('check', 14)}<span class="two"><b>${esc(o.name)}</b><small>${esc(o.node)}</small></span></li>`).join('')}</ul>` : '');
      if (open) host.querySelector('.lb').focus();
    };
    const close = (focus = true) => { open = false; render(); if (focus) host.querySelector('.lb-btn').focus(); };
    const choose = (i) => { const prev = sel; sel = options[i].id; close(); if (prev !== sel) save(host, 'audio.device', sel, { restart: true, revert: () => { sel = prev; render(); } }); };
    let typed = '', typedT;
    host.addEventListener('click', (e) => {
      if (e.target.closest('.lb-btn')) { open = !open; active = Math.max(0, options.findIndex((o) => o.id === sel)); render(); return; }
      const li = e.target.closest('li[role=option]'); if (li) choose(+li.dataset.i);
    });
    host.addEventListener('keydown', (e) => {
      if (!open) { if (['ArrowDown', 'ArrowUp'].includes(e.key) && e.target.closest('.lb-btn')) { e.preventDefault(); open = true; active = Math.max(0, options.findIndex((o) => o.id === sel)); render(); } return; }
      const k = e.key;
      if (k === 'ArrowDown') active = Math.min(options.length - 1, active + 1);
      else if (k === 'ArrowUp') active = Math.max(0, active - 1);
      else if (k === 'Home') active = 0; else if (k === 'End') active = options.length - 1;
      else if (k === 'Enter' || k === ' ') { e.preventDefault(); return choose(active); }
      else if (k === 'Escape' || k === 'Tab') { if (k === 'Escape') e.preventDefault(); return close(k === 'Escape'); }
      else if (k.length === 1) { typed += k.toLowerCase(); clearTimeout(typedT); typedT = setTimeout(() => (typed = ''), 600); const f = options.findIndex((o) => o.name.toLowerCase().startsWith(typed)); if (f >= 0) active = f; }
      else return;
      e.preventDefault(); render();
      host.querySelector(`#opt-${active}`)?.scrollIntoView({ block: 'nearest' });
    });
    document.addEventListener('pointerdown', (e) => { if (open && !host.contains(e.target)) close(false); });
    render();
  };

  // ================================================================ latency chart (inline SVG, focusable bars, table twin)
  F.initChart = (wrap, sessions) => {
    const narrow = wrap.clientWidth < 480;
    const W = 700, H = 132, padR = narrow ? 0 : 72, padB = 16;
    const lat = sessions.map((s) => s.ms), sorted = [...lat].sort((a, b) => a - b);
    const pc = (p) => sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)]; // nearest-rank, like metrics._percentile
    const p50 = pc(50), p95 = pc(95), max = Math.max(1200, pc(99) * 1.1);
    const y = (v) => H - padB - (v / max) * (H - padB - 6);
    const bw = (W - padR) / sessions.length;
    const grid = [0, 500, 1000].map((v) => `<line class="grid" x1="0" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text class="lbl" x="${W - padR + 6}" y="${y(v) + 4}" opacity=".7">${v}</text>`).join('');
    const bars = sessions.map((s, i) => `<rect class="bar${s.fb ? ' fb' : ''}" x="${i * bw + 1}" y="${y(s.ms)}" width="${Math.max(2, bw - 3)}" height="${H - padB - y(s.ms)}" rx="1" tabindex="${i === sessions.length - 1 ? 0 : -1}" data-i="${i}" aria-label="Session ${s.n}, ${s.t}, ${s.ms} milliseconds, ${s.mode}${s.fb ? ', used fallback' : ''}"/>${s.fb ? `<rect x="${i * bw + 1}" y="${y(s.ms)}" width="${Math.max(2, bw - 3)}" height="3" fill="var(--warn)" pointer-events="none"/>` : ''}`).join('');
    const line = (v, cls, label, dash) => `<line x1="0" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" stroke="${cls}" stroke-width="${dash === 'dot' ? 1 : 1.5}" ${dash === 'dash' ? 'stroke-dasharray="5 4"' : dash === 'dot' ? 'stroke-dasharray="1.5 3"' : ''}/><text class="lbl" x="${W - padR + 6}" y="${y(v) + 4}" style="fill:${cls}">${label}</text>`;
    wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="group" aria-labelledby="chartTitle" aria-describedby="chartSum">
      <defs><pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="4" height="4" fill="color-mix(in srgb, var(--warn) 22%, transparent)"/><line x1="0" y1="0" x2="0" y2="4" stroke="var(--warn)" stroke-width="1.6"/></pattern></defs>
      ${grid}${bars}${line(1000, 'var(--danger)', 'budget', 'dot')}${line(p95, 'var(--text)', `p95 ${p95}`, 'dash')}${line(p50, 'var(--primary)', `p50 ${p50}`)}
    </svg><p class="sr-only" id="chartSum">p50 ${p50} milliseconds, p95 ${p95} milliseconds, budget 1000. ${sessions.filter((s) => s.fb).length} sessions used fallback. Use left and right arrow keys to step through sessions.</p>`;
    // svg text would stretch with preserveAspectRatio=none; draw labels in an HTML overlay instead
    const svg = wrap.querySelector('svg');
    svg.querySelectorAll('text').forEach((t) => t.remove());
    const labels = [[1000, 'budget 1000', 'var(--danger)'], [p95, `p95 ${p95}`, 'var(--text)'], [p50, `p50 ${p50}`, 'var(--primary)']];
    const ov = document.createElement('div'); ov.setAttribute('aria-hidden', 'true');
    ov.style.cssText = `position:absolute;inset:8px 0 0 0;pointer-events:none;${narrow ? 'display:none;' : ''}`;
    // Label collision avoidance: sort by y, push apart to >= 13 px (in chart units), keep inside the plot.
    const all = [...labels.map(([v, t, c]) => ({ y: y(v), t, c, w: 400 })), ...[0, 500].map((v) => ({ y: y(v), t: v === 0 ? '0 ms' : String(v), c: 'var(--text-2)', w: 400, tick: true }))]
      .sort((a, b) => a.y - b.y);
    // Drop a tick label that would collide with a reference label: reference lines matter more.
    const kept = all.filter((l, i) => !l.tick || all.every((o) => o === l || o.tick || Math.abs(o.y - l.y) >= 13));
    for (let i = 1; i < kept.length; i++) if (kept[i].y - kept[i - 1].y < 13) kept[i].y = kept[i - 1].y + 13;
    ov.innerHTML = kept.map((l) => `<span style="position:absolute;right:0;width:${(padR / W) * 100 - 1}%;top:${(l.y / H) * 100}%;translate:0 -50%;font:400 11px/1 var(--font-sans);font-variant-numeric:tabular-nums;color:${l.c};white-space:nowrap">${l.t}</span>`).join('');
    wrap.appendChild(ov);
    const tip = document.createElement('div'); tip.className = 'chart-tip'; tip.hidden = true; wrap.appendChild(tip);
    const show = (rect) => {
      const s = sessions[+rect.dataset.i], r = rect.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      tip.textContent = `#${s.n} · ${s.t} · ${s.ms} ms · ${s.mode} · ${s.via}${s.fb ? ' · fallback' : ''}`;
      tip.style.left = `${Math.min(w.width - 90, Math.max(90, r.left - w.left + r.width / 2))}px`; tip.style.top = `${r.top - w.top + 8}px`; tip.hidden = false;
    };
    svg.addEventListener('pointerover', (e) => { if (e.target.matches('.bar')) show(e.target); });
    svg.addEventListener('pointerleave', () => (tip.hidden = true));
    svg.addEventListener('focusin', (e) => { if (e.target.matches('.bar')) show(e.target); });
    svg.addEventListener('focusout', () => (tip.hidden = true));
    svg.addEventListener('keydown', (e) => {
      if (!e.target.matches('.bar')) return;
      const bs = [...svg.querySelectorAll('.bar')], i = bs.indexOf(e.target);
      const n = e.key === 'ArrowLeft' ? i - 1 : e.key === 'ArrowRight' ? i + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? bs.length - 1 : null;
      if (n == null || !bs[n]) return;
      e.preventDefault(); e.target.tabIndex = -1; bs[n].tabIndex = 0; bs[n].focus();
    });
    return { p50, p95 };
  };
})();
