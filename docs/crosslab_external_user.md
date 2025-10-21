---
layout: default
title: CCI help and documentation page
permalink: /docs/crosslab_external_user/
---

<div style="display:flex;gap:.5rem;align-items:center;margin:.5rem 0 1rem;">
  <a id="pdf-link" class="button" href="#" style="display:none;">Download PDF</a>
  <button id="pdf-btn" style="display:none;">Generate PDF</button>
  <span id="pdf-status" style="font-size:.9rem;color:#666;"></span>
</div>

<div id="md-content"><em>Loading…</em></div>

<script>
// CONFIG  
const mdUrl = 'https://raw.githubusercontent.com/CCI-GU-Sweden/CCI_registration_documents/refs/heads/main/Crosslab%20manual%20external%20user.md';
const pdfBaseName = 'Crosslab manual external user';

// Prefer prebuilt PDF from CCI_registration_documents; fall back to "raw" if Pages isn't enabled
const prebuiltPdf = `https://cci-gu-sweden.github.io/CCI_registration_documents/assets/pdfs/${encodeURIComponent(pdfBaseName)}.pdf`;
const rawPdf      = `https://raw.githubusercontent.com/CCI-GU-Sweden/CCI_registration_documents/refs/heads/main/assets/pdfs/${encodeURIComponent(pdfBaseName)}.pdf`;

// Simple, robust resolvers for relative URLs in Markdown
function resolveMarkdownImages(md, base) {
  // 1) Markdown syntax: ![alt](url)
  md = md.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, url) => {
    url = url.trim();
    if (/^(?:https?:)?\/\//i.test(url) || url.startsWith('/')) return m; // already absolute
    const abs = new URL(url, base).href;
    return `![${alt}](${abs})`;
  });
  // 2) HTML <img src="url">
  md = md.replace(/<img\s+([^>]*?)src=["']([^"']+)["']([^>]*)>/gi, (m, pre, url, post) => {
    url = url.trim();
    if (/^(?:https?:)?\/\//i.test(url) || url.startsWith('/')) return m;
    const abs = new URL(url, base).href;
    return `<img ${pre}src="${abs}"${post}>`;
  });
  return md;
}

async function renderMarkdownPage() {
  const base = mdUrl.slice(0, mdUrl.lastIndexOf('/') + 1);
  const r = await fetch(mdUrl, { cache: 'no-store' });
  let md = await r.text();
  md = resolveMarkdownImages(md, base);

  document.getElementById('md-content').innerHTML = `<md>${md}</md>`;
  if (window.renderMarkdown) renderMarkdown();

  // external links open in a new tab (optional)
  document.querySelectorAll('#md-content a[href]').forEach(a => {
    const u = new URL(a.getAttribute('href'), location.href);
    if (u.origin !== location.origin) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  });
}

async function setupPdfButton() {
  const link = document.getElementById('pdf-link');
  const btn  = document.getElementById('pdf-btn');
  const status = document.getElementById('pdf-status');

  // Try prebuilt PDFs first
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

  // Fall back to client-side generation
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
      console.warn(e);
      status.textContent = 'PDF failed — try your browser’s “Print to PDF”.';
    }
  });
}

// Boot
renderMarkdownPage().then(setupPdfButton).catch(console.error);
</script>

<!-- Markdown renderer -->
<script src="https://cdn.jsdelivr.net/gh/MarketingPipeline/Markdown-Tag/markdown-tag.js"></script>
<!-- Client-side PDF (no SRI; prevents the integrity error you saw) -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"
        crossorigin="anonymous" referrerpolicy="no-referrer"></script>
