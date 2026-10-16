// Liste de recherche de joueurs (composant st.components.v2, sans iframe, styles isolés dans un
// shadow DOM), partagée par le Dashboard (un joueur) et le Radar (jusqu'à `max` joueurs). Sur le
// modèle de la grille Effectifs (pages/2_Effectifs.py). Deux parties :
//   1. fonctions de recherche PURES (aucun accès au DOM), exportées et testées avec node ;
//   2. rendu DOM + clavier/souris/tactile (export default, appelé par Streamlit au montage puis à
//      chaque changement de `data`).
// La recherche se fait entièrement ici, à chaque lettre, sans relancer la page. Python n'est
// prévenu (setTriggerValue("selection", [clés])) que d'un vrai changement de sélection : taper ne
// touche jamais à la sélection. La sélection affichée vient de Python (data.selected) à chaque
// envoi de données (présélection, saison, navigation).
// Tests : tests/js/test_picker.mjs.

// ---------------------------------------------------------------------------------------------
// 1. Fonctions de recherche pures
// ---------------------------------------------------------------------------------------------

// Minuscules sans accents : "Gaël" -> "gael", "Dončić" -> "doncic". Même normalisation que la
// recherche de la grille Effectifs (normalize de MERCATO_GRID_JS).
export function normalize(text) {
  return String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

// Mots de la recherche, normalisés ("  Fickou  GAËL " -> ["fickou", "gael"]).
export function queryWords(query) {
  return normalize(query).split(/\s+/).filter(Boolean);
}

// Index de recherche : [{ key, label, n (libellé normalisé) }], dans l'ordre des options.
export function buildIndex(options) {
  return options.map(([key, label]) => ({ key, label, n: normalize(label) }));
}

// Options dont le libellé contient chaque mot, dans n'importe quel ordre ("fickou gael" trouve
// "Gaël Fickou"), hors clés de `exclude`. Recherche vide : toutes les options hors `exclude`.
export function searchOptions(index, query, exclude = new Set()) {
  const words = queryWords(query);
  return index.filter((o) => !exclude.has(o.key) && words.every((w) => o.n.includes(w)));
}

// Morceaux du libellé pour la mise en évidence : [[texte, trouvé], ...]. Chaque caractère
// d'origine est normalisé à part, pour retrouver sa place dans le libellé normalisé.
export function highlightParts(label, query) {
  const words = queryWords(query);
  const chars = [...String(label)];
  if (!words.length) return [[chars.join(""), false]];
  let flat = "";
  const origin = [];
  chars.forEach((c, i) => {
    const n = normalize(c);
    flat += n;
    for (let k = 0; k < n.length; k++) origin.push(i);
  });
  const hit = new Array(chars.length).fill(false);
  for (const w of words) {
    let from = flat.indexOf(w);
    while (from !== -1) {
      for (let k = from; k < from + w.length; k++) hit[origin[k]] = true;
      from = flat.indexOf(w, from + w.length);
    }
  }
  const parts = [];
  chars.forEach((c, i) => {
    const last = parts[parts.length - 1];
    if (last && last[1] === hit[i]) last[0] += c;
    else parts.push([c, hit[i]]);
  });
  return parts;
}

// ---------------------------------------------------------------------------------------------
// 2. Rendu DOM
// ---------------------------------------------------------------------------------------------

const CHEVRON = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z"/></svg>';
let uid = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function createPicker(parent) {
  const id = `pp-${++uid}`;
  const root = el("div", "pp-root");
  const label = el("label", "pp-label");
  const control = el("div", "pp-control");
  const values = el("div", "pp-values");
  const single = el("span", "pp-single");
  const input = el("input", "pp-input");
  const indicators = el("div", "pp-indicators");
  const clear = el("button", "pp-clear", "×");
  const chevron = el("span", "pp-chevron");
  const menu = el("ul", "pp-menu");
  input.id = `${id}-input`;
  label.htmlFor = input.id;
  input.type = "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${id}-menu`);
  menu.id = `${id}-menu`;
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  clear.type = "button";
  chevron.innerHTML = CHEVRON;
  values.append(single, input);
  indicators.append(clear, chevron);
  control.append(values, indicators);
  root.append(label, control, menu);
  parent.appendChild(root);

  let data = { options: [], selected: [], max: 1, label: "", placeholder: "", texts: {} };
  let index = [];
  let selected = [];
  let results = [];
  let active = 0;
  let trigger = () => {};
  const multi = () => data.max > 1;
  const full = () => multi() && selected.length >= data.max;
  const labelOf = new Map();
  const isOpen = () => !menu.hidden;

  function emit(next) {
    if (next.length === selected.length && next.every((k, i) => k === selected[i])) return;
    selected = next;
    renderValues();
    trigger("selection", [...selected]);
  }

  function renderValues() {
    label.textContent = data.label || "";
    label.hidden = !data.label;
    values.querySelectorAll(".pp-chip").forEach((c) => c.remove());
    if (multi()) {
      for (const key of selected) {
        const chip = el("span", "pp-chip");
        const text = el("span", "pp-chip-text", labelOf.get(key) ?? String(key));
        const remove = el("button", "pp-chip-remove", "×");
        remove.type = "button";
        remove.dataset.key = JSON.stringify(key);
        remove.setAttribute("aria-label", `${data.texts.remove || "Retirer"} ${text.textContent}`);
        chip.append(text, remove);
        values.insertBefore(chip, input);
      }
      single.hidden = true;
      clear.hidden = true;
    } else {
      const key = selected[0];
      single.textContent = key == null ? "" : labelOf.get(key) ?? String(key);
      single.hidden = key == null || input.value !== "";
      clear.hidden = key == null;
      clear.setAttribute("aria-label", data.texts.clear || "Désélectionner");
    }
    const empty = multi() ? selected.length === 0 : selected[0] == null;
    input.placeholder = empty ? data.placeholder || "" : "";
    root.classList.toggle("pp-has-value", !empty);
  }

  function renderMenu() {
    menu.replaceChildren();
    const query = input.value;
    results = searchOptions(index, query, multi() ? new Set(selected) : new Set());
    if (full()) menu.append(el("li", "pp-notice", data.texts.full || ""));
    if (!results.length) {
      menu.append(el("li", "pp-empty", data.texts.empty || "Aucun joueur trouvé"));
    }
    active = Math.min(active, Math.max(results.length - 1, 0));
    results.forEach((o, i) => {
      const li = el("li", "pp-option");
      li.id = `${id}-opt-${i}`;
      li.dataset.index = String(i);
      li.setAttribute("role", "option");
      if (full()) li.setAttribute("aria-disabled", "true");
      if (!multi() && o.key === selected[0]) li.setAttribute("aria-selected", "true");
      for (const [text, hit] of highlightParts(o.label, query)) {
        li.append(hit ? el("mark", null, text) : document.createTextNode(text));
      }
      menu.append(li);
    });
    markActive();
  }

  function markActive() {
    menu.querySelectorAll(".pp-option").forEach((li, i) => li.classList.toggle("pp-active", i === active));
    const li = menu.querySelector(`#${id}-opt-${active}`);
    if (li) {
      input.setAttribute("aria-activedescendant", li.id);
      if (typeof li.scrollIntoView === "function") li.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function open() {
    if (!isOpen()) active = 0;
    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
    root.classList.add("pp-open");
    renderMenu();
  }

  function close() {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    root.classList.remove("pp-open");
  }

  function resetQuery() {
    input.value = "";
    renderValues();
  }

  // Choix d'une option : sélection unique remplacée, ou ajout (refusé au-delà de max).
  function pick(i) {
    const option = results[i];
    if (!option || full()) return;
    if (multi()) emit([...selected, option.key]);
    else emit([option.key]);
    resetQuery();
    close();
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen()) { open(); return; }
      if (!results.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      markActive();
    } else if (e.key === "Enter") {
      if (isOpen()) { e.preventDefault(); pick(active); }
      else open();
    } else if (e.key === "Escape") {
      if (isOpen() || input.value) { e.preventDefault(); e.stopPropagation(); }
      resetQuery();
      close();
    } else if (e.key === "Tab") {
      close();
    }
  }

  function onInput() {
    active = 0;
    renderValues();
    open();
  }

  // Un clic dans la case (hors croix) ouvre la liste ; mousedown sans défaut garde le focus dans
  // la case quand on clique une option ou une croix (sinon blur fermerait la liste avant le clic).
  function onMouseDown(e) {
    if (e.target !== input) e.preventDefault();
  }

  function onClick(e) {
    const remove = e.target.closest(".pp-chip-remove");
    if (remove) {
      const key = JSON.parse(remove.dataset.key);
      emit(selected.filter((k) => k !== key));
      if (isOpen()) renderMenu();
      return;
    }
    if (e.target.closest(".pp-clear")) {
      emit([]);
      resetQuery();
      close();
      return;
    }
    const option = e.target.closest(".pp-option");
    if (option) { pick(Number(option.dataset.index)); return; }
    if (e.target === input) { open(); return; }
    if (e.target.closest(".pp-control")) {
      input.focus();
      if (isOpen()) close(); else open();
    }
  }

  function onBlur() {
    resetQuery();
    close();
  }

  input.addEventListener("keydown", onKeyDown);
  input.addEventListener("input", onInput);
  input.addEventListener("blur", onBlur);
  root.addEventListener("mousedown", onMouseDown);
  root.addEventListener("click", onClick);

  return {
    root,
    setTrigger(fn) { trigger = fn || (() => {}); },
    setData(next) {
      data = { ...data, ...next, texts: { ...(next.texts || {}) } };
      index = buildIndex(data.options || []);
      labelOf.clear();
      for (const o of index) labelOf.set(o.key, o.label);
      selected = (data.selected || []).filter((k) => labelOf.has(k));
      renderValues();
      if (isOpen()) renderMenu();
    },
    get selected() { return [...selected]; },
    destroy() {
      input.removeEventListener("keydown", onKeyDown);
      input.removeEventListener("input", onInput);
      input.removeEventListener("blur", onBlur);
      root.removeEventListener("mousedown", onMouseDown);
      root.removeEventListener("click", onClick);
      root.remove();
    },
  };
}

// Appelée par Streamlit au montage, puis de nouveau quand `data` change, avec le MÊME
// parentElement : la liste existante est réutilisée (texte tapé et focus gardés).
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!data || !parentElement) return undefined;
  let picker = parentElement.__playerPicker;
  if (!picker) {
    picker = createPicker(parentElement);
    parentElement.__playerPicker = picker;
  }
  picker.setTrigger(setTriggerValue);
  picker.setData(data);
  return () => {
    picker.destroy();
    delete parentElement.__playerPicker;
  };
}
