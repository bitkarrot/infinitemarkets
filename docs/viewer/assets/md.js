/* Minimal markdown + mermaid helpers shared by slides.html and overview.html.
   Supports the subset the docs use: headings, paragraphs, lists, tables,
   blockquotes, image lines, fenced code/mermaid, **bold**, `code`, [links],
   and status tags like [shipped]. No dependencies beyond vendored mermaid. */
(function () {
  const TAGS = ['shipped', 'tested', 'spec-aligned', 'todo', 'roadmap'];
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const slug = s => s.toLowerCase().replace(/<[^>]+>|[*`]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  function inline(src) {
    const codes = [];
    let s = esc(src).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
    s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
         .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) =>
           `<a href="${u}"${/^https?:/.test(u) ? ' target="_blank" rel="noopener"' : ''}>${t}</a>`)
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

  function html(b, base = '') {
    switch (b.t) {
      case 'h': return `<h${b.n} id="${slug(b.text)}">${inline(b.text)}</h${b.n}>`;
      case 'p': return `<p${b.label ? ' class="label"' : ''}>${inline(b.text)}</p>`;
      case 'quote': return `<blockquote>${inline(b.text)}</blockquote>`;
      case 'ul': case 'ol':
        return `<${b.t}>${b.items.map(x => `<li>${x.split('\n').map(inline).join('<br>')}</li>`).join('')}</${b.t}>`;
      case 'table':
        return `<table><thead><tr>${b.head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>` +
          b.rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('') + `</tbody></table>`;
      case 'img':
        return b.imgs.map(x => `<figure><img src="${base}${esc(x.src)}" alt="${esc(x.alt)}" loading="lazy">` +
          (x.cap ? `<figcaption>${inline(x.cap)}</figcaption>` : '') + `</figure>`).join('');
      case 'code':
        return b.lang === 'mermaid'
          ? `<div class="mermaid-box" data-src="${encodeURIComponent(b.text)}"></div>`
          : `<pre><code>${esc(b.text)}</code></pre>`;
    }
    return '';
  }
  const join = (bs, base) => bs.map(b => html(b, base)).join('');

  /* Render every .mermaid-box under root. accentOf(box) picks the node fill;
     onRender(box, svg) lets callers adapt layout to the diagram's shape. */
  async function renderMermaid(root, accentOf, onRender) {
    const dark = document.documentElement.dataset.theme === 'dark';
    const ink = dark ? '#f0ead8' : '#111111', paper = dark ? '#26251f' : '#fffdf7';
    for (const [n, box] of [...root.querySelectorAll('.mermaid-box')].entries()) {
      mermaid.initialize({
        startOnLoad: false, theme: 'base', securityLevel: 'loose',
        themeVariables: {
          fontFamily: "'Inter', system-ui, sans-serif", fontSize: '18px',
          primaryColor: accentOf(box), primaryTextColor: '#111111', nodeTextColor: '#111111',
          primaryBorderColor: ink, lineColor: ink, textColor: ink, edgeLabelBackground: paper,
          clusterBkg: dark ? '#1e1d18' : '#f4f0e6', clusterBorder: ink, titleColor: ink
        },
        flowchart: { curve: 'basis', htmlLabels: true, nodeSpacing: 46, rankSpacing: 64, padding: 14 }
      });
      try {
        const { svg } = await mermaid.render(`md-m${n}-${Date.now()}`, decodeURIComponent(box.dataset.src));
        box.innerHTML = svg;
        const el = box.querySelector('svg');
        el.removeAttribute('width'); el.removeAttribute('height'); el.style.maxWidth = '100%';
        el.classList.add('mermaid');
        el.querySelectorAll('.edgeLabel').forEach(l => { if (!l.textContent.trim()) l.style.display = 'none'; });
        if (onRender) onRender(box, el);
      } catch (e) {
        box.innerHTML = `<pre>${esc(String(e.message || e))}</pre>`;
      }
    }
  }

  function themeToggle(btn, onChange) {
    const KEY = 'imv-theme';
    const paint = () => { btn.textContent = document.documentElement.dataset.theme === 'dark' ? '☀ Light' : '☾ Dark'; };
    btn.addEventListener('click', () => {
      const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = t;
      localStorage.setItem(KEY, t);
      paint();
      if (onChange) onChange(t);
    });
    paint();
  }

  function lightbox(root) {
    let lb = document.getElementById('lightbox');
    if (!lb) {
      lb = document.createElement('div');
      lb.id = 'lightbox'; lb.hidden = true;
      document.body.appendChild(lb);
    }
    lb.onclick = () => { lb.hidden = true; lb.innerHTML = ''; };
    addEventListener('keydown', e => { if (e.key === 'Escape') { lb.hidden = true; lb.innerHTML = ''; } });
    root.addEventListener('click', e => {
      const img = e.target.closest('figure img, img[data-zoom]');
      const svg = !img && e.target.closest('.mermaid-box')?.querySelector('svg');
      if (img) {
        lb.innerHTML = `<img src="${esc(img.currentSrc || img.src)}" alt="${esc(img.alt)}">`;
      } else if (svg) {
        lb.innerHTML = '<div class="lb-diagram"></div>';
        lb.firstChild.appendChild(svg.cloneNode(true));
      } else return;
      lb.hidden = false;
    });
  }

  window.MD = { esc, slug, inline, blocks, html, join, renderMermaid, themeToggle, lightbox };
})();
