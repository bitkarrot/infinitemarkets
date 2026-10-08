(function () {
  const THEME_KEY = 'imv-theme';
  const id = new URLSearchParams(location.search).get('d') || window.DIAGRAMS[0].id;
  let d = null;

  const s = document.createElement('script');
  s.src = 'diagrams/' + id + '.js';
  s.onload = () => init(window.DIAGRAM_DATA[id]);
  s.onerror = () => { document.getElementById('hudTitle').textContent = 'Diagram not found: ' + id; };
  document.body.appendChild(s);

  function initMermaid(theme) {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      themeVariables: {
        fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        fontSize: '19px',
        lineColor: '#111111',
        primaryTextColor: '#111111',
        edgeLabelBackground: theme === 'dark' ? '#26251f' : '#fffdf7'
      },
      flowchart: { curve: 'basis', htmlLabels: true, nodeSpacing: 70, rankSpacing: 110, padding: 18 },
      securityLevel: 'loose'
    });
  }

  const vp = document.getElementById('viewport');
  const cv = document.getElementById('canvas');
  const pct = document.getElementById('zoomPct');
  const themeBtn = document.getElementById('themeBtn');
  let scale = 1, tx = 0, ty = 0, natW = 0, natH = 0;

  function getTheme() { return localStorage.getItem(THEME_KEY) || 'dark'; }
  function setTheme(t) {
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.dataset.theme = t;
    themeBtn.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
    if (d) render();
  }
  themeBtn.onclick = () => setTheme(getTheme() === 'dark' ? 'light' : 'dark');
  themeBtn.textContent = getTheme() === 'dark' ? '☀ Light' : '☾ Dark';

  function apply() {
    cv.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    pct.textContent = Math.round(scale * 100) + '%';
  }
  function zoomAt(mx, my, ds) {
    const ns = Math.min(8, Math.max(0.05, scale * ds));
    tx = mx - (mx - tx) * ns / scale;
    ty = my - (my - ty) * ns / scale;
    scale = ns; apply();
  }
  function fit(mode) {
    let s;
    if (mode === 'w')      s = (innerWidth - 60) / natW;
    else if (mode === 'h') s = (innerHeight - 140) / natH;
    else                   s = Math.min((innerWidth - 60) / natW, (innerHeight - 140) / natH);
    scale = Math.min(s, 4);
    tx = natW * scale <= innerWidth ? (innerWidth - natW * scale) / 2 : 40;
    ty = natH * scale <= innerHeight ? (innerHeight - natH * scale) / 2 : 90;
    apply();
  }

  function render(refit) {
    cv.innerHTML = '';
    const pre = document.createElement('pre');
    pre.className = 'mermaid';
    pre.textContent = d.mermaid + '\n' + d.styles[getTheme()];
    cv.appendChild(pre);
    initMermaid(getTheme());
    return mermaid.run({ nodes: [pre] }).then(() => {
      const svg = cv.querySelector('svg');
      const vb = svg.viewBox.baseVal;
      natW = vb.width; natH = vb.height;
      svg.removeAttribute('width');
      svg.style.width = natW + 'px';
      svg.style.height = natH + 'px';
      if (refit) fit(); else apply();
    });
  }

  vp.addEventListener('wheel', e => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0016));
  }, { passive: false });

  let drag = null;
  vp.addEventListener('pointerdown', e => {
    drag = { x: e.clientX - tx, y: e.clientY - ty };
    vp.classList.add('dragging'); vp.setPointerCapture(e.pointerId);
  });
  vp.addEventListener('pointermove', e => {
    if (!drag) return;
    tx = e.clientX - drag.x; ty = e.clientY - drag.y; apply();
  });
  vp.addEventListener('pointerup', () => { drag = null; vp.classList.remove('dragging'); });
  vp.addEventListener('dblclick', () => fit());

  document.getElementById('zin').onclick    = () => zoomAt(innerWidth/2, innerHeight/2, 1.3);
  document.getElementById('zout').onclick   = () => zoomAt(innerWidth/2, innerHeight/2, 1/1.3);
  document.getElementById('fit').onclick    = () => fit();
  document.getElementById('fitw').onclick   = () => fit('w');
  document.getElementById('fith').onclick   = () => fit('h');
  document.getElementById('actual').onclick = () => { scale = 1; tx = 60; ty = 90; apply(); };

  const notes = document.getElementById('notes');
  document.getElementById('notesBtn').onclick   = () => notes.classList.toggle('open');
  document.getElementById('closeNotes').onclick = () => notes.classList.remove('open');

  function init(data) {
    if (!data) return;
    d = data;
    document.title = d.title + ' — infinitemarkets';
    document.getElementById('hudTitle').textContent = d.title;
    document.getElementById('hudSrc').textContent = d.source;

    document.getElementById('legend').innerHTML =
      d.legend.map(l => `<span><span class="sw" style="background:${l.color}"></span>${l.label}</span>`).join('');

    document.getElementById('notesTitle').textContent = d.title;
    document.getElementById('notesSrc').textContent = d.source;
    document.getElementById('notesBody').innerHTML =
      d.sections.map(sec =>
        `<h3>${sec.heading}</h3><ul>` +
        sec.bullets.map(b => `<li>${b}</li>`).join('') +
        `</ul>`).join('');

    render(true);
  }
})();
