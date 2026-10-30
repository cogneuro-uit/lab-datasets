// Dataset form: wizard steps, chip pickers, repeatable rows, DOI fill-in, ID suggestion, add-person dialog.
(() => {
  const form = document.getElementById("dsform");
  if (!form) return;
  const mode = form.dataset.mode;
  const icon = (n) => `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#i-${n}"/></svg>`;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  let dirty = false;
  const markDirty = () => {
    dirty = true;
    const u = form.querySelector("[data-unsaved]");
    if (u) u.hidden = false;
  };

  // ------------------------------------------------------------------ pickers
  function initPicker(el) {
    const name = el.dataset.name;
    const allowNew = el.hasAttribute("data-allow-new");
    let options = JSON.parse(el.dataset.options || "[]");
    const box = el.querySelector(".picker-box");
    const input = el.querySelector(".picker-input");
    const menu = el.querySelector(".picker-menu");
    let active = 0;
    let items = [];
    const selected = () => [...el.querySelectorAll('input[type="hidden"]')].map((i) => i.value);
    const labelOf = (v) => (options.find((o) => o[0] === v) || [v, v])[1];

    function add(value) {
      value = value.trim();
      if (!value || selected().includes(value)) return;
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.dataset.value = value;
      chip.innerHTML = `${esc(labelOf(value))}<button type="button" aria-label="Remove" data-remove>${icon("x")}</button><input type="hidden" name="${esc(name)}" value="${esc(value)}">`;
      box.insertBefore(chip, input);
      input.value = "";
      markDirty();
      update();
    }
    function update() {
      const q = input.value.trim().toLowerCase();
      const sel = selected();
      items = options.filter((o) => !sel.includes(o[0]) && (!q || o[1].toLowerCase().includes(q) || o[0].includes(q))).slice(0, 50);
      const slug = q.replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
      const canCreate = allowNew && slug && !options.some((o) => o[0] === slug) && !sel.includes(slug);
      let html = items.map((o, i) => `<li role="option" data-value="${esc(o[0])}" aria-selected="${i === active}">${esc(o[1])}</li>`).join("");
      if (canCreate) {
        items.push([slug, slug, true]);
        html += `<li role="option" class="new" data-value="${esc(slug)}" aria-selected="${items.length - 1 === active}">${icon("plus")} Create new tag “${esc(slug)}”</li>`;
      }
      if (!items.length) html = `<li class="none">${q ? "No matches" : "Nothing more to add"}</li>`;
      menu.innerHTML = html;
    }
    const open = () => { active = 0; update(); menu.hidden = false; input.setAttribute("aria-expanded", "true"); };
    const close = () => { menu.hidden = true; input.setAttribute("aria-expanded", "false"); };

    box.addEventListener("click", (e) => {
      const rm = e.target.closest("[data-remove]");
      if (rm) { rm.closest(".chip").remove(); markDirty(); update(); return; }
      input.focus();
    });
    input.addEventListener("click", open);
    input.addEventListener("input", () => { active = 0; open(); });
    input.addEventListener("blur", () => setTimeout(close, 150));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (menu.hidden) return open();
        active = Math.min(active + 1, items.length - 1); update();
      }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); update(); }
      else if (e.key === "Enter" || (e.key === "," && allowNew)) {
        e.preventDefault();
        if (!menu.hidden && items[active]) add(items[active][0]);
      } else if (e.key === "Backspace" && !input.value) {
        const chips = el.querySelectorAll(".chip");
        if (chips.length) { chips[chips.length - 1].remove(); markDirty(); update(); }
      } else if (e.key === "Escape") close();
    });
    menu.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-value]");
      if (li) { e.preventDefault(); add(li.dataset.value); }
    });
    el.addOption = (value, label) => { options.push([value, label]); };
    el.addValue = add;
  }
  form.querySelectorAll("[data-picker]").forEach(initPicker);

  // --------------------------------------------------------------- repeaters
  let rowCounter = 1000;
  form.querySelectorAll("[data-repeater]").forEach((rep) => {
    const rows = rep.querySelector("[data-rows]");
    const tpl = rep.querySelector("template[data-row-template]");
    rep.querySelector("[data-add-row]").addEventListener("click", () => {
      const html = tpl.innerHTML.replaceAll("__i__", String(rowCounter++));
      rows.insertAdjacentHTML("beforeend", html);
      const row = rows.lastElementChild;
      initRow(row);
      row.querySelector("input[type=text], input[type=url]")?.focus();
      markDirty();
    });
  });
  form.addEventListener("click", (e) => {
    const rm = e.target.closest("[data-remove-row]");
    if (rm) { rm.closest("[data-row]").remove(); markDirty(); }
  });

  // Location rows: guess the type from what was pasted.
  const guessKind = (t) => {
    t = t.trim().toLowerCase();
    if (/sharepoint\.com|teams\.microsoft|onedrive/.test(t)) return "teams";
    if (/osf\.io/.test(t)) return "osf";
    if (/zenodo\.org/.test(t)) return "zenodo";
    if (/openneuro\.org/.test(t)) return "openneuro";
    if (/figshare\.com/.test(t)) return "figshare";
    if (/^(\/|~|\\\\|[a-z]:\\)/.test(t)) return "server";
    return null;
  };
  function initRow(row) {
    const target = row.querySelector("[data-loc-target]");
    const kind = row.querySelector("[data-loc-kind]");
    if (target && kind) {
      target.addEventListener("input", () => {
        const g = guessKind(target.value);
        if (g && !kind.dataset.touched) kind.value = g;
      });
      kind.addEventListener("change", () => (kind.dataset.touched = "1"));
    }
    if (row.matches("[data-pub]")) initPub(row);
  }

  // DOI lookup for publication rows.
  function initPub(row) {
    const doiInput = row.querySelector("[data-doi]");
    const status = row.querySelector("[data-doi-status]");
    const btn = row.querySelector("[data-doi-lookup]");
    const fill = async () => {
      const q = doiInput.value.trim();
      if (!q) { status.className = "doi-status small bad"; status.textContent = "Paste a DOI first."; return; }
      status.className = "doi-status small";
      status.textContent = "Looking up…";
      btn.disabled = true;
      try {
        const r = await fetch("/api/doi?q=" + encodeURIComponent(q));
        const d = await r.json();
        if (d.doi) doiInput.value = d.doi;
        if (d.error) { status.className = "doi-status small bad"; status.textContent = d.error; return; }
        for (const k of ["title", "authors", "venue", "year", "url"]) {
          const f = row.querySelector(`[data-pub-field="${k}"]`);
          if (f && d[k] != null) f.value = d[k];
        }
        status.className = "doi-status small ok";
        status.textContent = "Filled in from the DOI. Check and correct if needed.";
        markDirty();
      } catch (e) {
        status.className = "doi-status small bad";
        status.textContent = "Lookup failed. You can fill in the details by hand.";
      } finally {
        btn.disabled = false;
      }
    };
    btn.addEventListener("click", fill);
    doiInput.addEventListener("paste", () => setTimeout(() => {
      if (!row.querySelector('[data-pub-field="title"]').value) fill();
    }, 0));
    doiInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fill(); } });
  }
  form.querySelectorAll("[data-row]").forEach(initRow);

  // Clear a radio group ("not decided yet").
  form.querySelectorAll("[data-clear-radio]").forEach((b) => b.addEventListener("click", () => {
    form.querySelectorAll(`input[name="${b.dataset.clearRadio}"]`).forEach((r) => (r.checked = false));
    markDirty();
  }));

  // ------------------------------------------------------------- ID suggestion
  const idInput = form.querySelector("[data-id-input]");
  if (idInput) {
    const title = form.querySelector("[data-title]");
    const year = form.querySelector("[data-year]");
    const stateEl = form.querySelector("[data-id-state]");
    const show = (ok, msg) => { stateEl.className = "id-state small " + (ok ? "ok" : "bad"); stateEl.innerHTML = (ok ? icon("circle-check") : icon("triangle-alert")) + " " + esc(msg); };
    const suggest = debounce(async () => {
      if (idInput.dataset.touched) return;
      const r = await fetch(`/api/suggest-id?title=${encodeURIComponent(title.value)}&year=${encodeURIComponent(year.value)}`);
      const d = await r.json();
      idInput.value = d.id;
      if (d.id) show(true, "Available"); else stateEl.textContent = "";
    }, 250);
    const check = debounce(async () => {
      if (!idInput.value) { stateEl.textContent = ""; return; }
      const d = await (await fetch("/api/check-id?id=" + encodeURIComponent(idInput.value))).json();
      show(d.ok, d.message);
    }, 300);
    title.addEventListener("input", suggest);
    year.addEventListener("input", () => {
      if (idInput.dataset.touched && /^\d{4}-/.test(idInput.value) && /^\d{4}$/.test(year.value)) {
        idInput.value = year.value + idInput.value.slice(4);
        check();
      } else suggest();
    });
    idInput.addEventListener("input", () => {
      idInput.value = idInput.value.toLowerCase().replace(/[^a-z0-9-]/g, "-");
      idInput.dataset.touched = "1";
      check();
    });
    if (idInput.value) check();
  }

  // ------------------------------------------------------------- add person
  const dialog = document.getElementById("person-dialog");
  let personTarget = null;
  form.querySelectorAll("[data-add-person]").forEach((b) => b.addEventListener("click", () => {
    personTarget = b.dataset.addPerson;
    dialog.querySelector("form").reset();
    dialog.querySelector("[data-person-error]").hidden = true;
    dialog.showModal();
  }));
  dialog?.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog?.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const err = dialog.querySelector("[data-person-error]");
    const r = await fetch("/people", { method: "POST", body: fd, headers: { Accept: "application/json" } });
    const d = await r.json();
    if (!r.ok) { err.textContent = Object.values(d.errors || {})[0] || d.error; err.hidden = false; return; }
    const select = form.querySelector("[data-people-select]");
    select.add(new Option(d.name, d.id));
    const picker = form.querySelector('[data-picker][data-name="contributors"]');
    picker?.addOption(d.id, d.name);
    if (personTarget === "contact") select.value = d.id;
    else picker?.addValue(d.id);
    dialog.close();
    window.toast(`${d.name} added`);
  });

  // ------------------------------------------------------------- steps
  const steps = [...form.querySelectorAll("[data-step]")];
  const links = [...form.querySelectorAll("[data-step-link]")];
  const fieldsOf = (step) => [...step.querySelectorAll("input, select, textarea")].filter((f) => f.name && !f.closest("template"));
  const firstInvalid = (step) => fieldsOf(step).find((f) => !f.checkValidity());

  if (mode === "wizard") {
    let current = 0;
    const visited = new Set([0]);
    const prev = form.querySelector("[data-prev]");
    const next = form.querySelector("[data-next]");
    const finish = form.querySelector("[data-finish]");
    const count = form.querySelector("[data-step-count]");

    const go = (i, focus = true) => {
      current = Math.max(0, Math.min(i, steps.length - 1));
      visited.add(current);
      steps.forEach((s, j) => s.classList.toggle("active", j === current));
      links.forEach((l, j) => {
        l.classList.toggle("active", j === current);
        l.classList.toggle("done", j !== current && visited.has(j) && j < current);
        l.toggleAttribute("aria-current", j === current);
      });
      prev.style.visibility = current === 0 ? "hidden" : "visible";
      next.hidden = current === steps.length - 1;
      finish.hidden = current !== steps.length - 1;
      count.textContent = `Step ${current + 1} of ${steps.length}`;
      if (current === steps.length - 1) buildReview();
      links[current]?.scrollIntoView({ block: "nearest", inline: "center" });
      if (focus) {
        window.scrollTo({ top: 0, behavior: "smooth" });
        steps[current].querySelector("input:not([type=hidden]), select, textarea")?.focus({ preventScroll: true });
      }
    };
    const validStep = (i) => {
      const bad = firstInvalid(steps[i]);
      if (bad) { go(i, false); bad.reportValidity(); return false; }
      return true;
    };
    next.addEventListener("click", () => validStep(current) && go(current + 1));
    prev.addEventListener("click", () => go(current - 1));
    links.forEach((l, j) => l.addEventListener("click", (e) => {
      e.preventDefault();
      if (j > current && !validStep(0)) return;  // basics must be valid before skipping ahead
      go(j);
    }));
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("input:not(.picker-input):not([data-doi])")) {
        e.preventDefault();
        if (current < steps.length - 1) next.click();
      }
    });
    const errStep = steps.findIndex((s) => s.querySelector(".has-error, .repeat-row .error"));
    go(errStep >= 0 ? errStep : Math.max(0, steps.findIndex((s) => "#" + s.id === location.hash)), false);
  } else if (links.length) {
    // Edit mode: stepper works as a table of contents that follows scrolling.
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        const i = steps.indexOf(en.target);
        links.forEach((l, j) => l.classList.toggle("active", j === i));
      });
    }, { rootMargin: "-30% 0px -60% 0px" });
    steps.forEach((s) => obs.observe(s));
    steps.forEach((s, i) => links[i].classList.toggle("has-error", !!s.querySelector(".has-error, .repeat-row .error")));
    const target = location.hash && form.querySelector(location.hash);
    if (target) setTimeout(() => target.scrollIntoView({ block: "start" }), 50);
  }

  // Review list in the last wizard step.
  function buildReview() {
    const list = form.querySelector("[data-review-list]");
    if (!list) return;
    const val = (n) => form.querySelector(`[name="${n}"]`)?.value?.trim();
    const any = (sel) => !!form.querySelector(sel);
    const checks = [
      ["Title, contact and status", val("title") && val("contact"), 0],
      ["Summary", val("summary"), 0],
      ["People, Slack channel and collection period", any('[name="contributors"]') || val("slack.channel") || val("collected.start"), 1],
      ["Modalities", any('[name="content.modalities"]:checked'), 2],
      ["Participants, population, paradigm", val("content.n_participants") || val("content.population") || val("content.paradigm"), 2],
      ["Tags", any('[name="content.tags"]'), 2],
      ["At least one storage location", [...form.querySelectorAll("[data-loc-target]")].some((i) => i.value.trim() && !i.closest("template")), 3],
      ["Ethics and sharing", form.querySelector('[name="legal.sharing"]:checked') || val("legal.ethics_ref"), 4],
      ["Papers, preprints or code", [...form.querySelectorAll('[data-pub] [name$=".doi"], [data-pub] [name$=".title"], [name^="outputs.code."]')].some((i) => i.value.trim() && !i.closest("template")), 5],
    ];
    list.innerHTML = checks.map(([label, ok, step]) => `<li>${ok ? icon("circle-check").replace('class="icon"', 'class="icon yes"') : icon("circle-help").replace('class="icon"', 'class="icon no"')}
      <span>${label}</span>${ok ? "" : `<a href="#" data-goto="${step}">add now</a>`}</li>`).join("") +
      `<li class="muted small">Anything missing can be added later from the dataset page.</li>`;
    list.querySelectorAll("[data-goto]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      links[+a.dataset.goto].click();
    }));
  }

  // ------------------------------------------------------------- submit
  form.addEventListener("input", markDirty);
  form.addEventListener("change", markDirty);
  form.addEventListener("submit", (e) => {
    for (const [i, step] of steps.entries()) {
      const bad = firstInvalid(step);
      if (bad) {
        e.preventDefault();
        if (mode === "wizard") links[i]?.click();
        setTimeout(() => { bad.reportValidity(); bad.focus(); }, 50);
        return;
      }
    }
    dirty = false;
    form.querySelectorAll("[type=submit]").forEach((b) => (b.disabled = true));
    // keep the clicked button's state from blocking a resubmit if the page comes back from cache
    setTimeout(() => form.querySelectorAll("[type=submit]").forEach((b) => (b.disabled = false)), 4000);
  });
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
})();
