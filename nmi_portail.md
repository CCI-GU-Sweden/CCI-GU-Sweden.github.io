---
layout: default
title: CCI help and documentation page
permalink: /docs/nmi_portail/
---

<div style="display:flex;gap:.5rem;align-items:center;margin:.5rem 0 1rem;">
  <a id="pdf-link" class="button" href="#" style="display:none;">Download PDF</a>
  <button id="pdf-btn" style="display:none;">Generate PDF</button>
  <span id="pdf-status" style="font-size:.9rem;color:#666;"></span>
</div>

<div id="md-content"><em>Loading…</em></div>

<script>
// CONFIG  
const mdUrl = 'https://raw.githubusercontent.com/CCI-GU-Sweden/CCI_registration_documents/refs/heads/main/NMI%20portail.md';
const pdfBaseName = 'NMI%20portail';

// Prebuilt PDF locations (served via GitHub Pages or raw)
const prebuiltPdf = `https://cci-gu-sweden.github.io/CCI_registration_documents/assets/pdfs/${pdfBaseName}.pdf`;
const rawPdf      = `https://raw.githubusercontent.com/CCI-GU-Sweden/CCI_registration_documents/refs/heads/main/assets/pdfs/${pdfBaseName}.pdf`;

// Regex to resolve relative image paths inside the fetched Markdown
const imageRegex = /!\[(?<altText>.*?)\]\s*\((?<imageURL>[^)]+)\)|<img\s+[^>]*?src=["'](?<imageURL1>[^"']+)["'][^>]*?>/g;

async function renderMarkdownFrom(mdUrl) {
  const baseUrl = mdUrl.substring(0, mdUrl.lastIndexOf('/') + 1);
  const mdResponse = await fetch(mdUrl, { cache: 'no-store' });
  const mdText = await mdResponse.text();

  // Fix relative image URLs
  const resolvedMarkdown = mdText.replace(imageRegex, (match, _a, _b, _c, _d, _e, _f, _g, _h, _i, _j, _k, _l, _m, _n, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _aa, _ab, groups) => {
    const src = (groups && (groups.imageURL || groups.imageURL1)) || null;
    if (!src) return match;
    const absoluteUrl = src.startsWith('http') || src.startsWith('/') ? src : new URL(src, baseUrl).href;
    return match.replace(src, absoluteUrl);
  });

  document.getElementById('md-content').innerHTML = `<md>${resolvedMarkdown}</md>`;
  if (window.renderMarkdown) window.renderMarkdown();

  // Optional: open external links in a new tab
  document.querySelectorAll('#md-content a[href]').forEach(a => {
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  });
}

async function tryShowPrebuiltPdf() {
  const link = document.getElementById('pdf-link');
  const btn  = document.getElementById('pdf-btn');
  const status = document.getElementById('pdf-status');

  // Prefer Pages URL; if not found, try raw; else show generator button
  for (const href of [prebuiltPdf, rawPdf]) {
    try {
      const head = await fetch(href, { method: 'HEAD', cache: 'no-store' });
      if (head.ok) {
        link.href = href;
        link.download = `${pdfBaseName}.pdf`;
        link.style.display = '';
        return;
      }
    } catch {}
  }
  // Fallback to client-side generation
  btn.style.display = '';
  btn.addEventListener('click', async () => {
    status.textContent = 'Preparing PDF…';
    try {
      await html2pdf().set({
        margin: 10,
        filename: `${pdfBaseName}.pdf`,
        image: { type: 'png', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
      }).from(document.getElementById('md-content')).save();
      status.textContent = '';
    } catch (e) {
      console.warn(e); status.textContent = 'PDF failed — try your browser’s “Print to PDF”.';
    }
  });
}

// Kick it off
renderMarkdownFrom(mdUrl).then(tryShowPrebuiltPdf).catch(console.error);
</script>

// Markdown renderer
<script src="https://cdn.jsdelivr.net/gh/MarketingPipeline/Markdown-Tag/markdown-tag.js"></script>
// Fallback PDF generator (only used if prebuilt PDF not found)
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"
        integrity="sha512-YcsIP0wAZy0u0m4q+6YV1qg9M+oWEj83S9v3n6uEwYqfE7Hqh8fH3u9q4j1S7EJqGdS9QJr0A3z+JtqH7QG6WQ=="
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>

<style>
/* Optional: cleaner PDF page breaks if users print */
#md-content h1, #md-content h2 { page-break-after: avoid; }
#md-content img { page-break-inside: avoid; max-width: 100%; }
@media print { nav, header, footer { display:none !important; } }
</style>
