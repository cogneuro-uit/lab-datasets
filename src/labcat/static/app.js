// Small helpers used on every page: theme toggle, flash messages, copy buttons, confirm dialogs.
(() => {
  const root = document.documentElement;

  // Theme: toggles between light and dark; remembers the choice.
  const effective = () =>
    root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const next = effective() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  });

  // Flash message: auto-hide after a few seconds.
  const flash = document.querySelector("[data-flash]");
  if (flash) {
    const hide = () => { flash.classList.add("hide"); setTimeout(() => flash.remove(), 300); };
    flash.querySelector("[data-dismiss]")?.addEventListener("click", hide);
    setTimeout(hide, 6000);
  }

  // Toast for small confirmations (e.g. "Copied").
  window.toast = (msg) => {
    const t = document.createElement("div");
    t.className = "flash";
    t.setAttribute("role", "status");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.classList.add("hide"); setTimeout(() => t.remove(), 300); }, 1800);
  };

  // Copy-to-clipboard buttons.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const text = btn.dataset.copy;
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    window.toast("Copied to clipboard");
  });

  // Close open <details class="menu"> when clicking elsewhere.
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });

  // File drop zone (YAML import).
  document.querySelectorAll("[data-dropzone]").forEach((zone) => {
    const input = zone.querySelector("input[type=file]");
    const name = zone.querySelector("[data-file-name]");
    const text = document.getElementById(zone.dataset.dropzone);
    input.addEventListener("change", async () => {
      const file = input.files[0];
      name.textContent = file?.name || "";
      if (file && text) {
        // Show the file's content in the text box, so it can be checked and corrected there.
        text.value = await file.text();
        input.value = "";
        text.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag");
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // Forms with data-confirm ask first, in a styled dialog.
  const confirmDialog = (message) => new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "dialog";
    d.innerHTML = `<form method="dialog" class="dialog-form"><h2>Are you sure?</h2><p></p>
      <div class="dialog-actions"><button class="btn btn-ghost" value="no">Cancel</button>
      <button class="btn btn-primary" value="yes">Yes, continue</button></div></form>`;
    d.querySelector("p").textContent = message;
    document.body.appendChild(d);
    d.addEventListener("close", () => { resolve(d.returnValue === "yes"); d.remove(); });
    d.showModal();
  });
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.dataset.confirm || form.dataset.confirmed) return;
    e.preventDefault();
    if (await confirmDialog(form.dataset.confirm)) {
      form.dataset.confirmed = "1";
      form.submit();
    }
  });
})();
