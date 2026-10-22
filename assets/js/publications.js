const PAGE_SIZE = 20;
const SORTS = new Set(["newest", "oldest", "title"]);
const INVOLVEMENT_LABELS = new Map([
  ["scientific-collaboration", "Scientific Collaboration"],
  ["service-provision", "Service Provision"],
]);

export function normalizeSearch(value) {
  return String(value ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

export function selectPublications(records, {query = "", year = "", sort = "newest", technologies = [], involvement = ""} = {}, labels = new Map()) {
  const terms = normalizeSearch(query).trim().split(/\s+/).filter(Boolean);
  return records.filter(record => {
    if (year && String(record.year) !== String(year)) return false;
    if (involvement && record.cci_involvement !== involvement) return false;
    const tags = record.technologies || [];
    if (technologies.length && !technologies.some(tag => tags.includes(tag))) return false;
    const text = normalizeSearch([record.title, record.authors_text, ...(record.authors || []),
      record.journal, record.doi, ...tags.map(tag => labels.get(tag) || tag)].join(" "));
    return terms.every(term => text.includes(term));
  }).sort((a, b) => {
    const titleOrder = a.title.localeCompare(b.title, "en", {sensitivity: "base"});
    if (sort === "title") return titleOrder || a.id.localeCompare(b.id);
    const years = sort === "oldest" ? a.year - b.year : b.year - a.year;
    return years || titleOrder || a.id.localeCompare(b.id);
  });
}

export function publicationURL(record) {
  if (record.doi) return `https://doi.org/${encodeURI(record.doi).replace(/[?#]/g, char => encodeURIComponent(char))}`;
  return externalURL(record.publication_url);
}

function externalURL(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function publicationCard(record, labels) {
  const item = element("li");
  const article = element("article", "publication-card");
  const meta = element("div", "publication-meta");
  meta.append(element("span", "publication-year", record.year));
  if (record.journal) meta.append(element("span", "publication-journal", record.journal));
  const type = {"posted-content": "Preprint", "book-chapter": "Book chapter"}[record.type];
  if (type) meta.append(element("span", "publication-type", type));
  if (INVOLVEMENT_LABELS.has(record.cci_involvement)) {
    const badge = element("span", "publication-involvement");
    badge.dataset.involvement = record.cci_involvement;
    badge.append(element("span", "publications-sr-only", "CCI involvement: "),
      document.createTextNode(INVOLVEMENT_LABELS.get(record.cci_involvement)));
    meta.append(badge);
  }
  const title = element("h2");
  const url = publicationURL(record);
  if (url) {
    const link = element("a", "", record.title);
    link.href = url;
    title.append(link);
  } else title.textContent = record.title;
  article.append(meta, title);
  const authors = record.authors || [];
  const preview = authors.length > 5 ? `${authors.slice(0, 5).join("; ")}; et al.` : record.authors_text || authors.join("; ");
  article.append(element("p", "publication-authors", preview));
  const disclosures = element("div", "publication-disclosures");
  const controls = element("div", "publication-disclosure-controls");
  const panels = element("div", "publication-disclosure-panels");
  function addDisclosure(key, label, content) {
    const button = element("button", "publication-disclosure-toggle");
    button.type = "button";
    button.id = `${record.id}-${key}-toggle`;
    button.dataset.disclosure = key;
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", `${record.id}-${key}-panel`);
    const arrow = element("span", "publication-disclosure-arrow", "▸");
    arrow.setAttribute("aria-hidden", "true");
    button.append(arrow, document.createTextNode(label));
    content.id = `${record.id}-${key}-panel`;
    content.setAttribute("role", "region");
    content.setAttribute("aria-labelledby", button.id);
    content.hidden = true;
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      content.hidden = !open;
    });
    controls.append(button);
    panels.append(content);
  }
  if (authors.length > 5) {
    const content = element("div");
    content.append(element("p", "publication-authors", authors.join("; ")));
    addDisclosure("authors", `All ${authors.length} authors`, content);
  }
  if (typeof record.abstract?.text === "string" && record.abstract.text.trim()) {
    const content = element("div", "publication-abstract-text");
    for (const paragraph of record.abstract.text.split(/\n\s*\n/).filter(text => text.trim())) {
      content.append(element("p", "", paragraph.trim()));
    }
    const attribution = element("p", "publication-abstract-source");
    for (const [label, value] of [["Abstract source", record.abstract.source_url], ["Reuse licence", record.abstract.license_url]]) {
      const href = externalURL(value);
      if (!href) continue;
      if (attribution.childNodes.length) attribution.append(document.createTextNode(" · "));
      const link = element("a", "", label);
      link.href = href;
      attribution.append(link);
    }
    if (attribution.childNodes.length) content.append(attribution);
    addDisclosure("abstract", "Abstract", content);
  }
  if (controls.childNodes.length) {
    disclosures.append(controls, panels);
    article.append(disclosures);
  }
  if (url) {
    const reference = element("div", "publication-doi");
    const link = element("a", "", record.doi ? `DOI: ${record.doi}` : "View publication");
    link.href = url;
    reference.append(link);
    article.append(reference);
  }
  if (record.technologies?.length) {
    const tags = element("div", "publication-tags");
    for (const tag of record.technologies) tags.append(element("span", "publication-tag", labels.get(tag) || tag.replaceAll("_", " ")));
    article.append(tags);
  }
  item.append(article);
  return item;
}

export async function initializePublications(root) {
  const form = root.querySelector("form");
  const fieldset = form.querySelector("fieldset");
  const search = root.querySelector("[name=q]");
  const year = root.querySelector("[name=year]");
  const sort = root.querySelector("[name=sort]");
  const involvement = root.querySelector("[name=cci_involvement]");
  const technologyPicker = root.querySelector("[data-technology-picker]");
  const technologySummary = technologyPicker.querySelector("summary");
  const technologyValue = root.querySelector("[data-technology-value]");
  const clearTechnologies = root.querySelector("[data-clear-technologies]");
  const clear = root.querySelector("[data-clear]");
  const status = root.querySelector("[data-status]");
  const results = root.querySelector("#publication-results");
  const more = root.querySelector("[data-more]");
  const empty = root.querySelector("[data-empty]");
  const retry = root.querySelector("[data-retry]");
  let records = [];
  let labels = new Map();
  let limit = PAGE_SIZE;
  let technologyInputs = [];

  function state() {
    return {query: search.value, year: year.value, sort: sort.value, involvement: involvement.value,
      technologies: technologyInputs.filter(input => input.checked).map(input => input.value)};
  }

  function restoreURL() {
    const params = new URLSearchParams(window.location.search);
    search.value = params.get("q") || "";
    year.value = params.get("year") || "";
    if (year.selectedIndex < 0) year.value = "";
    sort.value = SORTS.has(params.get("sort")) ? params.get("sort") : "newest";
    involvement.value = INVOLVEMENT_LABELS.has(params.get("involvement")) ? params.get("involvement") : "";
    for (const input of technologyInputs) input.checked = params.getAll("technology").includes(input.value);
  }

  function render(updateURL = true) {
    const filters = state();
    technologyValue.textContent = filters.technologies.length === 1 ? labels.get(filters.technologies[0]) || filters.technologies[0]
      : filters.technologies.length ? `${filters.technologies.length} technologies selected` : "All technologies";
    clearTechnologies.disabled = filters.technologies.length === 0;
    const matches = selectPublications(records, filters, labels);
    const visible = matches.slice(0, limit);
    results.replaceChildren(...visible.map(record => publicationCard(record, labels)));
    status.textContent = matches.length ? `Showing ${visible.length} of ${matches.length} publication${matches.length === 1 ? "" : "s"}${matches.length !== records.length ? ` (${records.length} total)` : ""}` : "0 publications found";
    empty.hidden = matches.length !== 0;
    more.hidden = visible.length >= matches.length;
    more.textContent = `Show ${Math.min(PAGE_SIZE, matches.length - visible.length)} more publications`;
    clear.disabled = !filters.query && !filters.year && !filters.involvement && !filters.technologies.length && filters.sort === "newest";
    results.setAttribute("aria-busy", "false");
    if (updateURL) {
      const url = new URL(window.location.href);
      for (const key of ["q", "year", "sort", "technology", "involvement"]) url.searchParams.delete(key);
      if (filters.query) url.searchParams.set("q", filters.query);
      if (filters.year) url.searchParams.set("year", filters.year);
      if (filters.sort !== "newest") url.searchParams.set("sort", filters.sort);
      if (filters.involvement) url.searchParams.set("involvement", filters.involvement);
      for (const tag of filters.technologies) url.searchParams.append("technology", tag);
      window.history.replaceState(null, "", url);
    }
  }

  async function load() {
    retry.hidden = true;
    fieldset.disabled = true;
    status.textContent = "Loading publications…";
    results.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(root.dataset.catalogueUrl, {cache: "no-store"});
      if (!response.ok) throw new Error(`Catalogue HTTP ${response.status}`);
      const catalogue = await response.json();
      if (catalogue.schema_version !== 1 || !Array.isArray(catalogue.publications)) throw new Error("Unsupported catalogue");
      records = catalogue.publications;
      if (records.some(record => typeof record.title !== "string" || typeof record.id !== "string" || !Number.isInteger(record.year))) throw new Error("Invalid catalogue record");
      labels = new Map((catalogue.vocabulary?.technologies || []).map(tag => [tag.id, tag.label]));
      year.replaceChildren(element("option", "", "All years"));
      year.firstChild.value = "";
      for (const value of [...new Set(records.map(record => record.year))].sort((a, b) => b - a)) {
        const option = element("option", "", value);
        option.value = value;
        year.append(option);
      }
      const options = root.querySelector("[data-technology-options]");
      options.replaceChildren();
      const tags = [...new Set(records.flatMap(record => record.technologies || []))].sort();
      technologyInputs = tags.map(tag => {
        const label = element("label");
        const input = element("input");
        input.type = "checkbox";
        input.name = "technology";
        input.value = tag;
        input.setAttribute("aria-controls", "publication-results");
        label.append(input, document.createTextNode(labels.get(tag) || tag.replaceAll("_", " ")));
        options.append(label);
        return input;
      });
      root.querySelector("[data-no-technologies]").hidden = tags.length > 0;
      restoreURL();
      fieldset.disabled = false;
      render(false);
    } catch (error) {
      status.textContent = "We couldn’t load the publications. Please try again.";
      results.setAttribute("aria-busy", "false");
      retry.hidden = false;
      console.error("Publication catalogue could not be loaded", error);
    }
  }

  form.addEventListener("submit", event => event.preventDefault());
  form.addEventListener("input", event => {
    if (event.target === search) { limit = PAGE_SIZE; render(); }
  });
  form.addEventListener("change", event => {
    if (event.target !== search) { limit = PAGE_SIZE; render(); }
  });
  clear.addEventListener("click", () => {
    search.value = ""; year.value = ""; sort.value = "newest";
    involvement.value = "";
    technologyInputs.forEach(input => { input.checked = false; });
    technologyPicker.open = false;
    limit = PAGE_SIZE;
    render();
    search.focus();
  });
  more.addEventListener("click", () => {
    const previousCount = results.children.length;
    limit += PAGE_SIZE;
    render();
    results.children[previousCount]?.querySelector("h2 a")?.focus();
  });
  retry.addEventListener("click", load);
  clearTechnologies.addEventListener("click", () => {
    technologyInputs.forEach(input => { input.checked = false; });
    limit = PAGE_SIZE;
    render();
  });
  technologyPicker.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      technologyPicker.open = false;
      technologySummary.focus();
    }
  });
  document.addEventListener("pointerdown", event => {
    if (!technologyPicker.contains(event.target)) technologyPicker.open = false;
  });
  window.addEventListener("popstate", () => { restoreURL(); limit = PAGE_SIZE; render(false); });
  await load();
}

if (typeof document !== "undefined") {
  const root = document.querySelector("[data-publications]");
  if (root) initializePublications(root);
}
