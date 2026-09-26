// Rendu et clics de la grille Effectifs (MERCATO_GRID_JS de pages/2_Effectifs.py) dans un DOM
// simulé (jsdom), monté dans un shadow DOM comme le fait Streamlit. Données : tests/js/fixtures/,
// copies des données JSON envoyées au composant pour 2024-25 et 2023-24 (prepare_season).
//
// Lancer depuis la racine du projet :  cd tests/js && npm install && node test_dom.mjs
// (ou tous les tests JS :               cd tests/js && npm install && npm test)

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM, VirtualConsole } from "jsdom";
import { loadGrid } from "./load_grid.mjs";

// Lien suivi ou non : un clic non intercepté fait tenter une navigation à jsdom (asynchrone, puis
// erreur "Not implemented: navigation"), comptée ici plutôt qu'affichée et vérifiée à la fin.
const navigations = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (e) => {
  if (/Not implemented: navigation/.test(e.message)) navigations.push(e.message);
  else console.error(e);
});
const dom = new JSDOM("<!doctype html><body><div id=host></div></body>", {
  url: "http://localhost:8501/Effectifs", virtualConsole,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const scrolls = [];
window.scrollTo = (...args) => scrolls.push(args);
const { default: mount } = await loadGrid();
const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const data1 = fixture("grid_2024-25.json");
const data2 = fixture("grid_2023-24.json");

const shadow = document.getElementById("host").attachShadow({ mode: "open" });
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log("ok -", name); };
const $ = (sel) => shadow.querySelector(sel);
const $$ = (sel) => [...shadow.querySelectorAll(sel)];
const click = (node) => node.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const card = (code) => $$(".mg-card").find((c) => c.querySelector('[data-action="reset-team"]').dataset.team === code);
const tiles = (code) => [...card(code).querySelectorAll(".mg-slot")];
const btn = (code, action, slot) => card(code).querySelector(`[data-action="${action}"][data-slot="${slot}"]`);
const lastToast = () => { const t = $$(".mg-toast"); return t.length ? t[t.length - 1].textContent : null; };
const type = (text) => { const i = $(".mg-input"); i.value = text; i.dispatchEvent(new window.Event("input", { bubbles: true })); };
const key = (k) => $(".mg-input").dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true }));
const byName = (d, re) => d.players.find((p) => re.test(p[1]))[0];
const teamOf = (d, code) => d.teams.find((t) => t.code === code);

// setTriggerValue simulé : Streamlit le fournit toujours au composant.
const triggers = [];
const setTriggerValue = (name, value) => triggers.push([name, value]);
const mountWith = (data) => mount({ data, parentElement: shadow, setTriggerValue });
const linkClick = (code, init = {}, inner = null) => {
  const ev = new window.MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init });
  const link = card(code).querySelector(".mg-team-link");
  (inner ? link.querySelector(inner) : link).dispatchEvent(ev);
  return ev;
};

let cleanup = mountWith(data1);

test("montage : 30 cartes, 180 tuiles photo, étiquettes M/A/AI/AF/P/6e, pas de marqueur", () => {
  assert.equal($$(".mg-card").length, 30);
  assert.equal($$(".mg-tile img").length, 180);
  assert.equal($$(".mg-tile-empty").length, 0);
  assert.deepEqual(tiles("DEN").map((s) => s.querySelector(".mg-badge").textContent), ["M", "A", "AI", "AF", "P", "6e"]);
  assert.equal($$(".mg-modified").length, 0);
  assert.equal($$(".mg-spacer").length, 30);
  assert.ok(card("DEN").querySelector(".mg-team-name").textContent.includes("Denver"));
});

test("boutons sous la rangée : ✕ par tuile remplie, ⇄ par paire voisine, hors des cellules de tuile", () => {
  const row = card("DEN").querySelector(".mg-slots");
  const xs = [...row.children].filter((n) => n.classList.contains("mg-x"));
  const sws = [...row.children].filter((n) => n.classList.contains("mg-swap"));
  assert.deepEqual(xs.map((b) => b.dataset.slot), ["0", "1", "2", "3", "4", "5"]);
  assert.deepEqual(sws.map((b) => b.dataset.slot), ["0", "1", "2", "3", "4"]);
  assert.equal(card("DEN").querySelectorAll(".mg-slot button[data-action='remove'], .mg-slot button[data-action='swap']").length, 0);
  assert.deepEqual(tiles("DEN").map((c) => c.dataset.slot), ["0", "1", "2", "3", "4", "5"]);
  assert.equal(sws[2].title, "Intervertir AI et AF");
  assert.deepEqual([...sws[2].querySelectorAll(".mg-swap-label")].map((l) => l.textContent), ["AI ", " AF"]);
  // clic sur le libellé (span) du ⇄ : bien pris comme un clic sur le bouton
  const before = tiles("DEN").map((c) => c.querySelector("img").src);
  click(sws[2].querySelector(".mg-swap-label"));
  const after = tiles("DEN").map((c) => c.querySelector("img").src);
  assert.equal(after[2], before[3]);
  assert.equal(after[3], before[2]);
  click(card("DEN").querySelector('.mg-swap[data-slot="2"]')); // remet dans l'ordre
  assert.deepEqual(tiles("DEN").map((c) => c.querySelector("img").src), before);
});

test("✕ : slot vidé en tuile pointillée '+', étiquette conservée, marqueur 'modifiée', sauvegarde", () => {
  click(btn("DEN", "remove", 0));
  const s0 = tiles("DEN")[0];
  assert.ok(s0.querySelector(".mg-tile-empty"));
  assert.equal(s0.querySelector(".mg-plus").textContent, "+");
  assert.equal(s0.querySelector(".mg-badge").textContent, "M");
  assert.ok(card("DEN").querySelector(".mg-modified"));
  assert.equal($$(".mg-modified").length, 1);
  const saved = JSON.parse(window.localStorage.getItem("mercato_v1_2024-25"));
  assert.equal(saved.slots.DEN[0], null);
});

const jokic = byName(data1, /Joki/);
const inCards = new Set(data1.teams.flatMap((t) => t.slots));
const free = data1.players.find((p) => !inCards.has(p[0]));

test("clic sur tuile vide : fenêtre de recherche, saisie, Entrée -> ajout, fermeture auto, toast", () => {
  click(tiles("DEN")[0].querySelector(".mg-tile-empty"));
  assert.ok($(".mg-overlay"));
  assert.ok($(".mg-panel-caption").textContent.includes("slot M"));
  assert.equal($(".mg-hint").textContent, "Tapez un nom (ex : jokic)");
  type(free[1].normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase());
  assert.equal($$(".mg-result")[0].textContent, `${free[1]} (${free[2]})`);
  key("Enter");
  assert.equal($(".mg-overlay"), null);
  assert.equal(teamOf(data1, "DEN") && Number(tiles("DEN")[0].querySelector("img").src.match(/(\d+)\.png/)[1]), free[0]);
  assert.equal(lastToast(), `${free[1]} rejoint les Denver Nuggets`);
  assert.equal(tiles("DEN")[0].querySelector(".mg-warning"), null);
});

test("transfert : Jokić DEN -> LAL par clic sur le résultat, ancien slot vide, toast", () => {
  const denIdx = teamOf(data1, "DEN").slots.indexOf(jokic);
  click(btn("LAL", "remove", 5));
  click(tiles("LAL")[5].querySelector(".mg-tile-empty"));
  type("jokic");
  const res = $$(".mg-result");
  assert.equal(res.length, 1);
  click(res[0]);
  assert.equal($(".mg-overlay"), null);
  assert.ok(tiles("LAL")[5].querySelector("img").src.endsWith(`/${jokic}.png`));
  assert.ok(tiles("DEN")[denIdx].querySelector(".mg-tile-empty"));
  assert.equal(lastToast(), "Nikola Jokić rejoint les Los Angeles Lakers (quitte les Denver Nuggets)");
});

test("même carte : rien ne change, toast", () => {
  const before = card("LAL").innerHTML;
  click(btn("LAL", "remove", 0));
  click(tiles("LAL")[0].querySelector(".mg-tile-empty"));
  type("jokic");
  key("Enter");
  assert.equal(lastToast(), "Nikola Jokić est déjà dans l'effectif des Los Angeles Lakers.");
  assert.equal($(".mg-overlay"), null);
  assert.ok(tiles("LAL")[0].querySelector(".mg-tile-empty"));
  assert.notEqual(before, null);
});

test("Échap et clic sur le fond ferment la recherche sans rien changer", () => {
  click(tiles("LAL")[0].querySelector(".mg-tile-empty"));
  key("Escape");
  assert.equal($(".mg-overlay"), null);
  click(tiles("LAL")[0].querySelector(".mg-tile-empty"));
  click($(".mg-panel")); // clic DANS la fenêtre : reste ouverte
  assert.ok($(".mg-overlay"));
  click($(".mg-overlay"));
  assert.equal($(".mg-overlay"), null);
});

test("⇄ : interversion avec le voisin de droite, étiquettes fixes ; pas de ⇄ sous le 6e", () => {
  const ids = () => tiles("BOS").map((s) => { const i = s.querySelector("img"); return i ? i.src : null; });
  const before = ids();
  click(btn("BOS", "swap", 0));
  const after = ids();
  assert.equal(after[0], before[1]);
  assert.equal(after[1], before[0]);
  assert.deepEqual(tiles("BOS").map((s) => s.querySelector(".mg-badge").textContent), ["M", "A", "AI", "AF", "P", "6e"]);
  assert.equal(btn("BOS", "swap", 5), null);
  click(btn("BOS", "swap", 4)); // P <-> 6e
  const after2 = ids();
  assert.equal(after2[4], before[5]);
});

test("reset d'équipe : Jokić revient à Denver (quitte les Lakers), toast, marqueur retiré", () => {
  click(card("DEN").querySelector('[data-action="reset-team"]'));
  const denIdx = teamOf(data1, "DEN").slots.indexOf(jokic);
  assert.ok(tiles("DEN")[denIdx].querySelector("img").src.endsWith(`/${jokic}.png`));
  assert.ok(tiles("LAL")[5].querySelector(".mg-tile-empty"));
  assert.ok($$(".mg-toast").some((t) => t.textContent === "Nikola Jokić revient aux Denver Nuggets (quitte les Los Angeles Lakers)"));
  assert.equal(card("DEN").querySelector(".mg-modified"), null);
  assert.equal(card("DEN").querySelector('[data-action="reset-team"]').disabled, true);
  assert.ok(card("LAL").querySelector(".mg-modified"));
});

test("changement de saison puis retour : état de chaque saison conservé, une seule grille", () => {
  mountWith(data2);
  assert.equal($$(".mg-root").length, 1);
  assert.equal($$(".mg-modified").length, 0);
  click(btn("MIA", "remove", 1));
  assert.equal($$(".mg-modified").length, 1);
  mountWith(data1);
  assert.equal($$(".mg-root").length, 1);
  assert.ok(tiles("LAL")[5].querySelector(".mg-tile-empty"));
  assert.ok(card("LAL").querySelector(".mg-modified"));
  assert.ok(card("BOS").querySelector(".mg-modified"));
  mountWith(data2);
  assert.ok(tiles("MIA")[1].querySelector(".mg-tile-empty"));
  mountWith(data1);
});

test("rechargement de page (nouveau montage) : état relu depuis localStorage", () => {
  cleanup();
  assert.equal($$(".mg-root").length, 0);
  cleanup = mountWith(data1);
  assert.ok(tiles("LAL")[5].querySelector(".mg-tile-empty"));
  assert.ok(card("BOS").querySelector(".mg-modified"));
});

test("reset global : second clic de confirmation obligatoire", () => {
  const b = $(".mg-reset-all");
  click(b);
  assert.equal(b.textContent, "Confirmer la réinitialisation ?");
  assert.ok($$(".mg-modified").length > 0);
  click(b);
  assert.equal($$(".mg-modified").length, 0);
  assert.equal(b.textContent, "↺ Tout réinitialiser");
  assert.equal(lastToast(), "Toutes les compositions ont été réinitialisées");
  const saved = JSON.parse(window.localStorage.getItem("mercato_v1_2024-25"));
  assert.deepEqual(saved.slots.LAL, teamOf(data1, "LAL").slots);
});

test("noms insérés en texte, jamais interprétés comme HTML", () => {
  const evil = structuredClone(data1);
  evil.season = "test-xss";
  evil.players[0][1] = '<img src=x onerror="window.__pwned=1">Evil';
  evil.teams[0].slots[0] = evil.players[0][0];
  mountWith(evil);
  assert.equal(shadow.querySelector('img[src="x"]'), null);
  mountWith(data1);
});

test("nom d'équipe = lien-bouton vers l'effectif réel : nom + flèche, logo/marqueur/reset hors du bouton", () => {
  assert.equal($$(".mg-team-link").length, 30);
  const den = card("DEN").querySelector(".mg-team-link");
  assert.equal(den.tagName, "A");
  assert.equal(den.getAttribute("href"), "?saison=2024-25&equipe=DEN");
  assert.equal(den.href, "http://localhost:8501/Effectifs?saison=2024-25&equipe=DEN");
  assert.deepEqual([...den.children].map((c) => [c.className, c.textContent]),
    [["mg-team-name", teamOf(data1, "DEN").name], ["mg-team-arrow", "→"]]);
  assert.equal(den.querySelector(".mg-team-arrow").getAttribute("aria-hidden"), "true");
  assert.equal(den.querySelector(".mg-logo, .mg-emblem, .mg-modified, button"), null);
  click(btn("DEN", "remove", 0)); // carte modifiée : marqueur à côté du bouton, pas dedans
  const ident = card("DEN").querySelector(".mg-ident");
  assert.deepEqual([...ident.children].map((c) => c.className), ["mg-logo", "mg-team-link", "mg-modified"]);
  assert.ok(card("DEN").querySelector(".mg-card-header > .mg-reset-team"));
  click(card("DEN").querySelector('[data-action="reset-team"]'));
  assert.equal(den.title, `Voir l'effectif réel 2024-25 des ${teamOf(data1, "DEN").name}`);
  mountWith(data2);
  assert.equal(card("MIA").querySelector(".mg-team-link").getAttribute("href"), "?saison=2023-24&equipe=MIA");
  mountWith(data1);
});

test("clic simple sur le nom : déclencheur open_team, pas de rechargement, page remontée, grille intacte", () => {
  triggers.length = 0;
  scrolls.length = 0;
  const before = $(".mg-grid").innerHTML;
  const ev = linkClick("BOS");
  assert.deepEqual(triggers, [["open_team", "BOS"]]);
  assert.equal(ev.defaultPrevented, true);
  assert.equal(scrolls.length, 1);
  assert.equal($(".mg-grid").innerHTML, before);
  // clic sur le nom ou la flèche, à l'intérieur du bouton : même effet
  triggers.length = 0;
  assert.equal(linkClick("MIA", {}, ".mg-team-name").defaultPrevented, true);
  assert.equal(linkClick("MIA", {}, ".mg-team-arrow").defaultPrevented, true);
  assert.deepEqual(triggers, [["open_team", "MIA"], ["open_team", "MIA"]]);
});

test("Cmd/Ctrl/Maj/Alt + clic : lien suivi normalement (nouvel onglet), rien d'intercepté", () => {
  triggers.length = 0;
  for (const mod of ["metaKey", "ctrlKey", "shiftKey", "altKey"]) {
    assert.equal(linkClick("BOS", { [mod]: true }).defaultPrevented, false, mod);
  }
  assert.deepEqual(triggers, []);
});

test("sans setTriggerValue : le nom reste un lien normal (rechargement complet)", () => {
  mount({ data: data1, parentElement: shadow });
  triggers.length = 0;
  assert.equal(linkClick("BOS").defaultPrevented, false);
  assert.deepEqual(triggers, []);
  mountWith(data1);
});

test("sauvegarde écrite par l'ancienne page Mercato relue par la page Effectifs", () => {
  // Clé et format exacts de l'ancienne page (mercato_v1_<saison>, empreinte saison|CODE:ids;...),
  // écrits en dur ici pour détecter tout changement qui rendrait les sauvegardes existantes
  // illisibles.
  cleanup();
  const fp = data1.season + "|" + data1.teams.map((t) => t.code + ":" + t.slots.map((s) => (s == null ? "-" : s)).join(",")).join(";");
  const slots = Object.fromEntries(data1.teams.map((t) => [t.code, t.slots.slice()]));
  slots.MIL[2] = null;
  window.localStorage.setItem("mercato_v1_2024-25", JSON.stringify({ fp, slots, added: [] }));
  cleanup = mountWith(data1);
  assert.ok(tiles("MIL")[2].querySelector(".mg-tile-empty"));
  assert.equal($$(".mg-modified").length, 1);
});

test("aller-retour vers un effectif (grille démontée puis remontée) : modifications conservées", () => {
  cleanup();
  assert.equal($$(".mg-root").length, 0);
  cleanup = mountWith(data1);
  assert.ok(tiles("MIL")[2].querySelector(".mg-tile-empty"));
  assert.ok(card("MIL").querySelector(".mg-modified"));
});

// Coût d'un clic côté JS (jsdom, ordre de grandeur seulement : pas de mise en page réelle).
const t0 = performance.now();
for (let i = 0; i < 20; i++) { click(btn("ATL", "swap", 0)); }
console.log(`\nclic ⇄ (re-rendu d'une carte) dans jsdom : ${((performance.now() - t0) / 20).toFixed(2)} ms en moyenne`);
// Navigations tentées (asynchrones) : exactement les 5 clics NON interceptés plus haut (4 clics
// avec modificateur + 1 sans setTriggerValue) ; le clic simple intercepté n'en a déclenché aucune.
await new Promise((resolve) => setTimeout(resolve, 50));
test("liens suivis : uniquement les clics non interceptés", () => {
  assert.equal(navigations.length, 5);
});

console.log(`${passed} tests DOM OK`);
