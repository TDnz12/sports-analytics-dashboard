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

const CDN = "https://cdn.nba.com/headshots/nba";
const imgOf = (code, pid) => card(code).querySelector(`.mg-tile img[src$="/${pid}.png"]`);

test("photo : portrait de la saison sous l'équipe du premier match, repli unique sur le portrait actuel", () => {
  const pid = teamOf(data1, "DEN").slots[0];
  const img = imgOf("DEN", pid);
  assert.equal(img.src, `${CDN}/${data1.photo_team_ids[pid]}/2024/1040x760/${pid}.png`);
  img.dispatchEvent(new window.Event("error"));
  assert.equal(img.src, `${CDN}/latest/1040x760/${pid}.png`);
  img.dispatchEvent(new window.Event("error")); // pas de boucle
  assert.equal(img.src, `${CDN}/latest/1040x760/${pid}.png`);
});

test("photo d'un joueur transféré en cours de saison : Siakam 2023-24 sous TOR dans la carte IND", () => {
  cleanup();
  cleanup = mountWith(data2);
  const siakam = byName(data2, /Siakam/);
  assert.ok(teamOf(data2, "IND").slots.includes(siakam));
  assert.equal(data2.photo_team_ids[siakam], 1610612761); // Toronto Raptors
  assert.equal(imgOf("IND", siakam).src, `${CDN}/1610612761/2023/1040x760/${siakam}.png`);
  cleanup();
  cleanup = mountWith(data1);
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
  // Photo toujours celle de l'équipe de son premier match (DEN), pas de sa nouvelle carte.
  assert.equal(tiles("LAL")[5].querySelector("img").src, `${CDN}/${data1.photo_team_ids[jokic]}/2024/1040x760/${jokic}.png`);
  assert.equal(data1.photo_team_ids[jokic], 1610612743); // Denver Nuggets
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

test("logo d'époque dans chaque en-tête (adresse locale static/), emblème seulement sans logo", () => {
  for (const t of data1.teams) {
    const img = card(t.code).querySelector(".mg-logo img");
    assert.equal(img.getAttribute("src"), t.logo, t.code);
    assert.ok(t.logo.startsWith("app/static/logos/nba/"), t.code);
  }
  assert.equal($$(".mg-emblem").length, 0);
  const noLogo = structuredClone(data1);
  noLogo.season = "test-sans-logo";
  noLogo.teams[0].logo = null;
  mountWith(noLogo);
  assert.equal(card(noLogo.teams[0].code).querySelector(".mg-emblem").textContent, noLogo.teams[0].code);
  assert.equal(card(noLogo.teams[0].code).querySelector(".mg-logo"), null);
  mountWith(data1);
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

// ---------------------------------------------------------------------------------------------
// Glisser-déposer. jsdom 24 n'a ni PointerEvent, ni elementFromPoint (pas de mise en page), ni
// requestAnimationFrame : événements pointer = MouseEvent + pointerId/pointerType ; chaque tuile
// visée reçoit une abscisse propre, que elementFromPoint (simulé sur le shadow root) résout ;
// images d'animation exécutées à la main.
// ---------------------------------------------------------------------------------------------
const points = new Map();
let nextX = 100;
shadow.elementFromPoint = (x) => points.get(x) || null;
const at = (node) => { const x = (nextX += 10); points.set(x, node); return { x, y: 300 }; };
const OUTSIDE = { x: 1, y: 300 }; // rien sous le pointeur
let rafQueue = [];
window.requestAnimationFrame = (cb) => { rafQueue.push(cb); return rafQueue.length; };
window.cancelAnimationFrame = () => { rafQueue = []; };
const runFrame = () => { const q = rafQueue; rafQueue = []; q.forEach((cb) => cb()); };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const testAsync = async (name, fn) => { await fn(); passed++; console.log("ok -", name); };

const pointer = (type, target, { x, y }, init = {}) => {
  const ev = new window.MouseEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, button: 0 });
  Object.defineProperty(ev, "pointerId", { value: init.pointerId ?? 1 });
  Object.defineProperty(ev, "pointerType", { value: init.pointerType ?? "mouse" });
  target.dispatchEvent(ev);
  return ev;
};
const tileAt = (code, j) => tiles(code)[j].querySelector(".mg-tile");
const pidAt = (code, j) => { const i = tiles(code)[j].querySelector("img"); return i ? Number(i.src.match(/(\d+)\.png$/)[1]) : null; };
const pidsOf = (code) => tiles(code).map((_, j) => pidAt(code, j));
// Après un glisser à la souris, le navigateur envoie un click sur l'ancêtre commun des éléments
// de départ et d'arrivée (ici la grille) : la grille doit l'ignorer.
const browserClick = () => click($(".mg-grid"));
// Glisser à la souris de la tuile (code, j) vers `dest` (nœud visé, ou null = hors tuile).
const mouseDrag = (code, j, dest, { withClick = true } = {}) => {
  const src = tileAt(code, j);
  const start = at(src.querySelector("img") || src);
  pointer("pointerdown", src, start);
  pointer("pointermove", src, { x: start.x, y: start.y + 20 }); // au-delà du seuil : démarre
  const end = dest ? at(dest) : OUTSIDE;
  pointer("pointermove", src, end);
  pointer("pointerup", src, end);
  if (withClick) browserClick();
};
const saved = () => JSON.parse(window.localStorage.getItem("mercato_v1_2024-25"));
const resetAll = () => { click($(".mg-reset-all")); click($(".mg-reset-all")); };

test("glisser à la souris vers une tuile vide de la même carte : déplacement, étiquettes fixes, pas de toast", () => {
  resetAll();
  const toastsBefore = $$(".mg-toast").length;
  const den = pidsOf("DEN");
  click(btn("DEN", "remove", 0));
  mouseDrag("DEN", 4, tiles("DEN")[0].querySelector(".mg-plus")); // Jokić (P) -> M vide
  assert.deepEqual(pidsOf("DEN"), [den[4], den[1], den[2], den[3], null, den[5]]);
  assert.deepEqual(tiles("DEN").map((s) => s.querySelector(".mg-badge").textContent), ["M", "A", "AI", "AF", "P", "6e"]);
  assert.equal(tileAt("DEN", 0).title, "Nikola Jokić");
  assert.ok(card("DEN").querySelector(".mg-modified"));
  assert.deepEqual(saved().slots.DEN, [den[4], den[1], den[2], den[3], null, den[5]]);
  assert.equal($$(".mg-toast").length, toastsBefore);
  // plus de fantôme ni de surlignage après le lâcher
  assert.equal($$(".mg-ghost, .mg-dragging, .mg-drop-target, .mg-is-dragging").length, 0);
});

test("glisser sur un autre joueur de la même carte : échange, pas de toast", () => {
  resetAll();
  const toastsBefore = $$(".mg-toast").length;
  const bos = pidsOf("BOS");
  mouseDrag("BOS", 0, tileAt("BOS", 5).querySelector("img"));
  assert.deepEqual(pidsOf("BOS"), [bos[5], bos[1], bos[2], bos[3], bos[4], bos[0]]);
  assert.equal($$(".mg-toast").length, toastsBefore);
  assert.equal($$(".mg-modified").length, 1);
});

test("glisser sur un joueur d'une autre carte : échange DEN ↔ LAL, toast, photos suivent", () => {
  resetAll();
  const den = pidsOf("DEN");
  const lal = pidsOf("LAL");
  const denPhoto = tileAt("DEN", 4).querySelector("img").src;
  mouseDrag("DEN", 4, tileAt("LAL", 2).querySelector(".mg-name")); // Jokić <-> James
  assert.equal(pidAt("DEN", 4), lal[2]);
  assert.equal(pidAt("LAL", 2), den[4]);
  assert.equal(tileAt("LAL", 2).querySelector("img").src, denPhoto);
  assert.equal(lastToast(), "Échange : Jokić ↔ James (DEN ↔ LAL)");
  assert.ok(card("DEN").querySelector(".mg-modified"));
  assert.ok(card("LAL").querySelector(".mg-modified"));
  assert.equal(saved().slots.LAL[2], den[4]);
  assert.deepEqual(saved().added.slice().sort((a, b) => a - b), [den[4], lal[2]].sort((a, b) => a - b));
});

test("glisser vers une tuile vide d'une autre carte : transfert, toast", () => {
  resetAll();
  const bos0 = pidAt("BOS", 0);
  click(btn("MIA", "remove", 3));
  mouseDrag("BOS", 0, tiles("MIA")[3]);
  assert.equal(pidAt("MIA", 3), bos0);
  assert.ok(tiles("BOS")[0].querySelector(".mg-tile-empty"));
  assert.equal(lastToast(), `${tileAt("MIA", 3).title} rejoint les ${teamOf(data1, "MIA").name} (quitte les ${teamOf(data1, "BOS").name})`);
});

test("lâché hors tuile, sur un bouton ✕ ou sur sa propre place : rien ne change, rien n'est sauvegardé", () => {
  resetAll();
  const before = $(".mg-grid").innerHTML;
  window.localStorage.removeItem("mercato_v1_2024-25");
  mouseDrag("DEN", 1, null);
  mouseDrag("DEN", 1, btn("LAL", "remove", 0));
  mouseDrag("DEN", 1, tileAt("DEN", 1).querySelector(".mg-badge"));
  assert.equal($(".mg-grid").innerHTML, before);
  assert.equal(window.localStorage.getItem("mercato_v1_2024-25"), null);
  assert.equal($$(".mg-ghost").length, 0);
});

test("pendant le glisser : fantôme, tuile de départ grisée, destination surlignée (pas sa propre place)", () => {
  resetAll();
  const src = tileAt("DEN", 0);
  const start = at(src);
  pointer("pointerdown", src, start);
  pointer("pointermove", src, { x: start.x, y: start.y + 3 }); // sous le seuil : pas encore
  assert.equal($(".mg-ghost"), null);
  pointer("pointermove", src, { x: start.x, y: start.y + 20 });
  assert.ok($(".mg-ghost"));
  assert.equal($(".mg-ghost").style.transform, "translate(0px, 20px)");
  assert.ok(src.classList.contains("mg-dragging"));
  assert.equal($$(".mg-drop-target").length, 0); // au-dessus de sa propre place
  pointer("pointermove", src, at(tileAt("LAL", 1)));
  assert.deepEqual($$(".mg-drop-target"), [tiles("LAL")[1]]);
  pointer("pointermove", src, OUTSIDE);
  assert.equal($$(".mg-drop-target").length, 0);
  // Échap : annulé, rien ne change
  window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape" }));
  assert.equal($$(".mg-ghost, .mg-dragging, .mg-is-dragging").length, 0);
  pointer("pointerup", src, at(tileAt("LAL", 1)));
  assert.equal($$(".mg-modified").length, 0);
});

await testAsync("clic simple : un petit mouvement reste un clic (tuile vide = recherche), click après un lâcher ignoré", async () => {
  resetAll();
  click(btn("DEN", "remove", 0));
  const empty = tileAt("DEN", 0);
  const p = at(empty);
  pointer("pointerdown", empty, p); // tuile vide : jamais de glisser
  pointer("pointermove", empty, { x: p.x, y: p.y + 30 });
  assert.equal($(".mg-ghost"), null);
  pointer("pointerup", empty, p);
  click(empty);
  assert.ok($(".mg-overlay"));
  key("Escape");
  // tuile remplie : petit mouvement (< 5 px) puis relâché -> pas de glisser, clic normal
  const src = tileAt("DEN", 1);
  const s = at(src);
  pointer("pointerdown", src, s);
  pointer("pointermove", src, { x: s.x + 2, y: s.y + 2 });
  pointer("pointerup", src, s);
  assert.equal($(".mg-ghost"), null);
  assert.equal(pidAt("DEN", 1), teamOf(data1, "DEN").slots[1]);
  // le click envoyé par le navigateur juste après un lâcher est ignoré, pas les suivants
  mouseDrag("DEN", 2, null, { withClick: false });
  click(tileAt("DEN", 0)); // pire cas : ce click tombe sur une tuile vide
  assert.equal($(".mg-overlay"), null);
  await sleep(5);
  click(tileAt("DEN", 0));
  assert.ok($(".mg-overlay"));
  key("Escape");
});

await testAsync("doigt : appui long de 300 ms puis glisser, défilement bloqué seulement pendant le glisser, vibration", async () => {
  resetAll();
  const vibrations = [];
  window.navigator.vibrate = (ms) => { vibrations.push(ms); return true; };
  const den = pidsOf("DEN");
  const lal = pidsOf("LAL");
  const src = tileAt("DEN", 0);
  const start = at(src);
  const touch = { pointerType: "touch", pointerId: 7 };
  pointer("pointerdown", src, start, touch);
  const early = new window.Event("touchmove", { bubbles: true, cancelable: true, composed: true });
  src.dispatchEvent(early);
  assert.equal(early.defaultPrevented, false); // avant l'appui long : la page peut défiler
  await sleep(150);
  assert.equal($(".mg-ghost"), null);
  await sleep(200);
  assert.ok($(".mg-ghost"));
  assert.deepEqual(vibrations, [15]);
  const during = new window.Event("touchmove", { bubbles: true, cancelable: true, composed: true });
  src.dispatchEvent(during);
  assert.equal(during.defaultPrevented, true);
  const menu = new window.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
  src.dispatchEvent(menu);
  assert.equal(menu.defaultPrevented, true);
  // un autre pointeur (deuxième doigt) est ignoré
  pointer("pointermove", src, at(tileAt("LAL", 5)), { pointerType: "touch", pointerId: 8 });
  assert.equal($$(".mg-drop-target").length, 0);
  const end = at(tileAt("LAL", 0));
  pointer("pointermove", src, end, touch);
  pointer("pointerup", src, end, touch);
  assert.equal(pidAt("LAL", 0), den[0]);
  assert.equal(pidAt("DEN", 0), lal[0]);
  const after = new window.Event("touchmove", { bubbles: true, cancelable: true, composed: true });
  tileAt("DEN", 1).dispatchEvent(after);
  assert.equal(after.defaultPrevented, false);
  delete window.navigator.vibrate;
  await sleep(5); // pas de click après un glisser au doigt : le blocage du click expire seul
});

await testAsync("doigt : bouger avant 300 ms = défilement (pas de glisser) ; pointercancel annule sans rien changer", async () => {
  resetAll();
  const touch = { pointerType: "touch", pointerId: 9 };
  const src = tileAt("DEN", 0);
  const start = at(src);
  pointer("pointerdown", src, start, touch);
  pointer("pointermove", src, { x: start.x, y: start.y + 15 }, touch);
  await sleep(350);
  assert.equal($(".mg-ghost"), null);
  pointer("pointerup", src, start, touch);
  // appui long, glisser au-dessus d'une autre carte, puis le navigateur annule le geste
  pointer("pointerdown", src, start, touch);
  await sleep(350);
  pointer("pointermove", src, at(tileAt("LAL", 0)), touch);
  assert.equal($$(".mg-drop-target").length, 1);
  pointer("pointercancel", src, OUTSIDE, touch);
  assert.equal($$(".mg-ghost, .mg-drop-target, .mg-dragging").length, 0);
  assert.equal($$(".mg-modified").length, 0);
});

test("défilement automatique près du bord bas puis haut, dans le conteneur qui défile", () => {
  resetAll();
  const host = document.getElementById("host");
  host.style.overflowY = "auto";
  Object.defineProperty(host, "scrollHeight", { value: 5000, configurable: true });
  Object.defineProperty(host, "clientHeight", { value: 700, configurable: true });
  host.scrollTop = 1000;
  const src = tileAt("DEN", 0);
  const start = at(src);
  pointer("pointerdown", src, start);
  pointer("pointermove", src, { x: start.x, y: start.y + 20 });
  runFrame();
  assert.equal(host.scrollTop, 1000); // milieu de l'écran : immobile
  pointer("pointermove", src, { x: OUTSIDE.x, y: window.innerHeight - 5 });
  runFrame();
  runFrame();
  assert.ok(host.scrollTop > 1000);
  const low = host.scrollTop;
  pointer("pointermove", src, { x: OUTSIDE.x, y: 5 });
  runFrame();
  assert.ok(host.scrollTop < low);
  pointer("pointerup", src, OUTSIDE);
  browserClick();
  const stopped = host.scrollTop;
  runFrame();
  assert.equal(host.scrollTop, stopped);
  assert.equal(rafQueue.length, 0);
  host.style.overflowY = "";
  delete host.scrollHeight;
  delete host.clientHeight;
});

test("⚠️ : suit le joueur dans sa carte, disparaît quand il change de carte (échange)", () => {
  const warn = structuredClone(data1);
  warn.season = "test-warning";
  const den = teamOf(warn, "DEN").slots;
  warn.missing = [den[3]];
  mountWith(warn);
  const hasWarn = (code, j) => !!tiles(code)[j].querySelector(".mg-warning");
  assert.equal(hasWarn("DEN", 3), true);
  mouseDrag("DEN", 3, tileAt("DEN", 0).querySelector("img"));
  assert.equal(hasWarn("DEN", 0), true);
  assert.equal(hasWarn("DEN", 3), false);
  mouseDrag("DEN", 0, tileAt("LAL", 0).querySelector("img"));
  assert.equal(pidAt("LAL", 0), den[3]);
  assert.equal(hasWarn("LAL", 0), false);
  // retour dans sa carte d'origine, sur une autre place que la sienne : ⚠️ rétabli
  mouseDrag("LAL", 0, tileAt("DEN", 5).querySelector("img"));
  assert.equal(pidAt("DEN", 5), den[3]);
  assert.equal(hasWarn("DEN", 5), true);
  // idem par la recherche : reparti aux Lakers, puis rajouté à DEN sur une place vide
  mouseDrag("DEN", 5, tileAt("LAL", 1).querySelector("img"));
  assert.equal(hasWarn("LAL", 1), false);
  click(btn("DEN", "remove", 2));
  click(tileAt("DEN", 2));
  type(tileAt("LAL", 1).title);
  key("Enter");
  assert.equal(pidAt("DEN", 2), den[3]);
  assert.equal(hasWarn("DEN", 2), true);
  mountWith(data1);
});

test("reset d'équipe après un échange DEN ↔ LAL : James retourne à sa place chez les Lakers, toasts", () => {
  resetAll();
  const den = pidsOf("DEN");
  const lal = pidsOf("LAL");
  mouseDrag("DEN", 4, tileAt("LAL", 2).querySelector("img")); // Jokić <-> James
  const nToasts = $$(".mg-toast").length;
  click(card("DEN").querySelector('[data-action="reset-team"]'));
  assert.deepEqual(pidsOf("DEN"), den);
  assert.deepEqual(pidsOf("LAL"), lal);
  assert.deepEqual($$(".mg-toast").slice(nToasts).map((t) => t.textContent), [
    "Nikola Jokić revient aux Denver Nuggets (quitte les Los Angeles Lakers)",
    "LeBron James retourne chez les Los Angeles Lakers",
  ]);
  assert.equal($$(".mg-modified").length, 0);
  assert.deepEqual(saved().slots.LAL, lal);
  assert.deepEqual(saved().added, []);
  // place d'origine déjà prise : le joueur sort de la grille, pas de toast de retour
  mouseDrag("DEN", 4, tileAt("LAL", 2).querySelector("img"));
  click(btn("LAL", "remove", 5));
  mouseDrag("LAL", 0, tileAt("LAL", 5)); // Reaves va au 6e : LAL[0] vide
  mouseDrag("LAL", 2, tileAt("LAL", 0)); // Jokić prend la place M : la place AI de James est libre
  mouseDrag("LAL", 1, tileAt("LAL", 2)); // Dončić prend la place AI de James
  const n2 = $$(".mg-toast").length;
  click(card("DEN").querySelector('[data-action="reset-team"]'));
  assert.deepEqual(pidsOf("DEN"), den);
  assert.deepEqual($$(".mg-toast").slice(n2).map((t) => t.textContent),
    ["Nikola Jokić revient aux Denver Nuggets (quitte les Los Angeles Lakers)"]);
  assert.ok(!pidsOf("LAL").includes(lal[2]));
  resetAll();
});

test("changement de saison pendant un glisser : annulé, plus de fantôme", () => {
  resetAll();
  const src = tileAt("DEN", 0);
  const start = at(src);
  pointer("pointerdown", src, start);
  pointer("pointermove", src, { x: start.x, y: start.y + 20 });
  assert.ok($(".mg-ghost"));
  mountWith(data2);
  assert.equal($$(".mg-ghost, .mg-is-dragging").length, 0);
  const before = $(".mg-grid").innerHTML;
  pointer("pointerup", src, at(tileAt("MIA", 0))); // plus d'effet
  assert.equal($(".mg-grid").innerHTML, before);
  mountWith(data1);
  assert.equal($$(".mg-modified").length, 0);
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
