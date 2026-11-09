// Catalog page: instant search (MiniSearch), facet filters, card / table view.
// All state lives in the URL, so filtered views can be bookmarked and shared.
(() => {
  const data = JSON.parse(document.getElementById("catalog-data").textContent);
  const meta = JSON.parse(document.getElementById("catalog-meta").textContent);
  const byId = new Map(data.map((d) => [d.id, d]));
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const icon = (n) => `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#i-${n}"/></svg>`;
  const LOC_ICONS = { teams: "users", server: "server", osf: "globe", zenodo: "archive", openneuro: "brain", figshare: "layers", other: "link" };

  // ---- search index ----
  const mini = new MiniSearch({
    fields: ["title", "summary", "tagsText", "paradigm", "population", "modalityLabels", "people", "id", "channel"],
    extractField: (doc, f) => (f === "tagsText" ? doc.tags.join(" ") : doc[f]),
    searchOptions: { boost: { title: 3, tagsText: 2, id: 2, modalityLabels: 2 }, prefix: true, fuzzy: 0.2, combineWith: "AND" },
  });
  mini.addAll(data);

  // ---- facets ----
  const FACETS = [
    { key: "status", title: "Status", values: (d) => [d.status], label: (v) => meta.statuses[v] || v, order: Object.keys(meta.statuses) },
    { key: "modality", title: "Modality", values: (d) => d.modalities, label: (v) => meta.modalities[v] || v },
    { key: "tag", title: "Tags", values: (d) => d.tags, label: (v) => "#" + v, limit: 8 },
    { key: "year", title: "Year", values: (d) => [String(d.year)], label: (v) => v, sortDesc: true, limit: 6 },
    { key: "sharing", title: "Sharing", values: (d) => [d.sharing || "none"], label: (v) => meta.sharing[v] || "Not set", order: [...Object.keys(meta.sharing), "none"] },
    { key: "person", title: "People", values: (d) => d.peopleIds, label: (v) => meta.people[v] || v, limit: 6 },
  ];

  const state = { q: "", filters: {}, retired: false, sort: "updated", view: "cards", expanded: new Set() };
  FACETS.forEach((f) => (state.filters[f.key] = new Set()));

  // ---- URL state ----
  function readURL() {
    const p = new URLSearchParams(location.search);
    state.q = p.get("q") || "";
    FACETS.forEach((f) => (state.filters[f.key] = new Set((p.get(f.key) || "").split(",").filter(Boolean))));
    state.retired = p.get("retired") === "1";
    state.sort = p.get("sort") || "updated";
    let saved = null;
    try { saved = localStorage.getItem("catalog-view"); } catch (e) {}
    state.view = p.get("view") || saved || (innerWidth < 700 ? "cards" : "cards");
  }
  function writeURL() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    FACETS.forEach((f) => state.filters[f.key].size && p.set(f.key, [...state.filters[f.key]].join(",")));
    if (state.retired) p.set("retired", "1");
    if (state.sort !== "updated") p.set("sort", state.sort);
    const qs = p.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  // ---- filtering ----
  function searchHits() {
    if (!state.q.trim()) return { ids: data.map((d) => d.id), terms: [] };
    const res = mini.search(state.q);
    return { ids: res.map((r) => r.id), terms: [...new Set(res.flatMap((r) => r.terms))] };
  }
  function passes(d, exceptKey) {
    const showRetired = state.retired || state.filters.status.has("retired");
    if (d.status === "retired" && !showRetired) return false;
    return FACETS.every((f) => {
      if (f.key === exceptKey) return true;
      const sel = state.filters[f.key];
      return !sel.size || f.values(d).some((v) => sel.has(v));
    });
  }

  // ---- rendering ----
  function highlight(text, terms) {
    let out = esc(text);
    if (!terms.length) return out;
    const re = new RegExp("\\b(" + terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
    return out.replace(re, "<mark>$1</mark>");
  }
  const plainSummary = (s) => s.replace(/[*_`#>\[\]]/g, "").replace(/\(https?:[^)]+\)/g, "");
  const badge = (s) => `<span class="badge status-${s}"><span class="dot"></span>${esc(meta.statuses[s])}</span>`;
  const meter = (score) => `<span class="meter ${score < 50 ? "low" : ""}" title="${score}% complete"><span style="width:${score}%"></span></span>`;

  function card(d, terms) {
    const chips = [
      ...d.modalities.map((m) => `<span class="chip chip-mod">${esc(meta.modalities[m] || m)}</span>`),
      ...d.tags.slice(0, 4).map((t) => `<span class="chip">#${highlight(t, terms)}</span>`),
    ].join("");
    const locs = d.locations.map((k) => `<span title="${esc(meta.locationKinds[k])}">${icon(LOC_ICONS[k] || "link")}</span>`).join("");
    return `<a class="ds-card status-${d.status}" href="/d/${encodeURIComponent(d.id)}">
      <div class="top"><span>${esc(d.year)}</span>·<span>${esc(d.contactName)}</span>${badge(d.status)}</div>
      <h3>${highlight(d.title, terms)}</h3>
      ${d.summary ? `<p class="summary">${highlight(plainSummary(d.summary), terms)}</p>` : ""}
      ${chips ? `<div class="chips">${chips}</div>` : ""}
      <div class="foot">
        <span class="loc-icons">${locs || `<span class="small">no location yet</span>`}</span>
        ${d.n != null ? `<span>${icon("users")} ${d.n}</span>` : ""}
        ${d.outputs ? `<span>${icon("book-open")} ${d.outputs}</span>` : ""}
        ${d.todos ? `<span class="todo-badge" title="${d.todos} open to-do${d.todos > 1 ? "s" : ""}">${icon("circle-check")} ${d.todos}</span>` : ""}
        ${meter(d.score)}
      </div></a>`;
  }

  function table(rows, terms) {
    return `<div class="table-wrap"><table class="ds-table"><thead><tr>
      <th>Title</th><th>Status</th><th>Year</th><th>Contact</th><th>Modalities</th><th>N</th><th>Sharing</th><th>Complete</th>
      </tr></thead><tbody>${rows.map((d) => `<tr data-href="/d/${encodeURIComponent(d.id)}">
        <td class="t-title"><a href="/d/${encodeURIComponent(d.id)}">${highlight(d.title, terms)}</a><div class="small muted mono">${esc(d.id)}${d.todos ? ` · <span class="todo-badge">${d.todos} to-do${d.todos > 1 ? "s" : ""}</span>` : ""}</div></td>
        <td>${badge(d.status)}</td><td>${esc(d.year)}</td><td><a class="person-link" href="/people/${encodeURIComponent(d.contact)}">${esc(d.contactName)}</a></td>
        <td>${d.modalities.map((m) => esc(meta.modalities[m] || m)).join(", ")}</td>
        <td>${d.n ?? ""}</td><td>${esc(meta.sharing[d.sharing] || "")}</td><td>${meter(d.score)}</td></tr>`).join("")}
      </tbody></table></div>`;
  }

  function renderFacets(hitSet) {
    const groups = FACETS.map((f) => {
      const counts = new Map();
      data.forEach((d) => {
        if (!hitSet.has(d.id) || !passes(d, f.key)) return;
        f.values(d).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
      });
      state.filters[f.key].forEach((v) => counts.has(v) || counts.set(v, 0));
      let vals = [...counts.keys()];
      if (f.order) vals.sort((a, b) => f.order.indexOf(a) - f.order.indexOf(b));
      else if (f.sortDesc) vals.sort((a, b) => b.localeCompare(a));
      else vals.sort((a, b) => counts.get(b) - counts.get(a) || f.label(a).localeCompare(f.label(b)));
      if (!vals.length) return "";
      const expanded = state.expanded.has(f.key);
      const shown = f.limit && !expanded ? vals.filter((v, i) => i < f.limit || state.filters[f.key].has(v)) : vals;
      const opts = shown.map((v) => `<label class="facet-opt ${counts.get(v) ? "" : "zero"}">
          <input type="checkbox" data-facet="${f.key}" value="${esc(v)}" ${state.filters[f.key].has(v) ? "checked" : ""}>
          <span>${esc(f.label(v))}</span><span class="n">${counts.get(v)}</span></label>`).join("");
      const more = f.limit && vals.length > f.limit
        ? `<button type="button" class="link-btn facet-more" data-expand="${f.key}">${expanded ? "Show fewer" : `Show all ${vals.length}`}</button>` : "";
      return `<div class="facet"><h3>${f.title}</h3>${opts}${more}</div>`;
    });
    $("facet-groups").innerHTML = groups.join("");
  }

  function renderActive() {
    const chips = [];
    FACETS.forEach((f) => state.filters[f.key].forEach((v) =>
      chips.push(`<button type="button" data-unfilter="${f.key}" data-value="${esc(v)}">${esc(f.title)}: ${esc(f.label(v))} ${icon("x")}</button>`)));
    $("active-filters").innerHTML = chips.join("");
    const n = chips.length;
    $("clear-filters").hidden = !n;
    $("filter-count").hidden = !n;
    $("filter-count").textContent = n;
  }

  function sortRows(rows, hitOrder) {
    if (state.q.trim() && state.sort === "updated") return rows.sort((a, b) => hitOrder.get(a.id) - hitOrder.get(b.id));
    const cmp = {
      updated: (a, b) => (b.updated || "").localeCompare(a.updated || ""),
      year: (a, b) => b.year - a.year || a.title.localeCompare(b.title),
      title: (a, b) => a.title.localeCompare(b.title),
    }[state.sort];
    return rows.sort(cmp);
  }

  function render() {
    const { ids, terms } = searchHits();
    const hitSet = new Set(ids);
    const hitOrder = new Map(ids.map((id, i) => [id, i]));
    const rows = sortRows(ids.map((id) => byId.get(id)).filter((d) => passes(d)), hitOrder);
    const results = $("results");
    results.className = state.view === "cards" ? "cards" : "";
    results.innerHTML = state.view === "cards" ? rows.map((d) => card(d, terms)).join("") : rows.length ? table(rows, terms) : "";
    $("no-results").hidden = rows.length > 0;
    const total = data.filter((d) => d.status !== "retired" || state.retired).length;
    $("count").textContent = rows.length === total ? `${total} dataset${total === 1 ? "" : "s"}` : `${rows.length} of ${total} datasets`;
    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
    renderFacets(hitSet);
    renderActive();
    writeURL();
  }

  // ---- events ----
  readURL();
  const q = $("q");
  q.value = state.q;
  $("sort").value = state.sort;
  $("show-retired").checked = state.retired;
  q.addEventListener("input", () => { state.q = q.value; render(); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { q.value = ""; state.q = ""; render(); }
    if (e.key === "Enter") { const first = document.querySelector("#results a"); if (first) location.href = first.href; }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); q.focus(); }
  });
  $("sort").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
  $("show-retired").addEventListener("change", (e) => { state.retired = e.target.checked; render(); });
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view;
    try { localStorage.setItem("catalog-view", state.view); } catch (e) {}
    render();
  }));
  $("facets").addEventListener("change", (e) => {
    const cb = e.target.closest("[data-facet]");
    if (!cb) return;
    const set = state.filters[cb.dataset.facet];
    cb.checked ? set.add(cb.value) : set.delete(cb.value);
    render();
  });
  $("facets").addEventListener("click", (e) => {
    const b = e.target.closest("[data-expand]");
    if (!b) return;
    const k = b.dataset.expand;
    state.expanded.has(k) ? state.expanded.delete(k) : state.expanded.add(k);
    render();
  });
  $("active-filters").addEventListener("click", (e) => {
    const b = e.target.closest("[data-unfilter]");
    if (!b) return;
    state.filters[b.dataset.unfilter].delete(b.dataset.value);
    render();
  });
  const clearAll = () => { FACETS.forEach((f) => state.filters[f.key].clear()); render(); };
  $("clear-filters").addEventListener("click", clearAll);
  $("reset-all").addEventListener("click", () => { q.value = ""; state.q = ""; clearAll(); });
  $("results").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a")) location.href = tr.dataset.href;
  });
  // Filters drawer on small screens.
  const facets = $("facets");
  const openFacets = (open) => { facets.classList.toggle("open", open); document.body.classList.toggle("facets-shown", open); };
  $("facets-open").addEventListener("click", () => openFacets(true));
  $("facets-close").addEventListener("click", () => openFacets(false));
  document.addEventListener("click", (e) => {
    if (document.body.classList.contains("facets-shown") && !facets.contains(e.target) && !e.target.closest("#facets-open")) openFacets(false);
  });

  render();
})();
