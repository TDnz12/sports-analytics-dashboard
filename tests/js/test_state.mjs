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
  const r = M.addPlayer(s0, data, "LAL", 5, 99);
  assert.equal(r.kind, "free");
  assert.equal(r.from, null);
  assert.equal(r.state.slots.LAL[5], 99);
  assert.ok(r.state.added.includes(99));
  assert.equal(M.addMessage(r.kind, "Free Agent", "Los Angeles Lakers"), "Free Agent rejoint les Los Angeles Lakers");
});

test("transfert : l'ancien slot devient vide, toast", () => {
  const s0 = M.initialState(data);
  const r = M.addPlayer(s0, data, "LAL", 5, 5);
  assert.equal(r.kind, "transfer");
  assert.equal(r.from, "DEN");
  assert.equal(r.state.slots.LAL[5], 5);
  assert.equal(r.state.slots.DEN[4], null);
  assert.equal(M.addMessage(r.kind, "Nikola Jokić", "Los Angeles Lakers", "Denver Nuggets"),
    "Nikola Jokić rejoint les Los Angeles Lakers (quitte les Denver Nuggets)");
});

test("même carte : rien ne change", () => {
  const s0 = M.removePlayer(M.initialState(data), "DEN", 0);
  const r = M.addPlayer(s0, data, "DEN", 0, 2);
  assert.equal(r.kind, "same");
  assert.equal(r.state, s0);
  assert.equal(M.addMessage("same", "Christian Braun", "Denver Nuggets"), "Christian Braun est déjà dans l'effectif des Denver Nuggets.");
});

test("badge « ? » : joueur d'origine oui, joueur ajouté non (même transféré)", () => {
  const miss = new Set(data.missing);
  const s0 = M.initialState(data);
  assert.equal(M.showWarning(s0, miss, 4), true);
  const r = M.addPlayer(s0, data, "LAL", 5, 4);
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
  // le badge « ? » suit le joueur (lié au player_id, pas au slot)
  const s4 = M.swapRight(s0, "DEN", 3);
  assert.equal(s4.slots.DEN[4], 4);
  assert.equal(M.showWarning(s4, new Set(data.missing), 4), true);
});

test("glisser-déposer : lâché sur sa propre place ou depuis une tuile vide -> rien ne change", () => {
  const s0 = M.initialState(data);
  const own = M.moveOrSwap(s0, data, { team: "DEN", idx: 2 }, { team: "DEN", idx: 2 });
  assert.equal(own.kind, "none");
  assert.equal(own.state, s0);
  const empty = M.moveOrSwap(s0, data, { team: "LAL", idx: 5 }, { team: "DEN", idx: 0 });
  assert.equal(empty.kind, "none");
  assert.equal(empty.state, s0);
});

test("glisser-déposer dans une même carte : déplacement vers une tuile vide, échange, badge « ? » conservé", () => {
  const miss = new Set(data.missing);
  const s0 = M.removePlayer(M.initialState(data), "DEN", 0);
  const mv = M.moveOrSwap(s0, data, { team: "DEN", idx: 3 }, { team: "DEN", idx: 0 }); // Gordon (badge « ? ») -> M
  assert.equal(mv.kind, "move");
  assert.deepEqual(mv.state.slots.DEN, [4, 2, 3, null, 5, 6]);
  assert.deepEqual(mv.state.added, []);
  assert.equal(M.showWarning(mv.state, miss, 4), true);
  assert.deepEqual(s0.slots.DEN, [null, 2, 3, 4, 5, 6]); // non muté
  const sw = M.moveOrSwap(M.initialState(data), data, { team: "DEN", idx: 4 }, { team: "DEN", idx: 1 });
  assert.equal(sw.kind, "swap");
  assert.equal(sw.pid, 5);
  assert.equal(sw.other, 2);
  assert.deepEqual(sw.state.slots.DEN, [1, 5, 3, 4, 2, 6]);
  assert.deepEqual(sw.state.added, []);
  assert.equal(M.isTeamModified(sw.state, data, "LAL"), false);
});

test("glisser-déposer vers une autre carte : transfert sur tuile vide, badge « ? » retiré", () => {
  const miss = new Set(data.missing);
  const s0 = M.initialState(data);
  const r = M.moveOrSwap(s0, data, { team: "DEN", idx: 3 }, { team: "LAL", idx: 5 });
  assert.equal(r.kind, "transfer");
  assert.equal(r.pid, 4);
  assert.equal(r.other, null);
  assert.equal(r.state.slots.LAL[5], 4);
  assert.equal(r.state.slots.DEN[3], null);
  assert.deepEqual(r.state.added, [4]);
  assert.equal(M.showWarning(r.state, miss, 4), false);
  assert.equal(M.isTeamModified(r.state, data, "DEN"), true);
  assert.equal(M.isTeamModified(r.state, data, "LAL"), true);
  assert.deepEqual(s0.added, []);
});

test("glisser-déposer sur un joueur d'une autre carte : échange, les deux perdent leur badge « ? », toast", () => {
  const miss = new Set(data.missing);
  const s0 = M.initialState(data);
  const r = M.moveOrSwap(s0, data, { team: "DEN", idx: 3 }, { team: "LAL", idx: 2 }); // Gordon <-> James, badge « ? » tous deux
  assert.equal(r.kind, "trade");
  assert.equal(r.pid, 4);
  assert.equal(r.other, 13);
  assert.deepEqual(r.state.slots.DEN, [1, 2, 3, 13, 5, 6]);
  assert.deepEqual(r.state.slots.LAL, [11, 12, 4, 14, 15, null]);
  assert.deepEqual(r.state.added.slice().sort((a, b) => a - b), [4, 13]);
  assert.equal(M.showWarning(r.state, miss, 4), false);
  assert.equal(M.showWarning(r.state, miss, 13), false);
  assert.deepEqual(s0.slots.DEN, [1, 2, 3, 4, 5, 6]);
  assert.equal(M.tradeMessage("Nikola Jokić", "LeBron James", "DEN", "LAL"), "Échange : Jokić ↔ James (DEN ↔ LAL)");
  assert.equal(M.tradeMessage("Michael Porter Jr.", "LeBron James", "DEN", "LAL"), "Échange : Porter ↔ James (DEN ↔ LAL)");
});

test("glisser-déposer : format de sauvegarde inchangé, relu tel quel", () => {
  const ls = new Map();
  const fake = { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, v) };
  const storage = M.makeStorage(fake);
  const d = { ...data, season: "2010-11" };
  const r = M.moveOrSwap(M.initialState(d), d, { team: "DEN", idx: 4 }, { team: "LAL", idx: 0 });
  M.saveState(storage, d, r.state);
  const saved = JSON.parse(ls.get("mercato_v1_2010-11"));
  assert.deepEqual(Object.keys(saved), ["fp", "slots", "added"]);
  assert.equal(saved.fp, M.fingerprint(d));
  assert.deepEqual(M.loadState(storage, d), r.state);
});

test("défilement automatique : nul au centre, négatif en haut, positif en bas, plafonné", () => {
  assert.equal(M.autoScrollStep(400, 800), 0);
  assert.equal(M.autoScrollStep(60, 800), 0);
  assert.equal(M.autoScrollStep(740, 800), 0);
  assert.ok(M.autoScrollStep(30, 800) < 0);
  assert.ok(M.autoScrollStep(770, 800) > 0);
  assert.ok(M.autoScrollStep(790, 800) > M.autoScrollStep(750, 800));
  assert.equal(M.autoScrollStep(0, 800), -18);
  assert.equal(M.autoScrollStep(800, 800), 18);
  assert.equal(M.autoScrollStep(-50, 800), -18);
  assert.equal(M.autoScrollStep(900, 800), 18);
});

test("reset d'équipe : reprend le joueur transféré ailleurs, toast, badge « ? » rétabli", () => {
  const s0 = M.initialState(data);
  const t = M.addPlayer(s0, data, "LAL", 5, 4); // Gordon (badge « ? ») part aux Lakers
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

test("reset après un échange entre cartes : chacun retrouve sa place d'origine, badges « ? » rétablis", () => {
  const miss = new Set(data.missing);
  const t = M.moveOrSwap(M.initialState(data), data, { team: "DEN", idx: 4 }, { team: "LAL", idx: 2 }); // Jokić <-> James
  const r = M.resetTeam(t.state, data, "DEN");
  assert.deepEqual(r.state.slots.DEN, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(r.state.slots.LAL, [11, 12, 13, 14, 15, null]);
  assert.deepEqual(r.returned, [{ pid: 5, from: "LAL" }]);
  assert.deepEqual(r.restored, [{ pid: 13, to: "LAL" }]);
  assert.deepEqual(r.state.added, []);
  assert.equal(M.showWarning(r.state, miss, 13), true);
  assert.equal(M.isTeamModified(r.state, data, "LAL"), false);
  assert.equal(M.restoreMessage("LeBron James", "Los Angeles Lakers"), "LeBron James retourne chez les Los Angeles Lakers");
});

test("reset : joueur venu d'ailleurs dont la place d'origine est prise, ou sans carte d'origine -> sort", () => {
  let s = M.addPlayer(M.initialState(data), data, "DEN", 0, 13).state; // James -> DEN (LAL[2] vide)
  s = M.addPlayer(s, data, "LAL", 2, 99).state; // agent libre à sa place
  s = M.addPlayer(s, data, "DEN", 1, 12).state; // Reaves -> DEN, LAL[1] reste vide
  s = M.removePlayer(s, "DEN", 2);
  s = M.addPlayer(s, data, "DEN", 2, 98).state; // joueur hors grille
  const r = M.resetTeam(s, data, "DEN");
  assert.deepEqual(r.state.slots.DEN, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(r.state.slots.LAL, [11, 12, 99, 14, 15, null]); // Reaves rentre, James non
  assert.deepEqual(r.restored, [{ pid: 12, to: "LAL" }]);
  assert.equal(M.findPlayer(r.state, 13), null);
  assert.equal(M.findPlayer(r.state, 98), null);
  assert.ok(!r.state.added.includes(12));
});

test("retour dans sa carte d'origine (glisser, échange, recherche) : retiré de added, badge « ? » rétabli", () => {
  const miss = new Set(data.missing);
  // glisser : Gordon (badge « ? ») part aux Lakers, puis revient à DEN sur une AUTRE place (échange avec Murray)
  const out = M.moveOrSwap(M.initialState(data), data, { team: "DEN", idx: 3 }, { team: "LAL", idx: 5 });
  assert.equal(M.showWarning(out.state, miss, 4), false);
  const back = M.moveOrSwap(out.state, data, { team: "LAL", idx: 5 }, { team: "DEN", idx: 0 });
  assert.equal(back.kind, "trade");
  assert.equal(back.state.slots.DEN[0], 4);
  assert.equal(M.showWarning(back.state, miss, 4), true);
  assert.deepEqual(back.state.added, [1]); // Murray, lui, a quitté sa carte
  // échange aller puis retour : les deux sont chez eux, added vide
  const t1 = M.moveOrSwap(M.initialState(data), data, { team: "DEN", idx: 3 }, { team: "LAL", idx: 2 });
  const t2 = M.moveOrSwap(t1.state, data, { team: "DEN", idx: 3 }, { team: "LAL", idx: 2 });
  assert.deepEqual(t2.state, M.initialState(data));
  // recherche : Gordon aux Lakers puis rajouté à DEN, sur une place vide quelconque
  const a1 = M.addPlayer(M.initialState(data), data, "LAL", 5, 4);
  const a2 = M.addPlayer(M.removePlayer(a1.state, "DEN", 5), data, "DEN", 5, 4);
  assert.equal(a2.kind, "transfer");
  assert.deepEqual(a2.state.added, []);
  assert.equal(M.showWarning(a2.state, miss, 4), true);
  // déplacement dans une carte qui n'est pas la sienne : reste dans added
  const m = M.moveOrSwap(a1.state, data, { team: "LAL", idx: 5 }, { team: "LAL", idx: 0 });
  assert.deepEqual(m.state.added, [4]);
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
