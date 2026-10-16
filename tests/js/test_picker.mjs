// Liste de recherche de joueurs (player_picker/player_picker.js) : fonctions de recherche pures,
// puis rendu, souris et clavier dans un DOM simulé (jsdom), monté dans un shadow DOM comme le fait
// Streamlit.
//
// Lancer depuis la racine du projet :  cd tests/js && npm install && node test_picker.mjs
// (ou tous les tests JS :               cd tests/js && npm install && npm test)

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

// Le fichier du composant est chargé tel quel comme module ES (copie .mjs : le dossier du projet
// n'a pas de package.json "type": "module").
const source = readFileSync(new URL("../../player_picker/player_picker.js", import.meta.url), "utf8");
const file = join(mkdtempSync(join(tmpdir(), "picker-")), "player_picker.mjs");
writeFileSync(file, source);

const dom = new JSDOM("<!doctype html><body><div id=a></div><div id=b></div><div id=c></div><div id=d></div><div id=e></div></body>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
const P = await import(pathToFileURL(file).href);

let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log("ok -", name); };

// --- 1. Recherche pure ------------------------------------------------------------------------
const RUGBY = [
  ["icw:199515", "Gaël Fickou (Racing 92) · Centre"],
  ["icw:1", "Antoine Dupont (Toulouse) · Demi de mêlée"],
  ["icw:2", "Gaëtan Barlot (Castres) · Talonneur"],
  ["icw:3", "Romain Ntamack (Toulouse) · Demi d'ouverture"],
];
const NBA = ["Luka Dončić", "Nikola Jokić", "Luka Garza", "LeBron James", "Stephen Curry",
             "Shai Gilgeous-Alexander"].map((n) => [n, n]);

test("normalize : accents et casse ignorés, comme la grille Effectifs", () => {
  assert.equal(P.normalize("Gaël FICKOU"), "gael fickou");
  assert.equal(P.normalize("Dončić"), "doncic");
  assert.deepEqual(P.queryWords("  Fickou  GAËL "), ["fickou", "gael"]);
});

test("« gael » et « fickou gael » trouvent Gaël Fickou ; « doncic » trouve Luka Dončić", () => {
  const r = P.buildIndex(RUGBY);
  assert.deepEqual(P.searchOptions(r, "gael").map((o) => o.key), ["icw:199515"]);
  assert.deepEqual(P.searchOptions(r, "fickou gael").map((o) => o.key), ["icw:199515"]);
  assert.deepEqual(P.searchOptions(r, "toulouse demi").map((o) => o.key), ["icw:1", "icw:3"]);
  assert.deepEqual(P.searchOptions(r, "melee").map((o) => o.key), ["icw:1"]);
  const n = P.buildIndex(NBA);
  assert.deepEqual(P.searchOptions(n, "doncic").map((o) => o.key), ["Luka Dončić"]);
  assert.deepEqual(P.searchOptions(n, "DONČIĆ").map((o) => o.key), ["Luka Dončić"]);
  assert.equal(P.searchOptions(n, "").length, NBA.length);
  assert.deepEqual(P.searchOptions(n, "luka", new Set(["Luka Dončić"])).map((o) => o.key), ["Luka Garza"]);
  assert.deepEqual(P.searchOptions(n, "zzzz"), []);
});

test("mise en évidence : parties trouvées, accents d'origine gardés", () => {
  assert.deepEqual(P.highlightParts("Gaël Fickou", "gael"), [["Gaël", true], [" Fickou", false]]);
  assert.deepEqual(P.highlightParts("Luka Dončić", "doncic"), [["Luka ", false], ["Dončić", true]]);
  assert.deepEqual(P.highlightParts("Gaël Fickou", ""), [["Gaël Fickou", false]]);
});

// --- 2. Rendu, souris, clavier ----------------------------------------------------------------
function mount(hostId, data) {
  const shadow = document.getElementById(hostId).attachShadow({ mode: "open" });
  // sent : [événement, clés] ; seqs : numéros des changements envoyés.
  const sent = [];
  const seqs = [];
  const setTriggerValue = (e, v) => { sent.push([e, v.keys]); seqs.push(v.seq); };
  const cleanup = P.default({ data, parentElement: shadow, setTriggerValue });
  const $ = (sel) => shadow.querySelector(sel);
  const $$ = (sel) => [...shadow.querySelectorAll(sel)];
  const input = $(".pp-input");
  const type = (text) => { input.focus(); input.value = text; input.dispatchEvent(new window.Event("input", { bubbles: true })); };
  const key = (k) => input.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  const click = (node) => node.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const options = () => $$(".pp-option").map((li) => li.textContent);
  const rerender = (next) => P.default({ data: next, parentElement: shadow, setTriggerValue });
  // Modifications du DOM des pastilles et du nom affiché, relevées de façon synchrone.
  const observer = new window.MutationObserver(() => {});
  observer.observe(shadow, { childList: true, subtree: true, characterData: true });
  const valueChanges = () => observer.takeRecords().filter((r) => {
    const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
    return t && (t.closest(".pp-values") || t.classList.contains("pp-values"));
  });
  return { shadow, sent, seqs, $, $$, input, type, key, click, options, rerender, cleanup, valueChanges };
}
const TEXTS = { empty: "Aucun joueur trouvé", remove: "Retirer", clear: "Désélectionner",
                full: "4 joueurs au maximum : retire un joueur pour en ajouter un." };

// Dashboard : un joueur
const single = mount("a", { options: NBA, selected: [], max: 1, label: "Rechercher un joueur",
                            placeholder: "ex. doncic", texts: TEXTS });

test("Dashboard : étiquette, placeholder, aucune étiquette technique, liste fermée", () => {
  assert.equal(single.$(".pp-label").textContent, "Rechercher un joueur");
  assert.equal(single.input.placeholder, "ex. doncic");
  assert.equal(single.$(".pp-menu").hidden, true);
  assert.equal(single.$(".pp-clear").hidden, true);
  assert.ok(!single.shadow.textContent.includes("player_picker"));
});

test("Dashboard : taper filtre à chaque lettre sans rien renvoyer à Python", () => {
  single.type("do");
  assert.equal(single.$(".pp-menu").hidden, false);
  single.type("doncic");
  assert.deepEqual(single.options(), ["Luka Dončić"]);
  assert.equal(single.$(".pp-option mark").textContent, "Dončić");
  assert.deepEqual(single.sent, []);
});

test("Dashboard : Entrée sélectionne, case vidée, nom affiché, croix visible", () => {
  single.key("Enter");
  assert.deepEqual(single.sent, [["selection", ["Luka Dončić"]]]);
  assert.equal(single.input.value, "");
  assert.equal(single.$(".pp-menu").hidden, true);
  assert.equal(single.$(".pp-single").textContent, "Luka Dončić");
  assert.equal(single.$(".pp-single").hidden, false);
  assert.equal(single.$(".pp-clear").hidden, false);
  assert.equal(single.input.placeholder, "");
});

test("Dashboard : taper n'efface pas le joueur sélectionné ; Échap ferme et vide la case", () => {
  single.type("jokic");
  assert.equal(single.$(".pp-single").hidden, true);
  single.key("Escape");
  assert.equal(single.input.value, "");
  assert.equal(single.$(".pp-menu").hidden, true);
  assert.equal(single.$(".pp-single").textContent, "Luka Dončić");
  assert.equal(single.sent.length, 1);
});

test("Dashboard : clic sur une option remplace le joueur ; même joueur : rien renvoyé", () => {
  single.type("luka");
  const garza = single.$$(".pp-option").find((li) => li.textContent === "Luka Garza");
  single.click(garza);
  assert.deepEqual(single.sent.at(-1), ["selection", ["Luka Garza"]]);
  single.type("garza");
  single.key("Enter");
  assert.equal(single.sent.length, 2);
});

test("Dashboard : croix pour désélectionner", () => {
  single.click(single.$(".pp-clear"));
  assert.deepEqual(single.sent.at(-1), ["selection", []]);
  assert.equal(single.$(".pp-clear").hidden, true);
  assert.equal(single.input.placeholder, "ex. doncic");
});

test("Dashboard : valeur venue de Python (présélection, saison) affichée sans rien renvoyer", () => {
  const before = single.sent.length;
  single.rerender({ options: NBA, selected: ["Nikola Jokić"], max: 1, label: "Rechercher un joueur",
                    placeholder: "ex. doncic", texts: TEXTS, seq: 3, epoch: 1 });
  assert.equal(single.$(".pp-single").textContent, "Nikola Jokić");
  assert.equal(single.sent.length, before);
});

test("Dashboard : « Aucun joueur trouvé », flèches qui bouclent", () => {
  single.type("zzzz");
  assert.deepEqual(single.options(), []);
  assert.equal(single.$(".pp-empty").textContent, "Aucun joueur trouvé");
  single.type("luka");
  assert.equal(single.$(".pp-active").textContent, "Luka Dončić");
  single.key("ArrowDown");
  assert.equal(single.$(".pp-active").textContent, "Luka Garza");
  single.key("ArrowDown");
  assert.equal(single.$(".pp-active").textContent, "Luka Dončić");
  single.key("ArrowUp");
  assert.equal(single.$(".pp-active").textContent, "Luka Garza");
  single.key("Escape");
});

// Radar : jusqu'à 4 joueurs
const radar = mount("b", { options: RUGBY.concat(NBA), selected: ["icw:1", "icw:3"], max: 4,
                           label: "Joueurs (1 à 4)", placeholder: "ex. gael", texts: TEXTS });
const chips = () => radar.$$(".pp-chip-text").map((c) => c.textContent);

test("Radar : joueurs choisis en pastilles, déjà choisis non proposés", () => {
  assert.deepEqual(chips(), ["Antoine Dupont (Toulouse) · Demi de mêlée", "Romain Ntamack (Toulouse) · Demi d'ouverture"]);
  radar.type("toulouse");
  assert.deepEqual(radar.options(), []);
  radar.key("Escape");
});

test("Radar : taper ne touche jamais à la sélection (Retour arrière compris)", () => {
  radar.type("g");
  radar.type("ga");
  radar.input.value = "";
  radar.key("Backspace");
  radar.key("Backspace");
  assert.deepEqual(radar.sent, []);
  assert.equal(chips().length, 2);
  radar.key("Escape");
});

test("Radar : « fickou gael » puis Entrée ajoute Gaël Fickou", () => {
  radar.type("fickou gael");
  assert.deepEqual(radar.options(), ["Gaël Fickou (Racing 92) · Centre"]);
  radar.key("Enter");
  assert.deepEqual(radar.sent.at(-1), ["selection", ["icw:1", "icw:3", "icw:199515"]]);
  assert.equal(chips().length, 3);
  assert.equal(radar.input.value, "");
});

test("Radar : croix d'une pastille retire le joueur", () => {
  const remove = radar.$$(".pp-chip-remove")[0];
  assert.equal(remove.getAttribute("aria-label"), "Retirer Antoine Dupont (Toulouse) · Demi de mêlée");
  radar.click(remove);
  assert.deepEqual(radar.sent.at(-1), ["selection", ["icw:3", "icw:199515"]]);
  assert.equal(chips().length, 2);
});

test("Radar : limite de 4, message et ajout refusé (clavier et souris)", () => {
  radar.type("doncic"); radar.key("Enter");
  radar.type("jokic"); radar.key("Enter");
  assert.equal(chips().length, 4);
  const sent = radar.sent.length;
  radar.type("curry");
  assert.equal(radar.$(".pp-notice").textContent, "4 joueurs au maximum : retire un joueur pour en ajouter un.");
  assert.equal(radar.$(".pp-option").getAttribute("aria-disabled"), "true");
  radar.key("Enter");
  radar.click(radar.$(".pp-option"));
  assert.equal(radar.sent.length, sent);
  assert.equal(chips().length, 4);
  radar.key("Escape");
});

test("Radar : la sélection envoyée par Python remplace celle affichée", () => {
  radar.rerender({ options: RUGBY.concat(NBA), selected: ["Stephen Curry"], max: 4,
                   label: "Joueurs (1 à 4)", placeholder: "ex. gael", texts: TEXTS, seq: 4, epoch: 1 });
  assert.deepEqual(chips(), ["Stephen Curry"]);
});

// --- 3. Synchronisation sans clignotement --------------------------------------------------
test("acceptSelection : montage, à jour, en retard, imposée par Python", () => {
  assert.deepEqual(P.acceptSelection(null, { seq: 6, epoch: 2 }), [true, { seq: 6, epoch: 2 }]);
  assert.deepEqual(P.acceptSelection({ seq: 3, epoch: 0 }, { seq: 3, epoch: 0 }), [true, { seq: 3, epoch: 0 }]);
  assert.deepEqual(P.acceptSelection({ seq: 3, epoch: 0 }, { seq: 2, epoch: 0 }), [false, { seq: 3, epoch: 0 }]);
  assert.deepEqual(P.acceptSelection({ seq: 3, epoch: 0 }, { seq: 2, epoch: 1 }), [true, { seq: 3, epoch: 1 }]);
  assert.deepEqual(P.acceptSelection({ seq: 0, epoch: 0 }, {}), [true, { seq: 0, epoch: 0 }]);
});

const BASE = { options: RUGBY.concat(NBA), max: 4, label: "Joueurs (1 à 4)", placeholder: "ex. gael", texts: TEXTS };
const late = mount("c", { ...BASE, selected: ["icw:1"], seq: 0, epoch: 0 });
const lateChips = () => late.$$(".pp-chip-text").map((c) => c.textContent.split(" (")[0]);

test("Radar : sélection en retard reçue juste après un clic, ignorée sans toucher au DOM", () => {
  late.type("fickou");
  late.key("Enter");
  assert.deepEqual(late.sent, [["selection", ["icw:1", "icw:199515"]]]);
  assert.deepEqual(late.seqs, [1]);
  late.valueChanges();
  // Run déclenché avant que Python ne reçoive le clic : ancienne sélection, numéro 0.
  late.rerender({ ...BASE, selected: ["icw:1"], seq: 0, epoch: 0 });
  assert.deepEqual(late.valueChanges(), [], "la case a bougé : clignotement");
  assert.deepEqual(lateChips(), ["Antoine Dupont", "Gaël Fickou"]);
  // Run suivant : Python a reçu le clic (numéro 1) et renvoie la nouvelle sélection.
  late.rerender({ ...BASE, selected: ["icw:1", "icw:199515"], seq: 1, epoch: 0 });
  assert.deepEqual(late.valueChanges(), []);
  assert.deepEqual(lateChips(), ["Antoine Dupont", "Gaël Fickou"]);
});

test("Radar : deux clics rapides, sélections en retard des deux runs ignorées", () => {
  late.click(late.$$(".pp-chip-remove")[0]);                 // numéro 2
  late.type("doncic"); late.key("Enter");                    // numéro 3
  assert.deepEqual(late.seqs, [1, 2, 3]);
  late.valueChanges();
  late.rerender({ ...BASE, selected: ["icw:1", "icw:199515"], seq: 1, epoch: 0 });
  late.rerender({ ...BASE, selected: ["icw:199515"], seq: 2, epoch: 0 });
  assert.deepEqual(late.valueChanges(), []);
  assert.deepEqual(lateChips(), ["Gaël Fickou", "Luka Dončić"]);
  late.rerender({ ...BASE, selected: ["icw:199515", "Luka Dončić"], seq: 3, epoch: 0 });
  assert.deepEqual(lateChips(), ["Gaël Fickou", "Luka Dončić"]);
});

test("Radar : sélection imposée par Python (epoch plus grande) toujours appliquée", () => {
  late.type("jokic"); late.key("Enter");                     // numéro 4, pas encore reçu
  late.rerender({ ...BASE, selected: ["Stephen Curry"], seq: 3, epoch: 1 });
  assert.deepEqual(lateChips(), ["Stephen Curry"]);
  late.type("curry gilgeous"); late.type("shai"); late.key("Enter");   // le numéro continue : 5
  assert.deepEqual(late.seqs.at(-1), 5);
});

test("Retour sur la page : la case repart du numéro de Python", () => {
  late.cleanup();
  const again = mount("d", { ...BASE, selected: ["icw:3"], seq: 5, epoch: 1 });
  assert.deepEqual(again.$$(".pp-chip-text").map((c) => c.textContent.split(" (")[0]), ["Romain Ntamack"]);
  again.type("dupont"); again.key("Enter");
  assert.deepEqual(again.seqs, [6]);
  again.cleanup();
});

test("Dashboard : nom en retard ignoré, sans clignotement", () => {
  const dash = mount("e", { options: NBA, selected: [], max: 1, label: "Rechercher un joueur",
                            placeholder: "ex. doncic", texts: TEXTS, seq: 0, epoch: 0 });
  dash.type("doncic"); dash.key("Enter");
  dash.valueChanges();
  dash.rerender({ options: NBA, selected: [], max: 1, label: "Rechercher un joueur",
                  placeholder: "ex. doncic", texts: TEXTS, seq: 0, epoch: 0 });
  assert.deepEqual(dash.valueChanges(), []);
  assert.equal(dash.$(".pp-single").textContent, "Luka Dončić");
  assert.equal(dash.$(".pp-clear").hidden, false);
  dash.cleanup();
});

test("Nettoyage : la liste est retirée du DOM", () => {
  radar.cleanup();
  assert.equal(radar.$(".pp-root"), null);
});

console.log(`\n${passed} tests de la liste de recherche de joueurs OK`);
