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

PAGE = str(ROOT / "Dashboard.py")
ok = lambda name: print("ok -", name)


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
    from data_sources.base import normalize_name
    from data_sources.rugby import stats
    keys = {}
    for season in seasons:
        df = stats.get_player_stats(season, competition=competition)
        keys.update({(lbl, season): (normalize_name(ln), normalize_name(fn))
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

widget(at, "selectbox", "Rechercher un joueur").set_value("Nikola Jokić").run()
assert not at.exception and widget(at, "button", "Voir le profil radar") is not None
ok("NBA : bouton « Voir le profil radar » présent")

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
assert "Classement des équipes pas encore disponible pour ce sport." in [i.value for i in at.info]
no_em_dash(at)
ok(f"Rugby : Top 14 2025-26 par défaut, {n_shown} points, {n_hidden} échantillons courts masqués")

# Légende : couleurs seules, fixes par famille
assert legend(at) == [("Avants", FAMILY_COLORS["Avants"]), ("Arrières", FAMILY_COLORS["Arrières"])], legend(at)
ok("Rugby : légende réduite aux familles, couleurs fixes")

table = at.dataframe[0].value
assert list(table.columns[:6]) == ["Joueur", "Équipe", "Poste", "Matchs", "Titularisations", "Minutes"]
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
col = table["% au pied (transformations et pénalités)"]
assert col.str.fullmatch(r"\d+ % \(\d+/\d+\)").sum() > 10 and (col == "NC").any()
assert sorted_by_name(table, "top14", ["2025-26"])  # tri alphabétique, quel que soit Y
ok("Rugby : % au pied en Y, NC retirés du graph, « NC » et détail réussis/tentatives dans le tableau")

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

# Recherche : bouton radar masqué ; joueur à échantillon court masqué signalé
search = widget(at, "selectbox", "Rechercher un joueur")
short = at.dataframe[0].value.query("Échantillon == 'court'")["Joueur"].iloc[0]
search.set_value(short).run()
assert not at.exception and widget(at, "button", "Voir le profil radar") is None
assert any("Afficher les échantillons courts" in i.value for i in at.info)
search.set_value("Aucun").run()
ok("Rugby : pas de bouton radar, message pour un joueur à échantillon court masqué")

# Changement de compétition : saison absente du Pro D2 remise à zéro
widget(at, "selectbox", "Saison").set_value("2021-22").run()
assert at.title[0].value == "Rugby · Top 14 · 2021-22"
widget(at, "selectbox", "Compétition").set_value("prod2").run()
assert not at.exception, at.exception
assert at.title[0].value == "Rugby · Pro D2 · 2025-26", at.title[0].value
assert widget(at, "selectbox", "Saison").options[1:] == ["2025-26", "2024-25", "2023-24", "2022-23"]
widget(at, "selectbox", "Statistiques utilisées").set_value("Phase régulière").run()
assert not at.exception and points(at) > 200
ok("Rugby : passage au Pro D2, saison remise à 2025-26, phase régulière")

# Toutes les saisons
season = widget(at, "selectbox", "Saison")
season.set_value(season.options[0]).run()
assert not at.exception, at.exception
assert at.title[0].value == "Rugby · Pro D2 · Toutes les saisons (2022-23 → 2025-26)", at.title[0].value
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
assert at.title[0].value == "Rugby · Top 14 · Toutes les saisons (2021-22 → 2025-26)"
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

assert not writes, writes
print("Tous les contrôles du Dashboard sont passés.")
