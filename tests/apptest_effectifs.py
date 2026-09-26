"""Vérifie la page Effectifs (pages/2_Effectifs.py) avec AppTest : grille, clic sur un nom
d'équipe (déclencheur open_team simulé comme le navigateur), vue effectif réel, adresse
?saison=..&equipe=.., bouton retour, synchronisation avec main_season. Lit les caches de
data_cache/ sans jamais les modifier (écritures interceptées). Environ une minute.

Lancer depuis la racine du projet :  .venv/bin/python tests/apptest_effectifs.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import data_sources.nba as nba, data_sources.base as base
writes = []
nba.write_cache = base.write_cache = lambda df, path, **k: writes.append(str(path))
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetStates, WidgetState
from streamlit.components.v2.bidi_component.main import _make_trigger_id
from data_sources import SPORTS
sp = SPORTS["nba"]
PAGE = str(ROOT / "pages" / "2_Effectifs.py")
ok = lambda name: print("ok -", name)

def find(node, typ):
    kids = getattr(node, "children", None)
    if isinstance(kids, dict):
        for ch in kids.values():
            if ch.type == typ: yield ch
            yield from find(ch, typ)

def logos(at):  # éléments st.image portant une URL de logo NBA
    out = []
    def walk(n):
        for ch in (getattr(n, "children", {}) or {}).values():
            if ch.type == "image" and "logos/nba" in str(ch.proto): out.append(ch)
            walk(ch)
    walk(at._tree)
    return out

def names(at):  # noms en gras des cartes joueur
    return [m.value[2:-2] for m in at.markdown if m.value.startswith("**") and m.value.endswith("**")]

def new(params=None, state=None):
    at = AppTest.from_file(PAGE, default_timeout=120)
    for k, v in (params or {}).items(): at.query_params[k] = v
    for k, v in (state or {}).items(): at.session_state[k] = v
    return at.run()

seasons = ["2024-25", "2004-05", "1996-97", "2025-26"]
before = {s: sp.get_mercato_lineup(s).copy() for s in seasons}
before_players = {s: sp.get_player_stats(s).copy() for s in seasons}

# 1. Grille : même contrôle que l'ancien test Mercato, 4 saisons
at = new(state={"effectifs_season": seasons[0]})
for i, s in enumerate(seasons):
    if i: at.selectbox(key="effectifs_season").set_value(s).run()
    assert not at.exception, at.exception
    comps = list(find(at._tree, "bidi_component")); assert len(comps) == 1
    data = json.loads(comps[0].proto.json); assert data["season"] == s
    ids = {p[0] for p in data["players"]}
    slot_ids = [pid for t in data["teams"] for pid in t["slots"] if pid is not None]
    assert all(len(t["slots"]) == 6 for t in data["teams"]) and set(slot_ids) <= ids and len(slot_ids) == len(set(slot_ids))
    assert [t["name"] for t in data["teams"]] == sorted(t["name"] for t in data["teams"])
    assert set(data) == {"season", "teams", "players", "missing"}, "données du composant modifiées"
    print(f"   {s}: {len(data['teams'])} équipes, {len(slot_ids)} joueurs en carte")
assert at.title[0].value == "👥 Effectifs"
assert at.caption[0].value.startswith("Clique sur le nom d'une équipe pour voir son effectif complet")
ok("grille sur 4 saisons, titre et phrase d'usage, données du composant inchangées")

# 2. Données envoyées identiques à la fixture des tests JS (empreinte des sauvegardes inchangée)
at = new(state={"effectifs_season": "2024-25"})
data = json.loads(list(find(at._tree, "bidi_component"))[0].proto.json)
assert data == json.load(open(f"{ROOT}/tests/js/fixtures/grid_2024-25.json"))
ok("données 2024-25 identiques à la fixture (et à l'ancienne page Mercato)")

# 3. Clic sur un nom d'équipe simulé (déclencheur open_team, comme le navigateur)
comp = list(find(at._tree, "bidi_component"))[0]
ws = at._tree.get_widget_states()
w = ws.widgets.add(); w.id = _make_trigger_id(comp.proto.id, "events")
w.json_trigger_value = json.dumps([{"event": "open_team", "value": "BOS"}])
at._run(widget_state=ws)
assert not at.exception, at.exception
assert dict(at.query_params) == {"saison": ["2024-25"], "equipe": ["BOS"]}, dict(at.query_params)
assert at.title[0].value == "👥 Boston Celtics — Effectif réel 2024-25", at.title[0].value
assert not list(find(at._tree, "bidi_component")), "grille encore affichée"
ok("déclencheur open_team -> adresse ?saison=2024-25&equipe=BOS et vue effectif réel")

# 4. Vue effectif réel : mêmes joueurs que l'ancienne page Rosters
for code, s in [("BOS", "2024-25"), ("DEN", "2010-11"), ("LAL", "1996-97")]:
    at = new({"saison": s, "equipe": code})
    # Même règle que l'ancienne page Rosters : joueurs de get_player_stats dont l'équipe est
    # `code`. Comparés triés : AppTest parcourt les cartes colonne par colonne (grille de 5
    # colonnes), pas dans l'ordre d'affichage.
    df = sp.get_player_stats(s, period="regular")
    expected = sorted(df.loc[df["team"] == code, "player"])
    assert not at.exception
    assert sorted(names(at)) == expected and expected, (code, s)
    assert at.title[0].value.endswith(f"Effectif réel {s}")
    assert "n'apparaissent pas ici" in at.caption[0].value
    assert [b.label for b in at.button] == ["← Retour à la grille"]
    print(f"   {code} {s}: {len(names(at))} joueurs")
ok("effectif réel = joueurs de l'équipe (même règle que l'ancienne page Rosters), titre et mention 'réel'")

# 5. Franchise historique : Seattle 2004-05 (vide dans l'ancienne page Rosters)
at = new({"saison": "2004-05", "equipe": "SEA"})
assert not at.exception and at.title[0].value == "👥 Seattle SuperSonics — Effectif réel 2004-05"
assert len(names(at)) > 0 and len(logos(at)) == 0, "logo actuel affiché pour les SuperSonics"
assert len(logos(new({"saison": "2024-25", "equipe": "BOS"}))) == 1, "contrôle témoin : logo des Celtics absent"
print(f"   SEA 2004-05: {len(names(at))} joueurs, pas de logo")
ok("Seattle 2004-05 : vrai effectif, nom d'époque, pas de logo du Thunder")

# 6. Équipe inconnue, saison invalide dans l'adresse
at = new({"saison": "2024-25", "equipe": "XXX"})
assert not at.exception and "Aucune équipe « XXX »" in at.warning[0].value
at = new({"saison": "1800-01", "equipe": "BOS"}, {"main_season": "2019-20"})
assert not at.exception and at.selectbox(key="effectifs_season").value == "2019-20"
ok("équipe inconnue : message clair ; saison invalide dans l'adresse : ignorée")

# 7. Bouton retour
at = new({"saison": "2024-25", "equipe": "BOS"})
at.button[0].click().run()
assert not at.exception and dict(at.query_params) == {} and at.title[0].value == "👥 Effectifs"
assert at.selectbox(key="effectifs_season").value == "2024-25"
ok("bouton retour : adresse vidée, grille, saison conservée")

# 8. Synchronisation main_season, priorité de l'adresse, changement de saison en vue détaillée
at = new(state={"main_season": "2019-20"})
assert at.selectbox(key="effectifs_season").value == "2019-20"
at = new(state={"main_season": "Toutes les saisons"})
assert at.selectbox(key="effectifs_season").value == "2024-25"
at = new({"saison": "2015-16", "equipe": "GSW"}, {"main_season": "2019-20"})
assert at.selectbox(key="effectifs_season").value == "2015-16"
at.selectbox(key="effectifs_season").set_value("2016-17").run()
assert not at.exception and dict(at.query_params) == {"saison": ["2016-17"], "equipe": ["GSW"]}
assert at.title[0].value.endswith("Effectif réel 2016-17")
at = new({"saison": "2015-16"})
at.selectbox(key="effectifs_season").set_value("2016-17").run()
assert at.selectbox(key="effectifs_season").value == "2016-17", "adresse ?saison= seule : choix écrasé"
ok("main_season suivie par défaut, adresse prioritaire, changement de saison suivi par l'adresse")

# 9. Caches intacts, aucune écriture
for s in seasons:
    pd.testing.assert_frame_equal(sp.get_mercato_lineup(s), before[s])
    pd.testing.assert_frame_equal(sp.get_player_stats(s), before_players[s])
assert writes == [], writes
ok("caches intacts, aucune écriture disque")
print("\nTous les contrôles AppTest de la page Effectifs sont OK")
