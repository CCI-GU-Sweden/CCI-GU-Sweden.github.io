---
layout: default
title: CCI User Registration Workflow
permalink: /user-registration-workflow/
---

<div style="margin:.75rem 0;">
  <label for="version-select"><strong>Version:</strong></label>
  <select id="version-select" style="margin-left:.5rem;"></select>
</div>

<iframe id="workflow-frame"
        src="https://cci-gu-sweden.github.io/CCI_user-registration-workflow/latest/"
        style="width:100%;height:75vh;border:1px solid #ddd;border-radius:8px;"
        loading="lazy"></iframe>

<script>
(async function () {
  const repo = 'CCI-GU-Sweden/CCI_user-registration-workflow';
  const base = 'https://cci-gu-sweden.github.io/CCI_user-registration-workflow';
  const select = document.getElementById('version-select');
  const frame  = document.getElementById('workflow-frame');

  // CalVer sorter: YYYY.M.D(.N)
  function key(t) {
    const parts = (t.name || '').split('.').map(p => parseInt(p, 10) || 0);
    const y = parts[0] || 0;
    const m = parts[1] || 0;
    const d = parts[2] || 0;
    const n = parts[3] || 0;
    return { y, m, d, n };
  }
  
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/tags`, {
      headers: { 'Accept': 'application/vnd.github+json' }, cache: 'no-store'
    });
    const tags = await r.json();
    tags.sort((a,b)=>{const A=key(a),B=key(b);return B.y-A.y||B.m-A.m||B.d-A.d||B.n-A.n;});
    for (const t of tags) {
      const o = document.createElement('option');
      o.value = `${base}/versions/${t.name}/`;
      o.textContent = t.name;
      select.appendChild(o);
    }
	if (tags.length) {
      select.value = `${base}/versions/${tags[0].name}/`;
      frame.src = select.value;
    }
    select.addEventListener('change', e => {
      document.getElementById('workflow-frame').src = e.target.value;
    });
  } catch (e) {
    console.warn('Could not load tags; falling back to latest.', e);
  }
})();
</script>
