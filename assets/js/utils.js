
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

async function renderMarkdownPage(mdUrl) {
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

async function setupPdfButtonPrebuilt(pdfBaseName,prebuiltPdf, rawPdf) {
  
  const link = document.getElementById('pdf-link');
  // Try prebuilt PDFs first
  for (const href of [prebuiltPdf, rawPdf]) {
    if (!href || !href.trim()) continue;
    try {
      const head = await fetch(href, { method: 'HEAD', cache: 'no-store' });
      if (head.ok) {
        link.href = href;
        link.download = `${pdfBaseName}.pdf`;
        link.style.display = '';
        return true;
      }
    } catch {}
  }
  return false;
}

async function setupPdfButtonGenerate(pdfBaseName) {
  const btn  = document.getElementById('pdf-btn');
  const status = document.getElementById('pdf-status');

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

async function setupPdfButton(pdfBaseName, prebuiltPdf = "", rawPdf = "") {
    const gotPrebuilt = await setupPdfButtonPrebuilt(pdfBaseName, prebuiltPdf, rawPdf);
    if (!gotPrebuilt) {
        await setupPdfButtonGenerate(pdfBaseName);
    }
}