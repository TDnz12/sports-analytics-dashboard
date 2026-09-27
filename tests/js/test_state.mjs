// Fonctions d'état PURES de la grille Effectifs (MERCATO_GRID_JS de pages/2_Effectifs.py) : aucun
// accès au DOM, node seul suffit (pas de dépendance).
//
// Lancer depuis la racine du projet :  cd tests/js && node test_state.mjs
// (ou tous les tests JS :               cd tests/js && npm install && npm test)

import assert from "node:assert/strict";
import { loadGrid } from "./load_grid.mjs";

const M = await loadGrid();
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log("ok -", name); };

const data = {
  season: "2024-25",
  teams: [
    { code: "DEN", name: "Denver Nuggets", logo: null, slots: [1, 2, 3, 4, 5, 6] },
    { code: "LAL", name: "Los Angeles Lakers", logo: null, slots: [11, 12, 13, 14, 15, null] },
  ],
  players: [[1, "Jamal Murray", "DEN"], [5, "Nikola Jokić", "DEN"], [2, "Christian Braun", "DEN"],
            [3, "Michael Porter Jr.", "DEN"], [4, "Aaron Gordon", "DEN"], [6, "Russell Westbrook", "DEN"],
            [11, "Jaxson Hayes", "LAL"], [12, "Austin Reaves", "LAL"], [13, "LeBron James", "LAL"],
            [14, "Rui Hachimura", "LAL"], [15, "Anthony Davis", "LAL"], [99, "Free Agent", "BOS"]],
  missing: [4, 13],
};

test("état initial = composition d'origine, étiquettes fixes", () => {
  const s = M.initialState(data);
  assert.deepEqual(s.slots.DEN, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(s.slots.LAL, [11, 12, 13, 14, 15, null]);
  assert.deepEqual(M.SLOT_LABELS, ["M", "A", "AI", "AF", "P", "6e"]);
});

test("retrait : slot vidé, état d'origine non muté", () => {
  const s0 = M.initialState(data);
  const s1 = M.removePlayer(s0, "DEN", 0);
  assert.equal(s1.slots.DEN[0], null);
  assert.equal(s0.slots.DEN[0], 1);
  assert.equal(M.isTeamModified(s1, data, "DEN"), true);
  assert.equal(M.isTeamModified(s1, data, "LAL"), false);
});

test("ajout d'un joueur libre", () => {
  const s0 = M.initialState(data);
  const r = M.addPlayer(s0, "LAL", 5, 99);
  assert.equal(r.kind, "free");
  assert.equal(r.from, null);
  assert.equal(r.state.slots.LAL[5], 99);
  assert.ok(r.state.added.includes(99));
  assert.equal(M.addMessage(r.kind, "Free Agent", "Los Angeles Lakers"), "Free Agent rejoint les Los Angeles Lakers");
});

test("transfert : l'ancien slot devient vide, toast", () => {
  const s0 = M.initialState(data);
  const r = M.addPlayer(s0, "LAL", 5, 5);
  assert.equal(r.kind, "transfer");
  assert.equal(r.from, "DEN");
  assert.equal(r.state.slots.LAL[5], 5);
  assert.equal(r.state.slots.DEN[4], null);
  assert.equal(M.addMessage(r.kind, "Nikola Jokić", "Los Angeles Lakers", "Denver Nuggets"),
    "Nikola Jokić rejoint les Los Angeles Lakers (quitte les Denver Nuggets)");
});

test("même carte : rien ne change", () => {
  const s0 = M.removePlayer(M.initialState(data), "DEN", 0);
  const r = M.addPlayer(s0, "DEN", 0, 2);
  assert.equal(r.kind, "same");
  assert.equal(r.state, s0);
  assert.equal(M.addMessage("same", "Christian Braun", "Denver Nuggets"), "Christian Braun est déjà dans l'effectif des Denver Nuggets.");
});

test("⚠️ : joueur d'origine oui, joueur ajouté non (même transféré)", () => {
  const miss = new Set(data.missing);
  const s0 = M.initialState(data);
  assert.equal(M.showWarning(s0, miss, 4), true);
  const r = M.addPlayer(s0, "LAL", 5, 4);
  assert.equal(M.showWarning(r.state, miss, 4), false);
  assert.equal(M.showWarning(r.state, miss, 13), true);
});

test("interversion avec le voisin de droite, y compris P <-> 6e ; pas de droite pour le 6e", () => {
  const s0 = M.initialState(data);
  const s1 = M.swapRight(s0, "DEN", 0);
  assert.deepEqual(s1.slots.DEN, [2, 1, 3, 4, 5, 6]);
  const s2 = M.swapRight(s0, "DEN", 4);
  assert.deepEqual(s2.slots.DEN, [1, 2, 3, 4, 6, 5]);
  assert.equal(M.swapRight(s0, "DEN", 5), s0);
  const s3 = M.swapRight(s0, "LAL", 4); // P <-> 6e vide
  assert.deepEqual(s3.slots.LAL, [11, 12, 13, 14, null, 15]);
  // le ⚠️ suit le joueur (lié au player_id, pas au slot)
  const s4 = M.swapRight(s0, "DEN", 3);
  assert.equal(s4.slots.DEN[4], 4);
  assert.equal(M.showWarning(s4, new Set(data.missing), 4), true);
});

test("reset d'équipe : reprend le joueur transféré ailleurs, toast, ⚠️ rétabli", () => {
  const s0 = M.initialState(data);
  const t = M.addPlayer(s0, "LAL", 5, 4); // Gordon (⚠️) part aux Lakers
  const s1 = M.removePlayer(t.state, "DEN", 0);
  const r = M.resetTeam(s1, data, "DEN");
  assert.deepEqual(r.state.slots.DEN, [1, 2, 3, 4, 5, 6]);
  assert.equal(r.state.slots.LAL[5], null);
  assert.deepEqual(r.returned, [{ pid: 4, from: "LAL" }]);
  assert.equal(M.showWarning(r.state, new Set(data.missing), 4), true);
  assert.equal(M.isTeamModified(r.state, data, "DEN"), false);
  assert.equal(M.returnMessage("Aaron Gordon", "Denver Nuggets", "Los Angeles Lakers"),
    "Aaron Gordon revient aux Denver Nuggets (quitte les Los Angeles Lakers)");
});

test("reset global = état initial", () => {
  const s = M.initialState(data);
  assert.deepEqual(s, { slots: { DEN: [1, 2, 3, 4, 5, 6], LAL: [11, 12, 13, 14, 15, null] }, added: [] });
});

test("recherche insensible aux accents, préfixe devant, limite", () => {
  const idx = M.buildSearchIndex(data.players);
  assert.deepEqual(M.searchPlayers(idx, "jokic").map((p) => p.id), [5]);
  assert.deepEqual(M.searchPlayers(idx, "JOKIĆ").map((p) => p.id), [5]);
  assert.deepEqual(M.searchPlayers(idx, "").map((p) => p.id), []);
  assert.deepEqual(M.searchPlayers(idx, "lal").map((p) => p.id).sort(), [11, 12, 13, 14, 15].sort());
  assert.deepEqual(M.searchPlayers(idx, "a", 3).length, 3);
  // "ja" : Jaxson (prénom) et James (nom) commencent par la saisie, devant les autres
  const ja = M.searchPlayers(idx, "ja").map((p) => p.name);
  assert.deepEqual(ja.slice(0, 3), ["Jamal Murray", "Jaxson Hayes", "LeBron James"]);
});

test("noms de famille : suffixes, homonymes dans une carte", () => {
  assert.equal(M.lastName("Michael Porter Jr."), "Porter");
  assert.equal(M.lastName("Gary Trent Jr"), "Trent");
  assert.deepEqual(M.displayLastNames(["Jalen Williams", null, "Jaylin Williams", "Nikola Jokić"]),
    ["J. WILLIAMS", null, "J. WILLIAMS", "JOKIĆ"]);
  assert.deepEqual(M.displayLastNames(["Mark Williams", "Jalen Williams"]), ["M. WILLIAMS", "J. WILLIAMS"]);
});

test("stockage : sauvegarde/rechargement par saison, empreinte périmée ignorée", () => {
  const ls = new Map();
  const fake = { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, v) };
  const storage = M.makeStorage(fake);
  const s1 = M.removePlayer(M.initialState(data), "DEN", 2);
  M.saveState(storage, data, s1);
  assert.ok(ls.has("mercato_v1_2024-25"));
  assert.deepEqual(M.loadState(storage, data), s1);
  // autre saison : état propre, indépendant
  const data2 = { ...data, season: "2023-24" };
  assert.deepEqual(M.loadState(storage, data2), M.initialState(data2));
  // composition d'origine modifiée depuis -> état sauvegardé ignoré
  const changed = { ...data, teams: [{ ...data.teams[0], slots: [1, 2, 3, 4, 5, 7] }, data.teams[1]] };
  assert.deepEqual(M.loadState(storage, changed), M.initialState(changed));
  // JSON illisible -> origine
  ls.set("mercato_v1_2024-25", "{pas du json");
  assert.deepEqual(M.loadState(storage, data), M.initialState(data));
});

test("stockage : repli en mémoire si localStorage indisponible ou en erreur", () => {
  const broken = { getItem: () => { throw new Error("bloqué"); }, setItem: () => { throw new Error("bloqué"); } };
  for (const ls of [null, broken]) {
    const storage = M.makeStorage(ls);
    const d = { ...data, season: ls ? "1999-00" : "1998-99" };
    const s1 = M.removePlayer(M.initialState(d), "LAL", 1);
    M.saveState(storage, d, s1);
    assert.deepEqual(M.loadState(storage, d), s1);
  }
});

test("photo : portrait de la saison sous l'équipe du premier match, sinon portrait actuel seul", () => {
  const cdn = "https://cdn.nba.com/headshots/nba";
  const latest = (id) => `${cdn}/latest/1040x760/${id}.png`;
  // JSON reçu de Python : clés en texte. Le joueur 13 est dans la carte LAL mais son premier
  // match était avec l'équipe 30 (transfert) : c'est elle qui compte.
  const d = { ...data, photo_team_ids: { 5: 10, 13: 30, 99: 40 } };
  assert.deepEqual(M.headshotSources(d, 5), { src: `${cdn}/10/2024/1040x760/5.png`, fallback: latest(5) });
  assert.deepEqual(M.headshotSources(d, 13), { src: `${cdn}/30/2024/1040x760/13.png`, fallback: latest(13) });
  assert.deepEqual(M.headshotSources(d, 99), { src: `${cdn}/40/2024/1040x760/99.png`, fallback: latest(99) });
  // Joueur absent du game log, ou saison avant 2015-16 (dictionnaire vide) : portrait actuel seul
  assert.deepEqual(M.headshotSources(d, 1), { src: latest(1), fallback: null });
  assert.deepEqual(M.headshotSources({ ...d, season: "2004-05", photo_team_ids: {} }, 5), { src: latest(5), fallback: null });
});

test("adresse de l'effectif réel d'une équipe", () => {
  assert.equal(M.teamHref("2024-25", "BOS"), "?saison=2024-25&equipe=BOS");
  assert.equal(M.teamHref("2024-25", "A&B"), "?saison=2024-25&equipe=A%26B");
});

console.log(`\n${passed} tests OK`);
