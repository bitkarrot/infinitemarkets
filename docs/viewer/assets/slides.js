/* Slide deck renderer: reads slides/deck.md (conventions in its header
   comment) and renders it with the viewer's brutalist styling. No build step,
   no dependencies beyond the vendored mermaid. */
(function () {
  const THEME_KEY = 'imv-theme';
  const DECK = 'slides/deck.md';
  const BASE = 'slides/';
  const ACCENTS = { lime: '#c8f53c', yellow: '#ffd23d', orange: '#ff6a1f',
                    pink: '#ff5aa8', mint: '#4fdc9a', blue: '#2e6bff' };
  const TAGS = ['shipped', 'tested', 'spec-aligned', 'todo', 'roadmap'];

  const stage = document.getElementById('stage');
  const counter = document.getElementById('zoomPct');
  const bar = document.querySelector('#progress span');
  const notes = document.getElementById('notes');
  const themeBtn = document.getElementById('themeBtn');
  let slides = [], cur = 0;

  /* ---------- markdown ---------- */
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  function inline(src) {
    const codes = [];
    let s = esc(src).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
    s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
         .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
         .replace(new RegExp(`\\[(${TAGS.join('|')})\\]`, 'g'), '<span class="tag tag-$1">$1</span>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
  }
  const IMG = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$/;
  const isBlockStart = l => /^(```|#{1,6}\s|\||>|\s*[-*]\s|\s*\d+\.\s|!\[|<!--)/.test(l);

  function blocks(md) {
    const L = md.split('\n'), out = [];
    for (let i = 0; i < L.length;) {
      const l = L[i];
      if (!l.trim()) { i++; continue; }
      if (l.startsWith('<!--')) { while (i < L.length && !L[i].includes('-->')) i++; i++; continue; }
      let m;
      if ((m = l.match(/^```(\w*)/))) {
        const buf = []; i++;
        while (i < L.length && !L[i].startsWith('```')) buf.push(L[i++]);
        out.push({ t: 'code', lang: m[1], text: buf.join('\n') }); i++; continue;
      }
      if ((m = l.match(/^(#{1,6})\s+(.*)/))) { out.push({ t: 'h', n: m[1].length, text: m[2] }); i++; continue; }
      if (l.startsWith('|')) {
        const rows = [];
        while (i < L.length && L[i].startsWith('|')) rows.push(L[i++]);
        const cells = r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        out.push({ t: 'table', head: cells(rows[0]), rows: rows.slice(2).map(cells) }); continue;
      }
      if (l.startsWith('>')) {
        const buf = [];
        while (i < L.length && L[i].startsWith('>')) buf.push(L[i++].replace(/^>\s?/, ''));
        out.push({ t: 'quote', text: buf.join(' ') }); continue;
      }
      if ((m = l.match(/^\s*([-*]|\d+\.)\s/))) {
        const ordered = /\d/.test(m[1]), items = [];
        while (i < L.length && L[i].trim()) {
          const it = L[i].match(/^\s*([-*]|\d+\.)\s+(.*)/);
          if (it && /\d/.test(it[1]) === ordered) items.push(it[2]);
          else if (!it && /^\s+\S/.test(L[i]) && items.length) items[items.length - 1] += '\n' + L[i].trim();
          else break;
          i++;
        }
        out.push({ t: ordered ? 'ol' : 'ul', items }); continue;
      }
      if (IMG.test(l.trim())) {
        const imgs = [];
        while (i < L.length && IMG.test(L[i].trim())) {
          const [, alt, src, cap] = L[i++].trim().match(IMG);
          imgs.push({ alt, src, cap });
        }
        out.push({ t: 'img', imgs }); continue;
      }
      const buf = [l]; i++;
      while (i < L.length && L[i].trim() && !isBlockStart(L[i])) buf.push(L[i++]);
      const text = buf.join(' ');
      out.push({ t: 'p', text, label: /^\*\*[^*]+\*\*(\s*\[[a-z-]+\])*$/.test(text.trim()) });
    }
    return out;
  }

  function html(b) {
    switch (b.t) {
      case 'h': return b.n === 1 ? `<h1>${inline(b.text)}</h1>` : `<h2>${inline(b.text)}</h2>`;
      case 'p': return `<p${b.label ? ' class="label"' : ''}>${inline(b.text)}</p>`;
      case 'quote': return `<blockquote>${inline(b.text)}</blockquote>`;
      case 'ul': case 'ol':
        return `<${b.t}>${b.items.map(x => `<li>${x.split('\n').map(inline).join('<br>')}</li>`).join('')}</${b.t}>`;
      case 'table':
        return `<table><thead><tr>${b.head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>` +
          b.rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('') + `</tbody></table>`;
      case 'img':
        return b.imgs.map(x => `<figure><img src="${BASE}${esc(x.src)}" alt="${esc(x.alt)}" loading="lazy">` +
          (x.cap ? `<figcaption>${inline(x.cap)}</figcaption>` : '') + `</figure>`).join('');
      case 'code':
        return b.lang === 'mermaid'
          ? `<div class="mermaid-box" data-src="${encodeURIComponent(b.text)}"></div>`
          : `<pre><code>${esc(b.text)}</code></pre>`;
    }
    return '';
  }
  const join = bs => bs.map(html).join('');

  /* ---------- layouts ---------- */
  function groups(bs) {
    const gs = [];
    bs.forEach(b => { if (b.label || !gs.length) gs.push([]); gs[gs.length - 1].push(b); });
    return gs;
  }
  function body(layout, bs) {
    const quotes = bs.filter(b => b.t === 'quote');
    const rest = bs.filter(b => b.t !== 'quote');
    const imgs = rest.filter(b => b.t === 'img');
    const mer = rest.filter(b => b.t === 'code' && b.lang === 'mermaid');
    const text = rest.filter(b => !imgs.includes(b) && !mer.includes(b));
    let main;
    if (mer.length) {
      main = text.length
        ? `<div class="cols"><div class="col diagram">${join(mer)}</div><div class="col">${join(text)}${join(quotes)}</div></div>`
        : `<div class="cols diagram-only"><div class="col diagram">${join(mer)}</div></div>${join(quotes)}`;
      return main;
    }
    if (layout === 'gallery' && imgs.length) {
      const n = imgs.reduce((a, b) => a + b.imgs.length, 0);
      return `<div class="gallery" style="grid-template-columns:repeat(${n},1fr)">${join(imgs)}</div>${join(text)}${join(quotes)}`;
    }
    if (imgs.length) {
      main = `<div class="cols"><div class="col">${join(text)}</div><div class="col media">${join(imgs)}</div></div>`;
    } else if (layout === 'split' || layout === 'cta') {
      const gs = groups(text);
      if (gs.length > 1) {
        const k = Math.ceil(gs.length / 2);
        main = `<div class="cols"><div class="col">${gs.slice(0, k).map(join).join('')}</div>` +
               `<div class="col">${gs.slice(k).map(join).join('')}</div></div>`;
      } else main = join(text);
    } else main = join(text);
    return main + join(quotes);
  }

  function parse(md) {
    md = md.replace(/^\s*<!--(?!\s*slide:)[\s\S]*?-->\s*/, '');
    return md.split(/^---$/m).map(s => s.trim()).filter(Boolean).map(raw => {
      const meta = { layout: 'bullets', accent: 'lime', kicker: '' };
      const mm = raw.match(/^<!--\s*slide:(.*?)-->/);
      if (mm) {
        raw = raw.slice(mm[0].length);
        for (const [, k, , q, v] of mm[1].matchAll(/(\w+)=("([^"]*)"|(\S+))/g)) meta[k] = q ?? v;
      }
      const [content, ...noteParts] = raw.split(/^Note:\s*$/m);
      const bs = blocks(content);
      const h1 = bs.find(b => b.t === 'h' && b.n === 1);
      const heads = bs.filter(b => b.t === 'h');
      return { meta, title: h1 ? h1.text : '', heads,
               rest: bs.filter(b => b.t !== 'h'), notes: noteParts.join('').trim() };
    });
  }

  function build(deck) {
    stage.innerHTML = deck.map((s, i) => {
      const accent = ACCENTS[s.meta.accent] || ACCENTS.lime;
      return `<section class="slide l-${s.meta.layout}" style="--accent:${accent}" data-i="${i}">
        <span class="num">${String(i + 1).padStart(2, '0')} / ${deck.length}</span>
        ${s.meta.kicker ? `<div class="kicker">${inline(s.meta.kicker)}</div>` : ''}
        ${join(s.heads)}
        <div class="body">${body(s.meta.layout, s.rest)}</div>
      </section>`;
    }).join('');
    slides = [...stage.querySelectorAll('.slide')];
    stage.querySelectorAll('figure img').forEach(img => {
      img.addEventListener('load', () => fit(slides[cur]));
      img.addEventListener('click', () => {
        const lb = document.getElementById('lightbox');
        lb.querySelector('img').src = img.src; lb.hidden = false;
      });
    });
  }

  /* ---------- mermaid ---------- */
  async function renderDiagrams() {
    const dark = document.documentElement.dataset.theme === 'dark';
    const ink = dark ? '#f0ead8' : '#111111', paper = dark ? '#26251f' : '#fffdf7';
    for (const [n, box] of [...stage.querySelectorAll('.mermaid-box')].entries()) {
      const accent = box.closest('.slide').style.getPropertyValue('--accent');
      mermaid.initialize({
        startOnLoad: false, theme: 'base', securityLevel: 'loose',
        themeVariables: {
          fontFamily: "'Inter', system-ui, sans-serif", fontSize: '18px',
          primaryColor: accent, primaryTextColor: '#111111', nodeTextColor: '#111111', primaryBorderColor: ink,
          lineColor: ink, textColor: ink, edgeLabelBackground: paper,
          clusterBkg: dark ? '#1e1d18' : '#f4f0e6', clusterBorder: ink, titleColor: ink
        },
        flowchart: { curve: 'basis', htmlLabels: true, nodeSpacing: 46, rankSpacing: 64, padding: 14 }
      });
      try {
        const { svg } = await mermaid.render(`deck-m${n}-${Date.now()}`, decodeURIComponent(box.dataset.src));
        box.innerHTML = svg;
        const el = box.querySelector('svg');
        el.removeAttribute('width'); el.removeAttribute('height'); el.style.maxWidth = '100%';
        el.classList.add('mermaid');
        el.querySelectorAll('.edgeLabel').forEach(l => { if (!l.textContent.trim()) l.style.display = 'none'; });
        const vb = el.viewBox.baseVal;
        box.closest('.cols').classList.toggle('stack', vb.width / vb.height > 1.6);
      } catch (e) {
        box.innerHTML = `<pre>${esc(String(e.message || e))}</pre>`;
      }
    }
  }

  /* ---------- fit, navigation, chrome ---------- */
  function scaleStage() {
    const s = Math.min(innerWidth / 1640, (innerHeight - 70) / 940);
    stage.style.transform = `scale(${s})`;
    stage.style.marginBottom = '50px';
  }
  function overflowing(el) {
    return [el.querySelector('.body'), ...el.querySelectorAll('.col:not(.diagram)')]
      .some(x => x && x.scrollHeight > x.clientHeight + 2);
  }
  function fit(el) {
    if (!el) return;
    let f = 1;
    el.style.setProperty('--fit', f);
    while (overflowing(el) && f > 0.62) { f -= 0.03; el.style.setProperty('--fit', f.toFixed(2)); }
  }
  function show(i) {
    cur = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, k) => s.classList.toggle('active', k === cur));
    const s = slides[cur];
    fit(s);
    counter.textContent = `${cur + 1} / ${slides.length}`;
    bar.style.width = `${((cur + 1) / slides.length) * 100}%`;
    document.documentElement.style.setProperty('--accent', s.style.getPropertyValue('--accent'));
    const d = window.DECK[cur];
    document.getElementById('notesSrc').textContent = `slide ${cur + 1} · ${d.title.replace(/\*\*/g, '')}`;
    document.getElementById('notesBody').innerHTML = d.notes
      ? d.notes.split(/\n\s*\n/).map(p => `<p>${inline(p.replace(/\n/g, ' '))}</p>`).join('')
      : '<p><i>No notes for this slide.</i></p>';
    if (location.hash !== `#${cur + 1}`) history.replaceState(null, '', `#${cur + 1}`);
  }
  const next = () => show(cur + 1), prev = () => show(cur - 1);

  function setTheme(t) {
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.dataset.theme = t;
    themeBtn.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
  }
  themeBtn.onclick = () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    renderDiagrams().then(() => fit(slides[cur]));
  };
  setTheme(document.documentElement.dataset.theme || 'dark');
  const toggleNotes = () => notes.classList.toggle('open');
  const fullscreen = () => document.fullscreenElement
    ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  document.getElementById('next').onclick = next;
  document.getElementById('prev').onclick = prev;
  document.getElementById('notesBtn').onclick = toggleNotes;
  document.getElementById('closeNotes').onclick = () => notes.classList.remove('open');
  document.getElementById('fsBtn').onclick = fullscreen;
  document.getElementById('lightbox').onclick = e => { e.currentTarget.hidden = true; };

  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const lb = document.getElementById('lightbox');
    if (e.key === 'Escape') { lb.hidden = true; notes.classList.remove('open'); return; }
    if (['ArrowRight', 'PageDown', ' ', 'Enter'].includes(e.key)) { e.preventDefault(); next(); }
    else if (['ArrowLeft', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); prev(); }
    else if (e.key === 'Home') show(0);
    else if (e.key === 'End') show(slides.length - 1);
    else if (e.key === 'n' || e.key === 'N') toggleNotes();
    else if (e.key === 't' || e.key === 'T') themeBtn.click();
    else if (e.key === 'f' || e.key === 'F') fullscreen();
  });
  let touchX = null;
  addEventListener('touchstart', e => { touchX = e.touches[0].clientX; }, { passive: true });
  addEventListener('touchend', e => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX; touchX = null;
    if (Math.abs(dx) > 50) (dx < 0 ? next : prev)();
  });
  addEventListener('hashchange', () => show((parseInt(location.hash.slice(1), 10) || 1) - 1));
  addEventListener('resize', scaleStage);
  scaleStage();

  fetch(DECK).then(r => { if (!r.ok) throw new Error(`${DECK}: HTTP ${r.status}`); return r.text(); })
    .then(async md => {
      window.DECK = parse(md);
      build(window.DECK);
      show((parseInt(location.hash.slice(1), 10) || 1) - 1);
      await document.fonts.ready;
      await renderDiagrams();
      fit(slides[cur]);
    })
    .catch(e => { stage.innerHTML = `<section class="slide active"><h1>Could not load the deck</h1><p>${esc(e.message)}</p></section>`; });
})();
