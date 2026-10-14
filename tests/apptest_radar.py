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


def traces(at, meta="points"):  # tracés du radar d'un rôle donné (meta), un par joueur au plus
    return [t for t in spec(at)["data"] if t.get("meta") == meta]


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
assert len(traces(at)) == 1 and len(traces(at, "legende")) == 1 and len(cards(at)) == 1
ok("ouverture : un joueur, une carte, un tracé")

# 2. Quatre joueurs : couleurs distinctes, remplissage transparent, valeurs au survol seulement
ms.set_value(FOUR).run()
assert not at.exception, at.exception
data = traces(at)
assert [t["name"] for t in data] == FOUR
colors = [t["marker"]["color"] for t in data]
assert len(set(colors)) == 4 and [c for _, c in cards(at)] == colors and [n for n, _ in cards(at)] == FOUR
assert [t["line"]["color"] for t in traces(at, "contour")] == colors
assert all(t["fillcolor"].endswith(",0.1)") for t in traces(at, "remplissage"))
assert all("text" not in t["mode"] for t in data)
# Légende : une entrée par joueur (trait + point + remplissage, comme avant), aucune autre
legend = [t for t in spec(at)["data"] if t.get("showlegend")]
assert [t["meta"] for t in legend] == ["legende"] * 4 and [t["name"] for t in legend] == FOUR
assert all(t["mode"] == "lines+markers" and t["fill"] == "toself" for t in legend)
assert all(t["legendgroup"] for t in spec(at)["data"])
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
assert row["Lancers francs (LF%)"].startswith("89.") and "% (669 tent.)" in row["Lancers francs (LF%)"], \
    row["Lancers francs (LF%)"]
assert "% (435 tent.)" in row["Tir extérieur (3PT%)"], row["Tir extérieur (3PT%)"]
assert row["Protection du ballon"].startswith("8.") and "%" in row["Protection du ballon"], row["Protection du ballon"]
assert row["Impact global (PIE)"].startswith("19.9%"), row["Impact global (PIE)"]
assert row["Scoring"].startswith("32.7"), row["Scoring"]
ok("tableau récap : pourcentages en % à une décimale (PIE compris), tentatives 3PT/LF, TOV% estimé")

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
assert set(at.multiselect(key="radar_players").value) <= set(FOUR) and len(traces(at, "legende")) >= 1
ok("playoffs : joueurs non qualifiés retirés, radar affiché")

# 10. Axe sans tentative (Rudy Gobert, 0 tir à 3 points en 2024-25) : point absent du tracé (pas
# un 0 au centre), "0 tent.  ·  NC" dans le tableau, ordre des axes conservé même s'il est le premier tracé
at = new({"radar_players": ["Rudy Gobert", "Stephen Curry"]})
assert not at.exception, at.exception
gobert, curry = traces(at)
labels = [a["label"] for a in nba.RADAR_AXES]
three = "Tir extérieur (3PT%)"
assert three not in gobert["theta"] and 0 not in gobert["r"], gobert["theta"]
assert len(gobert["theta"]) == len(labels) - 1 and curry["theta"] == labels
assert spec(at)["layout"]["polar"]["angularaxis"]["categoryarray"] == labels
# Segment qui enjambe l'axe vide : en tirets, entre les deux axes voisins ; le contour plein ne
# l'enjambe pas. Curry (aucun axe vide) n'a ni tirets ni cercle creux.
(dashes,) = traces(at, "tirets")
assert dashes["name"] == "Rudy Gobert" and dashes["line"]["dash"] == "dash"
neighbours = {"Impact global (PIE)", "Protection du ballon"}
assert set(dashes["theta"][:2]) == neighbours, dashes["theta"]
(solid_g, solid_c) = traces(at, "contour")
# Le contour est une suite de segments (début, fin, coupure None) : aucun ne relie les voisins.
segments = [set(solid_g["theta"][k:k + 2]) for k in range(0, len(solid_g["theta"]), 3)]
assert three not in solid_g["theta"] and neighbours not in segments, segments
# Cercle creux sans texte sur l'axe vide, survol "aucune tentative"
(circle,) = traces(at, "sans_tentative")
assert circle["name"] == "Rudy Gobert" and circle["theta"] == [three] and circle["mode"] == "markers"
assert circle["marker"]["symbol"] == "circle-open" and circle["customdata"] == ["aucune tentative"]
assert recap(at).loc["Rudy Gobert", three] == "0 tent.  ·  NC\u2007\u00A0", recap(at).loc["Rudy Gobert", three]
ok("axe sans tentative : pas de point, segment en tirets, cercle creux « aucune tentative », « 0 tent.  ·  NC » au tableau")

# 11. Deux joueurs sans tentative sur le même axe (Gobert et Simmons) : cercles creux décalés
# (pas de chevauchement) ; le segment en tirets de Simmons part du centre (Protection du ballon à 0)
at = new({"radar_players": ["Rudy Gobert", "Ben Simmons", "Stephen Curry", "Nikola Jokić"]})
assert not at.exception, at.exception
circles = traces(at, "sans_tentative")
assert [c["name"] for c in circles] == ["Rudy Gobert", "Ben Simmons"]
assert circles[1]["r"][0] - circles[0]["r"][0] >= 6, [c["r"] for c in circles]
simmons_dash = next(t for t in traces(at, "tirets") if t["name"] == "Ben Simmons")
assert 0 in simmons_dash["r"][:2] and simmons_dash["line"]["width"] == 2, simmons_dash["r"]
ok("4 joueurs : cercles creux décalés, tirets de Simmons partant du centre, aussi épais que le trait")

# 12. Volume trop faible (2020-21) : Gobert 0/4 et Simmons 3/10 à 3 points, sous 1 tentative par
# match. Axe vide comme sans tentative, survol avec le nombre de tentatives, vrai % au tableau.
at = new({"radar_season": "2020-21", "radar_players": ["Rudy Gobert", "Ben Simmons", "Nikola Jokić", "Stephen Curry"]})
assert not at.exception, at.exception
circles = traces(at, "sans_tentative")
assert [(c["name"], c["theta"], c["customdata"]) for c in circles] == [
    ("Rudy Gobert", [three], ["volume trop faible (4 tentatives en 71 matchs)"]),
    ("Ben Simmons", [three], ["volume trop faible (10 tentatives en 58 matchs)"]),
], circles
assert [t["name"] for t in traces(at, "tirets")] == ["Rudy Gobert", "Ben Simmons"]
assert all(three in t["theta"] for t in traces(at) if t["name"] in ("Nikola Jokić", "Stephen Curry"))
table = recap(at)
assert table.loc["Rudy Gobert", three] == "0.0% (4 tent.)  ·  NC\u2007\u00A0", table.loc["Rudy Gobert", three]
assert table.loc["Ben Simmons", three] == "30.0% (10 tent.)  ·  NC\u2007\u00A0", table.loc["Ben Simmons", three]
assert table.loc["Rudy Gobert", "Lancers francs (LF%)"].startswith("62.3% (374 tent.)  ·  ")
assert "NC" not in table.loc["Rudy Gobert", "Lancers francs (LF%)"]
cfg = json.loads(at.dataframe[0].proto.columns)
for label in (three, "Lancers francs (LF%)"):
    assert "NC : non classé, volume de tirs sous le seuil." in cfg[label]["help"], cfg[label]["help"]
assert all("NC" not in cfg[a["label"]]["help"] for a in nba.RADAR_AXES if "attempts_col" not in a)
assert any("« NC » (non classé)" in c.value or '"NC" (non classé)' in c.value for c in at.caption)
ok("volume trop faible (2020-21) : axe vide, survol avec les tentatives, « 0.0% (4 tent.)  ·  NC » au tableau, NC expliqué")

# --- Rugby (lot 6) -----------------------------------------------------------------
from data_sources.rugby import get_player_stats as rugby_stats, radar as rugby_radar


def select(at, label):
    return next(s for s in at.selectbox if s.label == label)


def all_texts(at):
    texts = [t.value for t in at.title] + [c.value for c in at.caption] + [i.value for i in at.info]
    texts += [m.value for m in at.markdown if "<style>" not in m.value]
    for w in list(at.selectbox) + list(at.multiselect):
        texts += [w.label] + [str(o) for o in w.options]
    if at.dataframe:
        texts += [str(v) for v in recap(at).to_numpy().ravel()] + list(recap(at).columns)
    return texts


# R1. Sport et compétition repris du Dashboard ; NBA par défaut sans choix du Dashboard
at = new()
assert select(at, "Sport").value == "nba" and not [s for s in at.selectbox if s.label == "Compétition"]
at = new({"selected_sport": "rugby", "selected_competition": "prod2"})
assert not at.exception, at.exception
assert select(at, "Sport").value == "rugby" and select(at, "Compétition").value == "prod2"
assert select(at, "Saison").value == "2025-26"
assert select(at, "Statistiques utilisées").value == "Saison complète (phases finales incluses)"
assert at.title[0].value == "Radar de comparaison · Pro D2 · 2025-26", at.title[0].value
at = new({"selected_sport": "rugby"})
assert select(at, "Compétition").value == "top14"
ok("sport et compétition repris du Dashboard (Pro D2), NBA sans choix du Dashboard")

# R2. Liste des joueurs : identifiants, nom et poste affichés, sans Indéterminé, (banc) compris
df_r = rugby_radar.compute_radar_scores(rugby_stats("2025-26", competition="top14"))
ms = at.multiselect(key="radar_players")
assert all(v.startswith("icw:") for v in ms.value)
und = df_r[(df_r["position_group"] == "Indéterminé") & (df_r["games_played"] > 0)]
assert len(und) > 0 and not any(o.endswith(" · Indéterminé") for o in ms.options)
assert any(o.endswith(" (banc)") for o in ms.options)
assert len(ms.options) == ((df_r["games_played"] > 0) & df_r["radar_eligible"]).sum()
assert any(f"{len(und)} joueurs sans poste déterminé" in c.value for c in at.caption)
ok(f"liste rugby par identifiant, « Nom · Poste », {len(und)} Indéterminé exclus et signalés, (banc) proposés")


def best(pos):  # titulaire du poste avec le plus de minutes
    return df_r[df_r["position_group"] == pos].sort_values("minutes_total").iloc[-1]


# R3. Pilier, Ailier, Arrière : intersection à 5 axes, notes, colonnes hors radar, cartes
trio = [best(p) for p in ("Pilier", "Ailier", "Arrière")]
ms.set_value([r["player_uid"] for r in trio]).run()
assert not at.exception, at.exception
cat = spec(at)["layout"]["polar"]["angularaxis"]["categoryarray"]
assert cat == ["Plaquages", "Mètres", "% gain de ligne", "Courses", "Défenseurs battus"], cat
caps = [c.value for c in at.caption]
assert any(c.startswith("Postes différents") for c in caps)
assert any(c.startswith("Axes retirés") and "Mètres au pied, Passes (Arrière)" in c for c in caps), caps
assert any(c.startswith("Joueurs de référence : Pilier") for c in caps)
assert rugby_radar.FEW_AXES_NOTE not in caps
table = recap(at)
assert list(table.index) == [r["player_label"] for r in trio]
pen = "Pénalités concédées par 80 (ajusté, peu fiable)"
for col in ("% plaquages", "Grattages (ajusté)", "Mètres au pied (ajusté)", "Essais", "% au pied",
            "Cartons (J / R)", pen):
    assert col in table.columns, col
assert all(" (brut " in v for v in table[pen]), table[pen]
cfg = json.loads(at.dataframe[0].proto.columns)
assert "Peu fiable sur une saison" in cfg[pen]["help"] and "valeur brute entre parenthèses" in cfg[pen]["help"]
assert [n for n, _ in cards(at)] == [r["player_label"] for r in trio]
card = next(m.value for m in at.markdown if "border-left: 4px solid" in m.value)
assert "· Saison complète (phases finales incluses) ·" in card
assert "Essais : " in card and "% au pied : " in card and "Cartons : " in card
assert "titularisation" in card and ">Pilier" in card
ok("Pilier, Ailier, Arrière : 5 axes communs, axes retirés au tableau, hors radar, cartes")

# R4. NC : % plaquages sous 25 tentatives (hors arrières, qui n'ont pas l'axe)
nc = df_r[df_r["radar_eligible"] & (df_r["tackle_attempts"].between(1, 24))
          & (df_r["position_group"] != "Arrière")].iloc[0]
ms.set_value([nc["player_uid"]]).run()
assert not at.exception, at.exception
(circle,) = traces(at, "sans_tentative")
reasons = dict(zip(circle["theta"], circle["customdata"]))
assert reasons["% plaquages"] == f"volume trop faible : {nc['tackle_attempts']:.0f} plaquages tentés, minimum 25", reasons
cell = recap(at).loc[nc["player_label"], "% plaquages"]
assert cell.endswith("  ·  NC  ") and f"({nc['tackles']:.0f}/{nc['tackle_attempts']:.0f})" in cell, cell
assert "Échantillon court" in next(m.value for m in at.markdown if "border-left" in m.value)
ok(f"NC : {nc['player_label']} ({nc['tackle_attempts']:.0f} plaquages tentés), cercle creux, « NC » au tableau, échantillon court")

# R5. Joueur (banc) : radar, mention dans la carte
bench = df_r[df_r["position_source"] == "banc"].sort_values("minutes_total").iloc[-1]
ms.set_value([bench["player_uid"]]).run()
assert not at.exception and len(traces(at)) == 1
assert "poste déduit du maillot de banc" in next(m.value for m in at.markdown if "border-left" in m.value)
ok(f"(banc) : radar de {bench['player_label']}, poste déduit du maillot de banc")

# R6. Présélection du Dashboard : sport, compétition, saison, période et joueur (par identifiant)
p = rugby_stats("2023-24", competition="top14", period="regular")
target = p[p["position_group"] == "Centre"].sort_values("minutes_total").iloc[-1]
at = new({"radar_preselect_player": target["player_uid"], "radar_preselect_label": target["player_label"],
          "radar_preselect_sport": "rugby", "radar_preselect_competition": "top14",
          "radar_preselect_season": "2023-24", "radar_preselect_period": "regular"})
assert not at.exception, at.exception
assert (select(at, "Sport").value, select(at, "Compétition").value, select(at, "Saison").value) == \
    ("rugby", "top14", "2023-24")
assert select(at, "Statistiques utilisées").value == "Phase régulière"
assert at.multiselect(key="radar_players").value == [target["player_uid"]]
ok(f"présélection rugby : {target['player_label']}, Top 14 2023-24, phase régulière")

# R7. Présélection d'un Indéterminé : message, pas de radar pour lui
u = und.iloc[0]
at = new({"radar_preselect_player": u["player_uid"], "radar_preselect_label": u["player_label"],
          "radar_preselect_sport": "rugby", "radar_preselect_competition": "top14",
          "radar_preselect_season": "2025-26", "radar_preselect_period": "all"})
assert not at.exception and u["player_uid"] not in at.multiselect(key="radar_players").value
assert any("n'a pas de poste déterminé" in i.value and u["player_label"] in i.value for i in at.info)
ok("présélection d'un Indéterminé : message « pas de poste déterminé »")

# R8. Retour à la NBA depuis le rugby : saison et joueurs revalidés
select(at, "Sport").set_value("nba").run()
assert not at.exception, at.exception
assert select(at, "Saison").value == "2024-25" and at.title[0].value == "Radar de comparaison · 2024-25"
assert len(at.multiselect(key="radar_players").value) == 1 and len(traces(at)) == 1
ok("rugby puis NBA : saison 2024-25 et joueur NBA, sans erreur")

# R9. Six Nations « bientôt disponible », sport sans radar
at = new({"selected_sport": "rugby", "selected_competition": "six_nations"})
assert not at.exception and any("Six Nations arrive dans une prochaine version" in i.value for i in at.info)
at = new({"selected_sport": "mma"})
assert not at.exception and any("pas encore disponible" in i.value for i in at.info)
ok("Six Nations « bientôt disponible », MMA sans radar")

# R10. Aucun tiret cadratin dans les textes rugby affichés
at = new({"selected_sport": "rugby", "radar_players": [r["player_uid"] for r in trio]})
assert not at.exception
assert not [t for t in all_texts(at) if "—" in t], [t for t in all_texts(at) if "—" in t]
at.radio[0].set_value("Centile").run()
assert not at.exception and not [t for t in all_texts(at) if "—" in t]
ok("rugby : aucun tiret cadratin (modes Indice et Centile)")

assert writes == [], writes
ok("aucune écriture disque")
print("\nTous les contrôles AppTest de la page Radar sont OK")
