"""Vérifie le Dashboard (Dashboard.py) avec AppTest, en NBA (rendu historique : pas de sélecteur
Compétition ni de case "échantillons courts", mêmes défauts) et en Rugby (Top 14 et Pro D2,
Six Nations "bientôt disponible", saison remise à zéro au changement de compétition, échantillons
courts masqués par défaut, NC, filtre par poste, tableau détaillé, mode "Toutes les saisons").
Lit les caches de data_cache/ sans jamais les modifier (écritures interceptées).

Lancer depuis la racine du projet :  .venv/bin/python tests/apptest_dashboard.py
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import data_sources.nba as nba, data_sources.base as base
writes = []
nba.write_cache = base.write_cache = lambda df, path, **k: writes.append(str(path))
from streamlit.testing.v1 import AppTest
from data_sources.rugby import get_player_stats as rugby_stats
from tests.pilote_picker import choisir, data as picker_data

PAGE = str(ROOT / "Dashboard.py")
ok = lambda name: print("ok -", name)
SEARCH = "Rechercher un joueur"  # étiquette de la liste de recherche de joueurs (player_picker)


def new():
    return AppTest.from_file(PAGE, default_timeout=300).run()


def widget(at, kind, label):
    found = [w for w in getattr(at, kind) if w.label == label]
    return found[0] if found else None


def captions(at):
    return [c.value for c in at.caption]


def points(at):  # nombre de points du nuage principal (traces avec un symbole d'échantillon)
    data = json.loads(at.get("plotly_chart")[0].proto.spec)["data"]
    return sum(len(t["hovertext"]) for t in data if t.get("mode") == "markers")


def spec(at):
    return json.loads(at.get("plotly_chart")[0].proto.spec)


def legend(at):  # (nom, couleur) des entrées de légende du nuage principal
    return [(t["name"], t["marker"]["color"]) for t in spec(at)["data"]
            if t.get("mode") == "markers" and t.get("showlegend", True)]


def display(at):  # valeurs affichées du tableau détaillé (formats du Styler compris)
    import pyarrow as pa
    return pa.ipc.open_stream(at.dataframe[0].proto.arrow_data.styler.display_values).read_all().to_pandas()


def index_hidden(at):
    return '"hidden": true' in at.dataframe[0].proto.columns.replace('":true', '": true') \
        and "_index" in at.dataframe[0].proto.columns


def name_key(competition, seasons):  # libellé affiché -> clé de tri (nom de famille, prénom)
    from data_sources.base import sort_key
    from data_sources.rugby import stats
    keys = {}
    for season in seasons:
        df = stats.get_player_stats(season, competition=competition)
        keys.update({(lbl, season): (sort_key(ln), sort_key(fn))
                     for lbl, ln, fn in zip(df["player_label"], df["last_name"], df["first_name"])})
    return keys


def sorted_by_name(table, competition, seasons, all_seasons=False):
    """Tout le tableau, échantillons courts compris : nom de famille, prénom, puis saison."""
    keys = name_key(competition, seasons)
    if all_seasons:
        order = [keys[(j, s)] + (s,) for j, s in zip(table["Joueur"], table["Saison"])]
    else:
        order = [keys[(j, seasons[0])] for j in table["Joueur"]]
    return order == sorted(order)


def short_mixed_in(table):
    """Échantillons courts mêlés aux autres : une ligne "normal" au moins après le premier "court"."""
    groups = table["Échantillon"].tolist()
    return "court" in groups and "normal" in groups[groups.index("court"):]


FAMILY_COLORS = {"Avants": "#1f77b4", "Arrières": "#d62728", "Indéterminé": "#9e9e9e"}


def no_em_dash(at):
    texts = [at.title[0].value] + captions(at) + [m.value for m in at.markdown if "<style>" not in m.value]
    texts += [i.value for i in at.info] + [w.value for w in at.warning]
    for kind in ("selectbox", "multiselect"):
        for w in getattr(at, kind):
            texts += [w.label] + [str(o) for o in w.options]  # options déjà formatées
    assert not [t for t in texts if "—" in str(t)], [t for t in texts if "—" in str(t)]


def no_nba_text(at):
    """Rugby : aucun texte repris de la NBA ou en anglais (titres, légendes, messages, widgets et
    leurs aides, en-têtes du tableau, infobulles), virgule décimale dans les infobulles."""
    texts = [at.title[0].value] + captions(at) + [m.value for m in at.markdown if "<style>" not in m.value]
    texts += [i.value for i in at.info] + [w.value for w in at.warning] + [s.value for s in at.subheader]
    for kind in ("selectbox", "multiselect", "slider", "checkbox"):
        for w in getattr(at, kind):
            texts += [w.label, w.help or ""] + [str(o) for o in getattr(w, "options", [])]
    texts += list(at.dataframe[0].value.columns) if at.dataframe else []
    hovers = [c[0] for t in spec(at)["data"] if t.get("mode") == "markers" for c in t["customdata"]]
    bad = [t for t in texts + hovers if re.search(r"garbage|clipp|-- |Offloads", str(t))]
    assert not bad, bad
    assert not [h for h in hovers if re.search(r"\d\.\d", h)], [h for h in hovers if re.search(r"\d\.\d", h)][:3]
    assert spec(at)["layout"].get("separators") == ", "


# --- NBA : rendu historique ---------------------------------------------------
at = new()
assert not at.exception, at.exception
assert at.title[0].value == "Basketball (NBA) · 2024-25", at.title[0].value
assert widget(at, "selectbox", "Compétition") is None
assert widget(at, "checkbox", "Afficher les échantillons courts") is None
assert widget(at, "selectbox", "Saison").value == "2024-25"
assert widget(at, "selectbox", "Statistiques utilisées").value == "Saison régulière"
assert widget(at, "selectbox", "Statistique en abscisse (X)").value == "salary_musd"
assert widget(at, "selectbox", "Statistique en ordonnée (Y)").value == "points_per_game"
assert widget(at, "selectbox", "Colorer selon").value == "pie"
assert widget(at, "multiselect", "Filtrer par poste (optionnel)") is None
assert widget(at, "slider", "Nombre de matchs joués minimum").max == 82
assert at.slider(key="min_minutes").value == 8.0 and at.slider(key="min_minutes").max == 40.0
assert any(c.startswith("◆ Losange = échantillon de saison court (peu de matchs joués)") for c in captions(at))
assert widget(at, "selectbox", "Sport").options == [
    "Basketball (NBA)", "Rugby", "MMA (bientôt disponible)", "Tennis (bientôt disponible)"]
assert points(at) > 300
no_em_dash(at)
nba_table = at.dataframe[0].value
assert list(nba_table.columns[:2]) == ["player", "team"] and "Échantillon" in nba_table.columns
assert not index_hidden(at)
assert {n for n, _ in legend(at)} == {"Échantillon normal", "Échantillon court (peu de matchs)"}, legend(at)
assert "ticksuffix" not in spec(at)["layout"]["yaxis"]
widget(at, "selectbox", "Statistique en ordonnée (Y)").set_value("fg_pct").run()
assert not at.exception and "ticksuffix" not in spec(at)["layout"]["yaxis"]
assert points(at) > 300
widget(at, "selectbox", "Statistique en ordonnée (Y)").set_value("points_per_game").run()
ok("NBA : titre, défauts, curseurs, légende des échantillons, graduations et tableau inchangés")

# Recherche d'un joueur : liste de recherche maison (player_picker), pilotée comme la grille
# Effectifs (tests/pilote_picker.py). Recherche, clavier et affichage : tests/js/test_picker.mjs.
d = picker_data(at, SEARCH)
assert d["placeholder"] == "ex. doncic" and d["max"] == 1 and d["selected"] == [], d
assert len(d["options"]) > 300 and ["Luka Dončić", "Luka Dončić"] in d["options"]
assert not [w for w in list(at.selectbox) + list(at.text_input) if w.label in ("Joueur", SEARCH)]
choisir(at, SEARCH, ["Nikola Jokić"])
assert at.session_state["searched_player"] == "Nikola Jokić"
assert widget(at, "button", "Voir le profil radar") is not None
ok("NBA : bouton « Voir le profil radar » présent")

# Juste après un choix, la liste reçoit déjà la nouvelle sélection (run relancé) : sinon, choisir
# puis cliquer la croix faisait réapparaître le joueur.
choisir(at, SEARCH, ["Luka Dončić"])
assert at.session_state["searched_player"] == "Luka Dončić"
assert picker_data(at, SEARCH)["selected"] == ["Luka Dončić"]
# Joueur gardé quand la saison change s'il y existe (2023-24), sinon "Aucun" (2016-17, avant ses débuts).
widget(at, "selectbox", "Saison").set_value("2023-24").run()
assert not at.exception and picker_data(at, SEARCH)["selected"] == ["Luka Dončić"]
widget(at, "selectbox", "Saison").set_value("2016-17").run()
assert not at.exception and picker_data(at, SEARCH)["selected"] == []
assert at.session_state["searched_player"] == "Aucun"
widget(at, "selectbox", "Saison").set_value("2024-25").run()
# Croix : désélection.
choisir(at, SEARCH, ["Luka Dončić"])
choisir(at, SEARCH, [])
assert at.session_state["searched_player"] == "Aucun" and widget(at, "button", "Voir le profil radar") is None
assert picker_data(at, SEARCH)["selected"] == []
ok("NBA : placeholder « ex. doncic », Luka Dončić choisi, gardé ou remis à « Aucun » au changement "
   "de saison, croix pour désélectionner")

# --- Rugby : Top 14 par défaut ----------------------------------------------------
at = new()
widget(at, "selectbox", "Sport").set_value("rugby").run()
assert not at.exception, at.exception
comp = widget(at, "selectbox", "Compétition")
assert comp.options == ["Top 14", "Pro D2", "Six Nations (bientôt disponible)"] and comp.value == "top14"
assert at.title[0].value == "Rugby · Top 14 · 2025-26", at.title[0].value
assert widget(at, "selectbox", "Statistiques utilisées").value == "Saison complète (phases finales incluses)"
assert widget(at, "selectbox", "Statistique en abscisse (X)").value == "tackles_per80"
assert widget(at, "selectbox", "Statistique en ordonnée (Y)").value == "metres_per80"
assert widget(at, "selectbox", "Colorer selon").value == "position_family"
assert at.slider(key="min_minutes").value == 0.0 and at.slider(key="min_minutes").max == 80.0
assert widget(at, "slider", "Nombre de matchs joués minimum").max == 34
box = widget(at, "checkbox", "Afficher les échantillons courts")
assert box is not None and box.value is False
hidden = [c for c in captions(at) if "à échantillon court masqués" in c]
assert len(hidden) == 1 and "moins de 5 matchs ou 520 minutes" in hidden[0], captions(at)
n_hidden = int(hidden[0].split()[0])
n_shown = points(at)
assert not any(c.startswith("◆ Losange") for c in captions(at))
assert not [s for s in at.subheader if s.value == "Classement des équipes"] and not at.info
assert widget(at, "slider", "Minutes par match minimum").proto.format == "%.0f"
no_em_dash(at)
no_nba_text(at)
ok(f"Rugby : Top 14 2025-26 par défaut, {n_shown} points, {n_hidden} échantillons courts masqués")

# Légende : couleurs seules, fixes par famille
assert legend(at) == [("Avants", FAMILY_COLORS["Avants"]), ("Arrières", FAMILY_COLORS["Arrières"])], legend(at)
ok("Rugby : légende réduite aux familles, couleurs fixes")

table = at.dataframe[0].value
assert list(table.columns[:7]) == ["Joueur", "Équipe", "Clubs", "Poste", "Matchs", "Titularisations", "Minutes"]
# Clubs : seulement pour un joueur passé par plusieurs clubs (3 en Top 14 2025-26, Gray compris)
assert table["Clubs"].notna().sum() >= 3 and table["Clubs"].dropna().str.contains(r"\(\d+\), ").all()
assert {"Plaquages par 80 min", "Mètres par 80 min", "Essais", "Cartons (J / R)", "Échantillon"} <= set(table.columns)
assert len(table) == n_shown + n_hidden and (table["Échantillon"] == "court").sum() == n_hidden
# Ordre purement alphabétique (nom de famille, prénom), échantillons courts mêlés aux autres
assert sorted_by_name(table, "top14", ["2025-26"]) and short_mixed_in(table)
assert table["Poste"].str.endswith(" (banc)").any() and not table["Poste"].str.contains("déduit").any()
shown = display(at)
assert shown["Mètres par 80 min"].str.fullmatch(r"\d+,\d").all(), shown["Mètres par 80 min"].head()
assert shown["Minutes"].str.fullmatch(r"\d+").all() and shown["Essais"].str.fullmatch(r"\d+").all()
assert index_hidden(at)
assert "Saison" not in table.columns
ok("Rugby : tableau détaillé complet, ordre alphabétique sans regrouper les échantillons courts, virgule décimale, sans index")

# Filtre équipe : un joueur passé par deux clubs apparaît dans chacun (Gray : Bordeaux-Bègles,
# club principal, et Perpignan), avec la mention de ses clubs dans l'infobulle (décision B.2).
team_box = widget(at, "multiselect", "Filtrer par équipe (optionnel)")
for club in ("Bordeaux-Bègles", "Perpignan"):
    team_box.set_value([club]).run()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    gray = table[table["Joueur"] == "Jonny Gray"]
    assert len(gray) == 1 and gray["Équipe"].iloc[0] == "Bordeaux-Bègles", (club, gray)
    assert gray["Clubs"].iloc[0] == "Bordeaux-Bègles (10), Perpignan (4)"
    hover = [h for t in spec(at)["data"] if t.get("mode") == "markers"
             for name, h in zip(t["hovertext"], [c[0] for c in t["customdata"]]) if name == "Jonny Gray"]
    assert hover and "Clubs : Bordeaux-Bègles (10), Perpignan (4)" in hover[0], hover
    assert set(table["Équipe"]) - {club} <= set(table.loc[table["Clubs"].notna(), "Équipe"])
team_box.set_value([]).run()
ok("Rugby : filtre Bordeaux-Bègles puis Perpignan, Jonny Gray présent dans les deux, clubs dans l'infobulle et le tableau")

box.check().run()
assert not at.exception and points(at) == n_shown + n_hidden
assert legend(at) == [(f, c) for f, c in FAMILY_COLORS.items()], legend(at)
assert not [c for c in captions(at) if "masqués" in c]
assert any(c.startswith("◆ Losange = échantillon de saison court (moins de 5 matchs ou 520 minutes)") for c in captions(at))
box.uncheck().run()
ok("Rugby : case cochée, les échantillons courts reviennent en losange")

# % au pied en Y : NC retirés du graph, détail "78 % (52/67)" et "NC" dans le tableau
widget(at, "selectbox", "Statistique en ordonnée (Y)").set_value("goal_kick_pct").run()
assert not at.exception, at.exception
nc = [c for c in captions(at) if " NC (" in c]
assert len(nc) == 1 and "sous 35 tentatives" in nc[0], captions(at)
assert spec(at)["layout"]["yaxis"]["ticksuffix"] == " %" and "ticksuffix" not in spec(at)["layout"]["xaxis"]
table = at.dataframe[0].value
col = table["% au pied"]
assert col.str.fullmatch(r"\d+ % \(\d+/\d+\)").sum() > 10 and (col == "NC").any()
assert sorted_by_name(table, "top14", ["2025-26"])  # tri alphabétique, quel que soit Y
# Non-buteurs absents du tableau, comptés au-dessus du tableau (D1.9)
missing = [c for c in captions(at) if " sans valeur pour " in c and "« % au pied »" in c]
assert len(missing) == 1 and missing[0].endswith("absents du graph et du tableau."), captions(at)
n_missing = int(missing[0].split()[0])
# Curseurs à 0, sans filtre : non-buteurs + lignes du tableau = tous les joueurs de la saison
assert n_missing + len(table) == len(rugby_stats("2025-26", competition="top14")), (n_missing, len(table))
# Piliers : graph vide à cause des tentatives, pas des minutes (curseur à 0) : message selon la cause
widget(at, "multiselect", "Filtrer par poste (optionnel)").set_value(["Pilier"]).run()
assert not at.exception, at.exception
(warn,) = [w.value for w in at.warning]
assert warn.startswith("Aucun joueur à afficher : ") and "« % au pied »" in warn, warn
assert "minimum de minutes" not in warn, warn
widget(at, "multiselect", "Filtrer par poste (optionnel)").set_value([]).run()
ok(f"Rugby : % au pied en Y, NC retirés du graph, « NC » et détail réussis/tentatives dans le tableau, "
   f"{n_missing} non-buteurs comptés, message de graph vide des piliers : {warn}")

# Stat peu fiable : mention dans le sélecteur et sous le graph
y = widget(at, "selectbox", "Statistique en ordonnée (Y)")
assert y.format_func("penalties_conceded_per80").endswith("(peu fiable sur une saison)")
y.set_value("penalties_conceded_per80").run()
assert any(c.startswith("Pénalités concédées par 80 min : peu fiable sur une saison") for c in captions(at))
ok("Rugby : mention « peu fiable sur une saison »")

# Filtre par poste
widget(at, "selectbox", "Statistique en ordonnée (Y)").set_value("metres_per80").run()
pos = widget(at, "multiselect", "Filtrer par poste (optionnel)")
assert pos.options[:2] == ["Pilier", "Talonneur"] and pos.options[-1] == "Indéterminé"
pos.set_value(["Pilier"]).run()
assert not at.exception and set(at.dataframe[0].value["Poste"].str.split(" \\(").str[0]) == {"Pilier"}
pos.set_value([]).run()
ok("Rugby : filtre par poste")

# Recherche : bouton radar présent (lot 6) ; joueur à échantillon court masqué signalé
short = at.dataframe[0].value.query("Échantillon == 'court'")["Joueur"].iloc[0]
choisir(at, SEARCH, [short])
assert widget(at, "button", "Voir le profil radar") is not None
assert any("Afficher les échantillons courts" in i.value for i in at.info)
choisir(at, SEARCH, [])
assert widget(at, "button", "Voir le profil radar") is None
ok("Rugby : bouton radar présent, message pour un joueur à échantillon court masqué")

d = picker_data(at, SEARCH)
assert d["placeholder"] == "ex. gael" and ["Gaël Fickou", "Gaël Fickou · Centre"] in d["options"], d["placeholder"]
assert all(" · " in label for _, label in d["options"])
assert not [l for _, l in d["options"] if re.search(r"\(banc\)|poste mixte|aussi|%", l)]
choisir(at, SEARCH, ["Gaël Fickou"])
assert at.session_state["searched_player"] == "Gaël Fickou"
choisir(at, SEARCH, [])
ok("Rugby : placeholder « ex. gael », Gaël Fickou proposé et choisi")

# Bouton radar : dépose sport, compétition, saison, période et identifiant du joueur
_r = rugby_stats("2025-26", competition="top14")
_target = _r[_r["position_group"] == "Ailier"].sort_values("minutes_total").iloc[-1]
radar_at = AppTest.from_file(PAGE, default_timeout=300)
radar_at.session_state["selected_sport"] = "rugby"
radar_at.run()
assert not radar_at.exception, radar_at.exception
choisir(radar_at, SEARCH, [_target["player_label"]])
# AppTest ne suit pas st.switch_page vers un fichier de pages/ : neutralisé le temps du clic, puis
# la page Radar est ouverte avec les clés déposées par le callback.
import streamlit as _st
_switch_page, _st.switch_page = _st.switch_page, lambda page: None
widget(radar_at, "button", "Voir le profil radar").click().run()
_st.switch_page = _switch_page
assert not radar_at.exception, radar_at.exception
deposited = {k: radar_at.session_state[k] for k in (
    "radar_preselect_player", "radar_preselect_label", "radar_preselect_season",
    "radar_preselect_sport", "radar_preselect_competition", "radar_preselect_period")}
assert deposited == {
    "radar_preselect_player": _target["player_uid"], "radar_preselect_label": _target["player_label"],
    "radar_preselect_season": "2025-26", "radar_preselect_sport": "rugby",
    "radar_preselect_competition": "top14", "radar_preselect_period": "all"}, deposited
radar_page = AppTest.from_file(str(ROOT / "pages" / "1_Radar_de_comparaison.py"), default_timeout=300)
for k, v in deposited.items():
    radar_page.session_state[k] = v
radar_page.run()
assert not radar_page.exception, radar_page.exception
assert radar_page.title[0].value == "Radar de comparaison · Top 14 · 2025-26", radar_page.title[0].value
assert picker_data(radar_page, "Joueurs (1 à 4)")["selected"] == [_target["player_uid"]]
assert widget(radar_page, "selectbox", "Statistiques utilisées").value == "Saison complète (phases finales incluses)"
ok(f"Rugby : « Voir le profil radar » ouvre le radar de {_target['player_label']} (Top 14 2025-26)")

# Changement de compétition : saison absente du Pro D2 remise à zéro
widget(at, "selectbox", "Saison").set_value("2021-22").run()
assert at.title[0].value == "Rugby · Top 14 · 2021-22"
widget(at, "selectbox", "Compétition").set_value("prod2").run()
assert not at.exception, at.exception
assert at.title[0].value == "Rugby · Pro D2 · 2025-26", at.title[0].value
assert widget(at, "selectbox", "Saison").options[1:] == ["2025-26", "2024-25", "2023-24", "2022-23"]
widget(at, "selectbox", "Statistiques utilisées").set_value("Phase régulière").run()
assert not at.exception and points(at) > 200
# Équipes triées sans accents (Béziers avant Brive), noms d'usage courts
teams = widget(at, "multiselect", "Filtrer par équipe (optionnel)").options
assert teams == sorted(teams, key=base.sort_key) and teams.index("Béziers") < teams.index("Brive"), teams
assert not {"Biarritz Olympique", "Stade Francais Paris", "Lyon O.U."} & set(teams), teams
no_nba_text(at)
ok("Rugby : passage au Pro D2, saison remise à 2025-26, phase régulière")

# Toutes les saisons
season = widget(at, "selectbox", "Saison")
season.set_value(season.options[0]).run()
assert not at.exception, at.exception
assert at.title[0].value == ("Rugby · Pro D2 · Toutes les saisons (2022-23 → 2025-26) · Saison complète "
                              "(phases finales incluses)"), at.title[0].value
assert widget(at, "selectbox", "Statistiques utilisées") is None and points(at) > 600
table = at.dataframe[0].value
assert list(table.columns[:3]) == ["Joueur", "Saison", "Équipe"]
assert sorted_by_name(table, "prod2", ["2022-23", "2023-24", "2024-25", "2025-26"], all_seasons=True)
assert short_mixed_in(table)
ok("Rugby : mode Toutes les saisons, colonne Saison dans le tableau")

# Bug du 13 octobre : depuis « Toutes les saisons », changer de compétition doit remettre la saison
# par défaut ET la pousser au navigateur (set_value), sinon le sélecteur garde l'ancien libellé.
def season_reset_pushed(at, expected_title):
    s = widget(at, "selectbox", "Saison")
    assert not at.exception, at.exception
    assert at.title[0].value == expected_title, at.title[0].value
    assert s.value == "2025-26" and s.proto.set_value, (s.value, s.proto.set_value)
    assert widget(at, "selectbox", "Statistiques utilisées") is not None


widget(at, "selectbox", "Compétition").set_value("top14").run()
season_reset_pushed(at, "Rugby · Top 14 · 2025-26")
season = widget(at, "selectbox", "Saison")
season.set_value(season.options[0]).run()
assert at.title[0].value == ("Rugby · Top 14 · Toutes les saisons (2021-22 → 2025-26) · Saison complète "
                              "(phases finales incluses)"), at.title[0].value
widget(at, "selectbox", "Compétition").set_value("prod2").run()
season_reset_pushed(at, "Rugby · Pro D2 · 2025-26")
widget(at, "selectbox", "Statistique en ordonnée (Y)").set_value("metres_per80").run()
assert not at.exception and widget(at, "selectbox", "Saison").value == "2025-26"
assert widget(at, "checkbox", "Afficher les échantillons courts").value is False
assert legend(at) == [("Avants", FAMILY_COLORS["Avants"]), ("Arrières", FAMILY_COLORS["Arrières"])], legend(at)
ok("Rugby : Toutes les saisons Top 14 puis Pro D2, saison remise et poussée au navigateur, mêmes couleurs")

# Six Nations : bientôt disponible, sans planter
widget(at, "selectbox", "Compétition").set_value("six_nations").run()
assert not at.exception, at.exception
assert at.title[0].value == "Rugby · Six Nations"
assert any("Six Nations arrive dans une prochaine version" in i.value for i in at.info)
no_em_dash(at)
ok("Rugby : Six Nations « bientôt disponible »")

# Retour en NBA : saison et curseurs de la NBA
widget(at, "selectbox", "Sport").set_value("nba").run()
assert not at.exception and at.title[0].value == "Basketball (NBA) · 2024-25", at.title[0].value
assert at.slider(key="min_minutes").value == 8.0 and at.slider(key="min_minutes").proto.set_value
assert widget(at, "selectbox", "Saison").proto.set_value
ok("Retour en NBA : saison 2024-25 et 8 min par match")

# Sport indisponible
widget(at, "selectbox", "Sport").set_value("mma").run()
assert not at.exception and any("**Basketball (NBA)**, **Rugby**" in i.value for i in at.info), [i.value for i in at.info]
ok("Sport indisponible : message avec les sports actifs")

# Données partielles : bandeau visible quand get_player_stats signale un manque (attrs).
# SPORTS["nba"] remplacé le temps du contrôle, restauré même en cas d'échec.
import dataclasses
import streamlit as st
from data_sources import SPORTS
_nba = SPORTS["nba"]


def _partial_stats(season, *args, **kwargs):
    df = _nba.get_player_stats(season, *args, **kwargs).copy()
    df.attrs[base.INCOMPLETE_DATA_ATTR] = ["fiabilité"]
    return df


SPORTS["nba"] = dataclasses.replace(_nba, get_player_stats=_partial_stats)
st.cache_data.clear()
try:
    at = new()
    assert not at.exception, at.exception
    assert any(w.value == "Données partielles pour 2024-25 : fiabilité indisponible. Les autres stats ne "
               "sont pas concernées." for w in at.warning), [w.value for w in at.warning]
finally:
    SPORTS["nba"] = _nba
    st.cache_data.clear()
ok("données partielles : bandeau « Données partielles pour 2024-25 » affiché")

assert not writes, writes
print("Tous les contrôles du Dashboard sont passés.")
