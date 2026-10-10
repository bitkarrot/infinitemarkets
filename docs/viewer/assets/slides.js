/* Slide deck renderer: reads slides/deck.md (conventions in its header
   comment) and renders it with the viewer's brutalist styling. Markdown,
   mermaid, theme and lightbox helpers come from md.js. */
(function () {
  const DECK = 'slides/deck.md';
  const BASE = 'slides/';
  const ACCENTS = { lime: '#c8f53c', yellow: '#ffd23d', orange: '#ff6a1f',
                    pink: '#ff5aa8', mint: '#4fdc9a', blue: '#2e6bff' };

  const stage = document.getElementById('stage');
  const counter = document.getElementById('zoomPct');
  const bar = document.querySelector('#progress span');
  const notes = document.getElementById('notes');
  const themeBtn = document.getElementById('themeBtn');
  let slides = [], cur = 0;

  const { esc, inline, blocks } = MD;
  const html = b => MD.html(b, BASE);
  const join = bs => MD.join(bs, BASE);

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
    stage.querySelectorAll('figure img').forEach(img => img.addEventListener('load', () => fit(slides[cur])));
  }

  /* ---------- mermaid ---------- */
  const renderDiagrams = () => MD.renderMermaid(stage,
    box => box.closest('.slide').style.getPropertyValue('--accent'),
    (box, svg) => {
      const vb = svg.viewBox.baseVal;
      box.closest('.cols').classList.toggle('stack', vb.width / vb.height > 1.6);
    });

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

  MD.themeToggle(themeBtn, () => renderDiagrams().then(() => fit(slides[cur])));
  const toggleNotes = () => notes.classList.toggle('open');
  const fullscreen = () => document.fullscreenElement
    ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  document.getElementById('next').onclick = next;
  document.getElementById('prev').onclick = prev;
  document.getElementById('notesBtn').onclick = toggleNotes;
  document.getElementById('closeNotes').onclick = () => notes.classList.remove('open');
  document.getElementById('fsBtn').onclick = fullscreen;
  MD.lightbox(stage);

  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape') { notes.classList.remove('open'); return; }
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
