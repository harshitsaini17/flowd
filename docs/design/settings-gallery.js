/* State gallery for the design mockup (docs/design/settings.html) only; it is not shipped with
   flowd. It draws static examples of every control state into #gallery, #empties and
   #toastGallery once settings.js has booted. Static styling comes from the utility classes in
   settings.css, so the page needs no style= attributes. */
(() => {
  const draw = () => {
    const { $, $$, I } = window.F;
    const { badge } = F.w;
    const sw = (on, label, cls = '', extra = '') => `<button class="switch${cls}" role="switch" aria-checked="${on}" aria-label="${label}"${extra}><span class="chk">${I('check', 10)}</span></button>`;
    const latency = (cls, body) => `<div class="card${cls} u-flex1"><div class="ct">${I('timer', 14)}Latency</div>${body}</div>`;
    const G = [
      ['Toggle: off / on', sw(false, 'Off example') + sw(true, 'On example')],
      ['Toggle: focus / disabled', sw(true, 'Focused example', ' focus-sim') + sw(false, 'Disabled example', ' sim-disabled', ' aria-disabled="true"') + sw(true, 'Disabled on example', ' sim-disabled', ' aria-disabled="true"')],
      ['Buttons', '<button class="btn primary">Primary</button><button class="btn">Secondary</button><button class="btn hover-sim">Hover</button><button class="btn sim-disabled" aria-disabled="true">Disabled</button>'],
      ['Number: default / invalid', `<span class="num"><input class="input" value="350" aria-label="example"><span class="unit">ms</span></span><span class="num invalid"><span class="err-ico">${I('circle-alert', 14)}</span><input class="input" value="-5" aria-invalid="true" aria-label="invalid example"><span class="unit">ms</span></span><div class="field-err u-full">${I('circle-alert', 14)}<span>Must be a whole number above 0. Still using 350 ms.</span></div>`],
      ['Input: focus', '<input class="input focus-sim u-w140" value="Super+D" aria-label="focus example">'],
      ['Segmented', '<span class="segmented"><button aria-checked="true" role="radio">Toggle</button><button aria-checked="false" role="radio" tabindex="-1">Push-to-talk</button></span>'],
      ['Badges', badge('ok', 'circle-check', 'Online') + badge('warn', 'triangle-alert', 'Offline') + badge('danger', 'circle-alert', 'Failed') + badge('neutral', 'circle-dashed', 'Not installed') + badge('restart', 'power', 'Requires restart')],
      ['Row feedback', `<span class="feedback u-noanim">${I('loader-circle', 12)}</span><span class="feedback u-noanim"><span class="ok">${I('check', 12)}</span>Saved</span>`],
      ['Copy button', `<button class="copy">${I('copy', 14)}<span>Copy</span></button><button class="copy" data-s="ok">${I('check', 14)}<span>Copied</span></button><button class="copy" data-s="err">${I('circle-alert', 14)}<span>Select and copy</span></button>`],
      ['Status card: loading / empty / degraded', latency('', '<span class="skel"></span>') + latency('', '<div class="cv">—</div><div class="cs">No sessions yet</div>') + latency(' warn', `<div class="cv">${I('triangle-alert', 16)}1140<small>ms p95</small></div><div class="cs">Above the 1000 ms budget</div>`)],
    ];
    $('#gallery').innerHTML = G.map(([l, v]) => `<div class="cell${l.startsWith('Status card') ? ' u-span' : ''}"><span class="gl">${l}</span><div class="gv">${v}</div></div>`).join('');
    // CSSOM writes are allowed by the page's CSP; style= attributes are not.
    $$('#gallery .card.warn .cv svg').forEach((s) => Object.assign(s.style, { display: 'inline', verticalAlign: '-1px', marginRight: '4px' }));
    $$('#gallery button').forEach((b) => b.addEventListener('click', (e) => e.preventDefault()));

    const EM = [
      ['book-a', 'No custom terms yet.', 'Add names and acronyms the recognizer should spell your way, like Hyprland or LLM.', 'Add term'],
      ['app-window', 'Using built-in modes only.', '17 apps are mapped by default. Add one to override.', 'Add app'],
      ['audio-lines', 'No dictations yet.', 'Press your hotkey or click the indicator to try it.', 'Show hotkey setup'],
      ['mic-off', 'No input devices found.', 'Check that PipeWire is running: systemctl --user status pipewire', 'Refresh'],
    ];
    $('#empties').innerHTML = EM.map(([ic, t, d, a], i) => `<div class="empty${i ? ' u-bt' : ''}">${I(ic, 20)}<div><b>${t}</b><p>${d}</p><button class="btn sm">${a}</button></div></div>`).join('');

    const T = [
      ['success', 'check', 'flowd restarted. All changes are active.', ''],
      ['undo', null, 'Removed “scratch that”', 'Undo'],
      ['warn', 'triangle-alert', 'Cleanup went offline. Pasting as heard.', ''],
      ['error', 'circle-alert', 'Couldn’t save. config.toml isn’t writable.', 'Retry'],
    ];
    $('#toastGallery').innerHTML = T.map(([k, ic, m, a]) => `<div class="toast ${k} u-noanim">${ic ? I(ic) : ''}<span class="msg">${m}</span>${a ? `<button class="btn ghost sm">${a}</button>` : ''}<button class="icon-btn" aria-label="Dismiss">${I('x', 14)}</button></div>`).join('');
  };
  if (window.F?.ready) draw();
  else document.addEventListener('flowd:ready', draw, { once: true });
})();
