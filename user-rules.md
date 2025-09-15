---
layout: page
title: CCI User Rules
permalink: /user-rules/
---

<div style="margin:.75rem 0;">
  <label for="version-select"><strong>Version:</strong></label>
  <select id="version-select" style="margin-left:.5rem;"></select>
</div>

<iframe id="rules-frame"
        src="https://cci-gu-sweden.github.io/cci-user-rules/latest/"
        style="width:100%;height:75vh;border:1px solid #ddd;border-radius:8px;"
        loading="lazy"></iframe>

<script>
(async function () {
  const repo = 'CCI-GU-Sweden/cci-user-rules';
  const base = 'https://cci-gu-sweden.github.io/cci-user-rules';
  const select = document.getElementById('version-select');
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/tags`, {
      headers: { 'Accept': 'application/vnd.github+json' }, cache: 'no-store'
    });
    const tags = await r.json();               // [{name: "v1.2.3"}, ...]
    // sort semver desc
    tags.sort((a,b) => b.name.localeCompare(a.name, undefined, {numeric:true, sensitivity:'base'}));
    for (const t of tags) {
      const o = document.createElement('option');
      o.value = `${base}/versions/${t.name}/`;
      o.textContent = t.name;
      select.appendChild(o);
    }
    select.addEventListener('change', e => {
      document.getElementById('rules-frame').src = e.target.value;
    });
  } catch (e) {
    console.warn('Could not load tags; falling back to latest.', e);
  }
})();
</script>
