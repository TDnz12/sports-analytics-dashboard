"""Vérifie la page Radar de comparaison (pages/1_Radar_de_comparaison.py) avec AppTest : sélection
de 1 à 4 joueurs (cartes, tracés, couleurs), limite à 4, sélection vidée, changement de saison,
présélection depuis le Dashboard, axe "Protection du ballon" et formats du tableau récap. Lit les
caches de data_cache/ sans jamais les modifier (écritures interceptées).

Lancer depuis la racine du projet :  .venv/bin/python tests/apptest_radar.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import data_sources.nba as nba, data_sources.base as base
writes = []
nba.write_cache = base.write_cache = lambda df, path, **k: writes.append(str(path))
from streamlit.testing.v1 import AppTest

PAGE = str(ROOT / "pages" / "1_Radar_de_comparaison.py")
ok = lambda name: print("ok -", name)
FOUR = ["Shai Gilgeous-Alexander", "Luka Dončić", "Nikola Jokić", "Victor Wembanyama"]


def new(state=None):
    at = AppTest.from_file(PAGE, default_timeout=120)
    for k, v in (state or {}).items(): at.session_state[k] = v
    return at.run()


def traces(at):  # tracés du radar (figure Plotly sérialisée)
    return spec(at)["data"]


def cards(at):  # noms des cartes d'en-tête, avec la couleur de leur bordure
    return [(m.value.split("font-size: 1.05rem;\">")[1].split("<")[0], m.value.split("solid ")[1].split(";")[0])
            for m in at.markdown if "border-left: 4px solid" in m.value]


def recap(at):
    return at.dataframe[0].value.set_index("Joueur")


def spec(at):
    return json.loads(at.get("plotly_chart")[0].proto.spec)


# 1. Ouverture par défaut : un joueur, saison 2024-25
at = new()
assert not at.exception, at.exception
ms = at.multiselect(key="radar_players")
assert at.selectbox(key="radar_season").value == "2024-25" and len(ms.value) == 1
assert len(traces(at)) == 1 and len(cards(at)) == 1
ok("ouverture : un joueur, une carte, un tracé")

# 2. Quatre joueurs : couleurs distinctes, remplissage transparent, valeurs au survol seulement
ms.set_value(FOUR).run()
assert not at.exception, at.exception
data = traces(at)
assert [t["name"] for t in data] == FOUR
colors = [t["line"]["color"] for t in data]
assert len(set(colors)) == 4 and [c for _, c in cards(at)] == colors and [n for n, _ in cards(at)] == FOUR
assert all(t["fillcolor"].endswith(",0.1)") for t in data)
assert all("text" not in t["mode"] for t in data)
assert all("Protection du ballon" in t["theta"] for t in data)
assert "possessions utilisées" in data[0]["customdata"][data[0]["theta"].index("Protection du ballon")][1]
assert list(recap(at).index) == FOUR
ok("4 joueurs : 4 cartes et 4 tracés de couleurs distinctes, remplissage à 10 %, infobulles d'axe")

# 2 bis. Échelle radiale 0-100 : le cercle extérieur correspond exactement au score maximum
assert spec(at)["layout"]["polar"]["radialaxis"]["range"] == [0, 100]
ok("échelle radiale fixée de 0 à 100")

# 3. Tableau récap : pourcentages et TOV% lisibles
row = recap(at).loc["Shai Gilgeous-Alexander"]
assert row["Efficacité (TS%)"].startswith("63.") and "%" in row["Efficacité (TS%)"], row["Efficacité (TS%)"]
assert row["Lancers francs (LF%)"].startswith("89.") and "%" in row["Lancers francs (LF%)"], row["Lancers francs (LF%)"]
assert row["Protection du ballon"].startswith("8.") and "%" in row["Protection du ballon"], row["Protection du ballon"]
assert row["Impact global (PIE)"].startswith("19.9%"), row["Impact global (PIE)"]
assert row["Scoring"].startswith("32.7"), row["Scoring"]
ok("tableau récap : pourcentages en % à une décimale (PIE compris), TOV% estimé, points par match inchangés")

# 3 bis. Survol : même valeur réelle que le tableau, pour chaque axe et chaque joueur
for t in data:
    for theta, (raw, _) in zip(t["theta"], t["customdata"]):
        assert recap(at).loc[t["name"], theta].startswith(raw + "  ·  "), (t["name"], theta, raw)
ok("survol : valeur réelle identique au tableau (PIE en % à une décimale)")

# 3 ter. Largeurs du tableau : Joueur épinglée et assez large pour les noms complets, colonnes
# d'axes à la largeur de leur contenu (aucune largeur fixe)
cfg = json.loads(at.dataframe[0].proto.columns)
assert cfg["Joueur"]["width"] >= 190 and cfg["Joueur"]["pinned"], cfg["Joueur"]
assert all("width" not in cfg[label] and cfg[label]["help"] for label in data[0]["theta"]), cfg
assert all(v.endswith("\u2007\u00A0") for label in data[0]["theta"] for v in recap(at)[label]), \
    "marge de fin de cellule absente"
ok("tableau récap : colonnes d'axes ajustées au contenu avec marge de fin, Joueur épinglée")

# 4. Limite à 4 joueurs : dans le navigateur, le widget bloque le 5e choix ; AppTest, qui force la
# valeur, reçoit l'erreur de max_selections de Streamlit.
ms.set_value(FOUR + ["LeBron James"]).run()
assert at.exception and "max_selections" in at.exception[0].message, at.exception
ok("5e joueur refusé")

# 5. Deux joueurs : valeurs écrites à côté des points, décalées haut/bas
at = new({"radar_players": FOUR[:2]})
data = traces(at)
assert all("text" in t["mode"] for t in data)
assert [t["textposition"] for t in data] == ["top center", "bottom center"]
ok("2 joueurs : valeurs affichées, décalées haut/bas")

# 6. Sélection vidée à la main : message, pas de repli automatique
at = new({"radar_players": FOUR[:2]})
at.multiselect(key="radar_players").set_value([]).run()
assert not at.exception and at.multiselect(key="radar_players").value == []
assert any("au moins un joueur" in w.value for w in at.warning)
ok("sélection vide : message, sélection laissée vide")

# 7. Changement de saison : joueurs absents retirés, repli si tout disparaît
at = new({"radar_players": ["Victor Wembanyama", "LeBron James"]})
at.selectbox(key="radar_season").set_value("2022-23").run()
assert not at.exception and at.multiselect(key="radar_players").value == ["LeBron James"]
at.selectbox(key="radar_season").set_value("2002-03").run()
assert not at.exception and len(at.multiselect(key="radar_players").value) == 1
ok("changement de saison : joueurs absents retirés, repli sur un joueur si besoin")

# 8. Présélection depuis le Dashboard
at = new({"radar_preselect_player": "Nikola Jokić", "radar_preselect_season": "2023-24"})
assert at.selectbox(key="radar_season").value == "2023-24"
assert at.multiselect(key="radar_players").value == ["Nikola Jokić"]
ok("présélection du Dashboard : saison et joueur repris")

# 9. Playoffs
at = new({"radar_players": FOUR})
next(s for s in at.selectbox if s.label == "Statistiques utilisées").set_value("Playoffs uniquement").run()
assert not at.exception, at.exception
assert set(at.multiselect(key="radar_players").value) <= set(FOUR) and len(traces(at)) >= 1
ok("playoffs : joueurs non qualifiés retirés, radar affiché")

assert writes == [], writes
ok("aucune écriture disque")
print("\nTous les contrôles AppTest de la page Radar sont OK")
