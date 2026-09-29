"""Vérifie la page Effectifs (pages/2_Effectifs.py) avec AppTest : grille, clic sur un nom
d'équipe (déclencheur open_team simulé comme le navigateur), vue effectif réel, adresse
?saison=..&equipe=.., bouton retour, synchronisation avec main_season. Lit les caches de
data_cache/ sans jamais les modifier (écritures interceptées). Environ une minute.

Lancer depuis la racine du projet :  .venv/bin/python tests/apptest_effectifs.py
"""

import json
import pathlib
import re
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

def logos(at):  # adresses des logos de la vue effectif réel (disque clair, en HTML)
    return re.findall(r'class="team-logo-disc"><img src="([^"]+)"', "".join(m.value for m in at.markdown))

LOGO_NOTICE = "Logos : propriété de la NBA et de ses équipes, utilisés à titre non commercial."
PHOTO_NOTICE = ("Photos : portrait de la saison à partir de 2015-16 quand il existe, sinon portrait "
                "le plus récent du joueur.")
CDN = "https://cdn.nba.com/headshots/nba"

def photos(at):  # (src, repli) des photos de la vue effectif réel
    return re.findall(r'class="roster-photo-box"><img src="([^"]+)"(?: data-fallback="([^"]+)")?',
                      "".join(m.value for m in at.markdown))

def fallback_scripts(at):  # st.html du repli des photos (vue effectif réel)
    return [h.proto for h in find(at._tree, "html")]

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
    assert set(data) == {"season", "teams", "players", "missing", "photo_team_ids"}, "données du composant modifiées"
    # Portraits de saison : équipe du premier match, à partir de 2015-16 seulement (clés en texte : JSON).
    if int(s[:4]) >= 2015:
        first = sp.get_first_game_teams(s)
        assert data["photo_team_ids"] == {str(p): t for p, t in zip(first["player_id"], first["team_id"])}
        assert set(map(str, slot_ids)) <= set(data["photo_team_ids"])
    else:
        assert data["photo_team_ids"] == {}
    # Logos d'époque servis localement (static/), pour toutes les équipes de la saison.
    for t in data["teams"]:
        assert t["logo"] and t["logo"].startswith("app/static/logos/nba/"), (s, t["code"], t["logo"])
        assert (ROOT / "static" / t["logo"][len("app/static/"):]).is_file(), t["logo"]
    print(f"   {s}: {len(data['teams'])} équipes, {len(slot_ids)} joueurs en carte, logos locaux")
assert at.title[0].value == "Effectifs"
assert at.caption[0].value.startswith("Clique sur le nom d'une équipe pour voir son effectif complet")
assert at.caption[-1].value == LOGO_NOTICE, "mention des logos absente en bas de la grille"
assert at.caption[-2].value == PHOTO_NOTICE, "mention des photos absente en bas de la grille"
ok("grille sur 4 saisons, titre et phrase d'usage, logos locaux, portraits de saison dès 2015-16, mentions en bas")

# 1 bis. Logos d'époque dans la grille (saison 2003-04 : dinosaure des Raptors, Jazz 1996, Sonics)
at = new(state={"effectifs_season": "2003-04"})
logo_of = {t["code"]: t["logo"] for t in json.loads(list(find(at._tree, "bidi_component"))[0].proto.json)["teams"]}
assert logo_of["TOR"].endswith("/1995_toronto-raptors.png") and logo_of["UTA"].endswith("/1996_utah-jazz.png")
assert logo_of["SEA"].endswith("/2001_seattle-supersonics.png") and logo_of["IND"].endswith("/1990_indiana-pacers.png")
ok("grille 2003-04 : logos d'époque (Raptors, Jazz, SuperSonics, Pacers)")

# 2. Données envoyées identiques à la fixture des tests JS (empreinte des sauvegardes inchangée)
at = new(state={"effectifs_season": "2024-25"})
data = json.loads(list(find(at._tree, "bidi_component"))[0].proto.json)
assert data == json.load(open(f"{ROOT}/tests/js/fixtures/grid_2024-25.json"))
ok("données 2024-25 identiques à la fixture des tests JS")

# 3. Clic sur un nom d'équipe simulé (déclencheur open_team, comme le navigateur)
comp = list(find(at._tree, "bidi_component"))[0]
ws = at._tree.get_widget_states()
w = ws.widgets.add(); w.id = _make_trigger_id(comp.proto.id, "events")
w.json_trigger_value = json.dumps([{"event": "open_team", "value": "BOS"}])
at._run(widget_state=ws)
assert not at.exception, at.exception
assert dict(at.query_params) == {"saison": ["2024-25"], "equipe": ["BOS"]}, dict(at.query_params)
assert at.title[0].value == "Boston Celtics — Effectif réel 2024-25", at.title[0].value
assert not list(find(at._tree, "bidi_component")), "grille encore affichée"
ok("déclencheur open_team -> adresse ?saison=2024-25&equipe=BOS et vue effectif réel")

# 4. Vue effectif réel : joueurs dont le DERNIER match de la saison est avec l'équipe (game log),
# équipe NBA d'origine pour un joueur sans match dans le log (voir nba._with_final_game_team).
for code, s in [("BOS", "2024-25"), ("MEM", "2024-25"), ("DEN", "2010-11"), ("LAL", "1996-97")]:
    at = new({"saison": s, "equipe": code})
    # Attendu recalculé depuis les caches BRUTS (pas depuis get_player_stats, qui est testé).
    # Comparés triés : AppTest parcourt les cartes colonne par colonne (grille de 5 colonnes),
    # pas dans l'ordre d'affichage.
    raw = pd.read_parquet(ROOT / "data_cache" / "raw" / "nba" / "nba_api" / f"{s}.parquet")
    log = pd.read_parquet(ROOT / "data_cache" / "raw" / "nba" / "nba_api" / f"game_log_{s}.parquet")
    last = log.sort_values("game_date").drop_duplicates("player_id", keep="last").set_index("player_id")["team"]
    final_team = raw["player_id"].map(last).fillna(raw["team"])
    expected = sorted(raw.loc[final_team == code, "player"])
    assert not at.exception
    assert sorted(names(at)) == expected and expected, (code, s)
    assert at.title[0].value.endswith(f"Effectif réel {s}")
    assert "n'apparaissent pas ici" in at.caption[0].value
    assert [b.label for b in at.button] == ["← Retour à la grille"]
    if (code, s) == ("MEM", "2024-25"):
        assert "Desmond Bane" in names(at), "Bane (échangé à ORL en juin 2025) doit être à MEM en 2024-25"
    print(f"   {code} {s}: {len(names(at))} joueurs")
at = new({"saison": "2024-25", "equipe": "ORL"})
assert "Desmond Bane" not in names(at) and "Kentavious Caldwell-Pope" in names(at)
ok("effectif réel = équipe du dernier match (Bane à MEM, pas à ORL, en 2024-25), titre et mention 'réel'")

# 5. Franchise historique : Seattle 2004-05 (vide dans l'ancienne page Rosters)
at = new({"saison": "2004-05", "equipe": "SEA"})
assert not at.exception and at.title[0].value == "Seattle SuperSonics — Effectif réel 2004-05"
assert len(names(at)) > 0 and logos(at) == ["app/static/logos/nba/2001_seattle-supersonics.png"], logos(at)
assert at.caption[-1].value == LOGO_NOTICE, "mention des logos absente en bas de la vue effectif"
assert logos(new({"saison": "2024-25", "equipe": "BOS"})) == ["app/static/logos/nba/1996_boston-celtics.svg"]
print(f"   SEA 2004-05: {len(names(at))} joueurs, logo des SuperSonics 2001-2008")
ok("Seattle 2004-05 : vrai effectif, nom et logo d'époque sur disque clair, mention en bas")

# 5 bis. Photos de la vue effectif réel : portrait de la saison (équipe du premier match) avec
# repli sur le portrait actuel à partir de 2015-16, portrait actuel seul avant.
at = new({"saison": "2023-24", "equipe": "IND"})
first = dict(zip(sp.get_first_game_teams("2023-24")["player_id"], sp.get_first_game_teams("2023-24")["team_id"]))
ph = photos(at)
assert ph and len(ph) == len(names(at)), (len(ph), len(names(at)))
for src, fb in ph:
    pid = int(fb.rsplit("/", 1)[1][:-4])
    assert fb == f"{CDN}/latest/1040x760/{pid}.png" and src == f"{CDN}/{first[pid]}/2023/1040x760/{pid}.png", (src, fb)
siakam = int(sp.get_player_stats("2023-24").set_index("player").loc["Pascal Siakam", "player_id"])
assert (f"{CDN}/1610612761/2023/1040x760/{siakam}.png", f"{CDN}/latest/1040x760/{siakam}.png") in ph, "Siakam sous TOR"
scripts = fallback_scripts(at)
assert len(scripts) == 1 and scripts[0].unsafe_allow_javascript and "data-fallback" in scripts[0].body
assert at.caption[-2].value == PHOTO_NOTICE and at.caption[-1].value == LOGO_NOTICE
at = new({"saison": "2004-05", "equipe": "SEA"})
assert photos(at) and all(src.startswith(f"{CDN}/latest/") and not fb for src, fb in photos(at))
assert fallback_scripts(at) == [] and at.caption[-2].value == PHOTO_NOTICE
ok("photos : IND 2023-24 portrait de saison + repli (Siakam sous TOR), SEA 2004-05 portrait actuel seul")

# 6. Équipe inconnue, saison invalide dans l'adresse
at = new({"saison": "2024-25", "equipe": "XXX"})
assert not at.exception and "Aucune équipe « XXX »" in at.warning[0].value
at = new({"saison": "1800-01", "equipe": "BOS"}, {"main_season": "2019-20"})
assert not at.exception and at.selectbox(key="effectifs_season").value == "2019-20"
ok("équipe inconnue : message clair ; saison invalide dans l'adresse : ignorée")

# 7. Bouton retour
at = new({"saison": "2024-25", "equipe": "BOS"})
at.button[0].click().run()
assert not at.exception and dict(at.query_params) == {} and at.title[0].value == "Effectifs"
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
