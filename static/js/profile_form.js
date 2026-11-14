/* Profile form enhancements (progressive: without JS the form still works as plain fields).
   1. Languages: add / remove rows of the Django formset, keeping its management form consistent.
   2. Skills: a tag ("chip") input that writes a comma-separated list back into the original textarea,
      so server-side parsing and validation are unchanged. */
(function () {
  "use strict";

  /* ---------------- 1. Language rows ---------------- */
  function initLanguages() {
    const rows = document.getElementById("lang-rows");
    const tpl = document.getElementById("lang-template");
    const addBtn = document.getElementById("add-lang");
    if (!rows || !tpl || !addBtn) return;

    const prefix = rows.dataset.prefix;
    const max = parseInt(rows.dataset.max, 10) || 10;
    const total = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
    const limitNote = document.getElementById("lang-limit");
    const nameRe = new RegExp(`${prefix}-(\\d+|__prefix__)-`);

    // Rename every row's fields to 0..n-1 so Django sees a gap-free formset.
    function renumber() {
      const all = rows.querySelectorAll(".langrow");
      all.forEach((row, i) => {
        row.querySelectorAll("[name], [id], label[for]").forEach((el) => {
          ["name", "id", "for"].forEach((attr) => {
            const v = el.getAttribute(attr);
            if (v && nameRe.test(v)) el.setAttribute(attr, v.replace(nameRe, `${prefix}-${i}-`));
          });
        });
      });
      total.value = String(all.length);
      const full = all.length >= max;
      addBtn.disabled = full;
      if (limitNote) limitNote.hidden = !full;
      // With a single row, "remove" just clears it.
      all.forEach((row) => {
        const btn = row.querySelector("[data-remove-lang]");
        if (btn) btn.setAttribute("aria-label", all.length === 1 ? "Clear this language" : "Remove this language");
      });
    }

    function addRow(focus) {
      if (rows.querySelectorAll(".langrow").length >= max) return;
      const frag = tpl.content.cloneNode(true);
      rows.appendChild(frag);
      renumber();
      const last = rows.querySelector(".langrow:last-child");
      last.classList.add("row-enter");
      if (focus) last.querySelector("input")?.focus();
    }

    rows.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove-lang]");
      if (!btn) return;
      const row = btn.closest(".langrow");
      if (rows.querySelectorAll(".langrow").length === 1) {
        row.querySelectorAll("input, select").forEach((el) => { el.value = ""; });
        row.querySelectorAll(".err").forEach((el) => el.remove());
        row.querySelector("input")?.focus();
        return;
      }
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove();
      renumber();
      (next?.querySelector("input") || addBtn).focus();
    });

    addBtn.addEventListener("click", () => addRow(true));

    // Show the controls only now that JS is running.
    rows.querySelectorAll("[data-remove-lang]").forEach((b) => { b.hidden = false; });
    addBtn.hidden = false;
    renumber();
  }

  /* ---------------- 2. Chip (tag) inputs ---------------- */
  function splitItems(text) {
    return text.split(/[,;\n]/).map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean);
  }

  // "an interest", "a skill"; "countries", "skills"
  const withArticle = (w) => (/^[aeiou]/i.test(w) ? `an ${w}` : `a ${w}`);
  const plural = (w) => (/[^aeiou]y$/i.test(w) ? `${w.slice(0, -1)}ies` : `${w}s`);

  function initChips(textarea) {
    const noun = textarea.dataset.chips || "item";
    const maxItems = parseInt(textarea.dataset.maxItems, 10) || 30;
    const maxLen = 100;
    let items = [];
    const seen = () => new Set(items.map((s) => s.toLowerCase()));

    const box = document.createElement("div");
    box.className = "chip-input";
    const list = document.createElement("ul");
    list.className = "chip-list";
    list.setAttribute("aria-label", `Added ${plural(noun)}`);
    const entry = document.createElement("input");
    entry.type = "text";
    entry.className = "chip-entry";
    entry.id = `${textarea.id}_entry`;
    entry.autocomplete = "off";
    entry.maxLength = maxLen;
    entry.placeholder = `Type ${withArticle(noun)} and press Enter`;
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn btn-sm";
    add.textContent = "Add";
    const status = document.createElement("div");
    status.className = "sr-only";
    status.setAttribute("aria-live", "polite");
    const note = document.createElement("div");
    note.className = "help chip-note";

    box.append(list, entry, add);
    textarea.insertAdjacentElement("afterend", box);
    box.insertAdjacentElement("afterend", note);
    box.insertAdjacentElement("afterend", status);
    textarea.hidden = true;

    const label = document.querySelector(`label[for="${textarea.id}"]`);
    if (label) label.htmlFor = entry.id; // clicking the label focuses the entry box

    function sync() {
      textarea.value = items.join(", ");
      list.replaceChildren(
        ...items.map((text, i) => {
          const li = document.createElement("li");
          li.className = "chip-tag";
          const span = document.createElement("span");
          span.textContent = text;
          const x = document.createElement("button");
          x.type = "button";
          x.className = "chip-x";
          x.setAttribute("aria-label", `Remove ${text}`);
          x.textContent = "×";
          x.addEventListener("click", () => {
            items.splice(i, 1);
            sync();
            status.textContent = `Removed ${text}.`;
            entry.focus();
          });
          li.append(span, x);
          return li;
        })
      );
      const full = items.length >= maxItems;
      entry.disabled = full;
      add.disabled = full;
      entry.placeholder = full ? `Limit of ${maxItems} reached` : items.length ? `Add another ${noun}` : `Type ${withArticle(noun)} and press Enter`;
      note.textContent = `${items.length} of ${maxItems}`;
    }

    function commit(text) {
      const known = seen();
      const added = [];
      let skipped = 0;
      for (const raw of splitItems(text)) {
        const item = raw.slice(0, maxLen);
        if (items.length >= maxItems) break;
        if (known.has(item.toLowerCase())) { skipped += 1; continue; }
        items.push(item);
        known.add(item.toLowerCase());
        added.push(item);
      }
      entry.value = "";
      sync();
      if (added.length) status.textContent = `Added ${added.join(", ")}.`;
      else if (skipped) status.textContent = "Already added.";
      if (skipped) {
        box.classList.remove("shake");
        void box.offsetWidth; // restart the animation
        box.classList.add("shake");
      }
    }

    entry.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === ",") && entry.value.trim()) {
        e.preventDefault(); // Enter must not submit the whole profile form
        commit(entry.value);
      } else if (e.key === "Enter") {
        e.preventDefault();
      } else if (e.key === "Backspace" && !entry.value && items.length) {
        const removed = items.pop();
        sync();
        status.textContent = `Removed ${removed}.`;
      }
    });
    entry.addEventListener("paste", (e) => {
      const text = (e.clipboardData || window.clipboardData).getData("text");
      if (/[,;\n]/.test(text)) { e.preventDefault(); commit(text); }
    });
    // Text typed but not yet added still counts when leaving the box or submitting.
    entry.addEventListener("blur", () => { if (entry.value.trim()) commit(entry.value); });
    textarea.form?.addEventListener("submit", () => { if (entry.value.trim()) commit(entry.value); });
    add.addEventListener("click", () => { if (entry.value.trim()) commit(entry.value); entry.focus(); });
    box.addEventListener("click", (e) => { if (e.target === box || e.target === list) entry.focus(); });

    // Mirror the field's state classes (AI-filled, error) onto the visible box.
    const field = textarea.closest(".field");
    if (field) ["has-error", "ai-filled", "ai-empty"].forEach((c) => field.classList.contains(c) && box.classList.add(c));

    items = splitItems(textarea.value);
    sync();
  }

  let started = false;
  function start() {
    if (started) return; // a deferred script can see both "interactive" and DOMContentLoaded
    started = true;
    initLanguages();
    document.querySelectorAll("textarea[data-chips]").forEach(initChips);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
