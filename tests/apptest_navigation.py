"""Vérifie que le sport, la compétition et la saison persistent d'une page à l'autre (Dashboard,
Radar, Effectifs), avec de vrais changements de page dans une même session (AppTest.switch_page),
sans injecter selected_sport, selected_competition ni selected_season. Vérifie aussi le bouton
« Voir le profil radar » du Dashboard.

Deux modes :
- "AppTest" : changement de page tel qu'AppTest l'exécute. Streamlit y efface l'état des widgets de
  la page quittée à la fin du premier run de la nouvelle page (ce mode reproduisait le retour en
  NBA du Dashboard avant la correction) ;
- "strict" : comme dans le navigateur, la nouvelle page démarre sans aucun état des widgets de la
  page quittée. AppTest.switch_page renvoie au premier run les valeurs des widgets encore affichés
  (ceux de l'ancienne page) : le mode strict ouvre donc la page dans une nouvelle session AppTest,
  avec seulement les clés de session qui ne sont pas des widgets de la page quittée (ce mode
  reproduisait aussi le Radar ouvert en NBA depuis un Dashboard en rugby).

Bouton « Voir le profil radar » : AppTest ne sait pas changer de page depuis un callback (il crée
un gestionnaire de pages neuf à chaque run, et les callbacks passent avant que les pages de pages/
soient enregistrées : StreamlitPageNotFoundError, alors que le navigateur, lui, garde ce
gestionnaire). st.switch_page est donc remplacé pendant ce test pour noter la page demandée, puis
le test change de page lui-même (dans les deux modes).

Lit les caches de data_cache/ sans jamais les modifier (écritures interceptées).
Lancer depuis la racine du projet :  .venv/bin/python tests/apptest_navigation.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import data_sources.nba as nba, data_sources.base as base
writes = []
nba.write_cache = base.write_cache = lambda df, path, **k: writes.append(str(path))
import streamlit as st
from data_sources import SPORTS
from streamlit.testing.v1 import AppTest

DASHBOARD, RADAR, EFFECTIFS = "Dashboard.py", "pages/1_Radar_de_comparaison.py", "pages/2_Effectifs.py"
NBA_ONLY_NOTE = "Page NBA uniquement pour l'instant. Le Dashboard et le Radar restent sur Rugby · Top 14."
# Clés de widgets de chaque page (effacées par le navigateur quand on la quitte).
WIDGET_KEYS = {
    DASHBOARD: ["main_sport", "main_competition", "main_season", "min_minutes", "min_games",
                "show_low_sample"],
    RADAR: ["radar_sport", "radar_competition", "radar_season", "radar_period", "radar_players"],
    EFFECTIFS: ["effectifs_season", "mercato_grid"],
}
ok = lambda name: print("ok -", name)


def select(at, label, value=None):
    widget = next((s for s in at.selectbox if s.label == label), None)
    if value is not None:
        widget.set_value(value).run()
        assert not at.exception, at.exception
    return widget


class Session:
    def __init__(self, strict: bool):
        self.strict = strict
        self.page = DASHBOARD
        self.at = AppTest.from_file(str(ROOT / DASHBOARD), default_timeout=300).run()
        assert not self.at.exception, self.at.exception

    def go(self, page: str):
        if self.strict:
            kept = {k: v for k, v in self.at.session_state.to_dict().items()
                    if k not in WIDGET_KEYS[self.page]}
            self.at = AppTest.from_file(str(ROOT / page), default_timeout=300)
            for k, v in kept.items():
                self.at.session_state[k] = v
            self.at.run()
        else:
            self.at.switch_page(page).run()
        assert not self.at.exception, self.at.exception
        self.page = page
        return self.at

    def title(self):
        return self.at.title[0].value

    def season(self):
        return select(self.at, "Saison").value

    def captions(self):
        return [c.value for c in self.at.caption]


for strict in (False, True):
    mode = "strict" if strict else "AppTest"
    s = Session(strict)
    assert s.title() == "Basketball (NBA) · 2024-25", s.title()

    # 1. Dashboard en Rugby, Pro D2 -> Radar : Rugby, Pro D2
    select(s.at, "Sport", "rugby")
    select(s.at, "Compétition", "prod2")
    assert s.title() == "Rugby · Pro D2 · 2025-26", s.title()
    s.go(RADAR)
    assert (select(s.at, "Sport").value, select(s.at, "Compétition").value) == ("rugby", "prod2")
    assert s.title() == "Radar de comparaison · Pro D2 · 2025-26", s.title()
    # Un rerun sur la même page ne change rien.
    s.at.run()
    assert select(s.at, "Compétition").value == "prod2" and not s.at.exception

    # 2. Compétition changée sur le Radar -> Dashboard : Rugby, Top 14
    select(s.at, "Compétition", "top14")
    s.go(DASHBOARD)
    assert s.title() == "Rugby · Top 14 · 2025-26", s.title()
    s.at.run()
    assert s.title() == "Rugby · Top 14 · 2025-26", s.title()
    ok(f"{mode} : Dashboard Rugby Pro D2 -> Radar Pro D2 ; Top 14 choisi sur le Radar -> Dashboard Top 14")

    # 3. NBA choisie sur le Radar -> Dashboard en NBA ; puis Rugby sur le Dashboard -> Radar en
    # Rugby, compétition gardée (Top 14)
    s.go(RADAR)
    assert select(s.at, "Compétition").value == "top14"
    select(s.at, "Sport", "nba")
    assert s.title() == "Radar de comparaison · NBA · 2024-25", s.title()
    s.go(DASHBOARD)
    assert s.title() == "Basketball (NBA) · 2024-25", s.title()
    select(s.at, "Sport", "rugby")
    assert s.title() == "Rugby · Top 14 · 2025-26", s.title()
    s.go(RADAR)
    assert (select(s.at, "Sport").value, select(s.at, "Compétition").value) == ("rugby", "top14")
    ok(f"{mode} : NBA choisie sur le Radar -> Dashboard NBA ; Rugby sur le Dashboard -> Radar Rugby, Top 14 gardé")

    # 4. Aller-retour sans rien toucher : rien ne bouge
    for _ in range(2):
        s.go(DASHBOARD)
        assert s.title() == "Rugby · Top 14 · 2025-26", s.title()
        s.go(RADAR)
        assert s.title() == "Radar de comparaison · Top 14 · 2025-26", s.title()
    ok(f"{mode} : allers-retours répétés sans changement")

    # 6. Saison NBA partagée entre les 3 pages, dans tous les sens
    s = Session(strict)
    select(s.at, "Saison", "2022-23")
    s.go(EFFECTIFS)
    assert s.title() == "Effectifs" and s.season() == "2022-23", s.season()
    assert NBA_ONLY_NOTE not in s.captions()
    select(s.at, "Saison", "2019-20")
    s.go(DASHBOARD)
    assert s.title() == "Basketball (NBA) · 2019-20", s.title()
    s.go(RADAR)
    assert s.title() == "Radar de comparaison · NBA · 2019-20", s.title()
    select(s.at, "Saison", "2021-22")
    s.go(EFFECTIFS)
    assert s.season() == "2021-22", s.season()
    s.go(DASHBOARD)
    assert s.title() == "Basketball (NBA) · 2021-22", s.title()
    ok(f"{mode} : saison NBA gardée Dashboard -> Effectifs -> Dashboard -> Radar -> Effectifs -> Dashboard")

    # 7. Rugby choisi sur le Dashboard -> Effectifs en NBA avec la note ; saison changée sur
    # Effectifs -> Dashboard toujours en Rugby Top 14 2023-24
    select(s.at, "Sport", "rugby")
    select(s.at, "Saison", "2023-24")
    assert s.title() == "Rugby · Top 14 · 2023-24", s.title()
    s.go(EFFECTIFS)
    assert s.season() == "2024-25" and NBA_ONLY_NOTE in s.captions(), (s.season(), s.captions())
    select(s.at, "Saison", "2018-19")
    s.go(DASHBOARD)
    assert s.title() == "Rugby · Top 14 · 2023-24", s.title()
    s.go(RADAR)
    assert s.title() == "Radar de comparaison · Top 14 · 2023-24", s.title()
    ok(f"{mode} : Rugby Top 14 2023-24 -> Effectifs NBA avec la note -> Dashboard et Radar Rugby Top 14 2023-24")

    # 8. "Toutes les saisons" en NBA : gardée par le Dashboard après un passage par le Radar et
    # Effectifs (qui ne l'ont pas), jusqu'à ce qu'on change la saison sur le Radar
    s.go(DASHBOARD)
    select(s.at, "Sport", "nba")
    all_label = next(o for o in select(s.at, "Saison").options if o.startswith("Toutes les saisons"))
    select(s.at, "Saison", all_label)
    all_title = s.title()
    assert all_title.startswith("Basketball (NBA) · Toutes les saisons"), all_title
    s.go(RADAR)
    assert s.title() == "Radar de comparaison · NBA · 2024-25", s.title()
    s.go(EFFECTIFS)
    assert s.season() == "2024-25", s.season()
    s.go(DASHBOARD)
    assert s.title() == all_title, s.title()
    s.go(RADAR)
    select(s.at, "Saison", "2020-21")
    s.go(DASHBOARD)
    assert s.title() == "Basketball (NBA) · 2020-21", s.title()
    ok(f"{mode} : « Toutes les saisons » gardée après Radar et Effectifs, remplacée par une saison choisie sur le Radar")

# 5. Radar ouvert en premier, sans passer par le Dashboard : NBA ; Rugby choisi -> Dashboard Rugby
at = AppTest.from_file(str(ROOT / RADAR), default_timeout=300).run()
assert select(at, "Sport").value == "nba" and at.title[0].value == "Radar de comparaison · NBA · 2024-25"
select(at, "Sport", "rugby")
select(at, "Compétition", "prod2")
kept = {k: v for k, v in at.session_state.to_dict().items() if k not in WIDGET_KEYS[RADAR]}
at = AppTest.from_file(str(ROOT / DASHBOARD), default_timeout=300)
for k, v in kept.items():
    at.session_state[k] = v
at.run()
assert not at.exception and at.title[0].value == "Rugby · Pro D2 · 2025-26", at.title[0].value
ok("Radar ouvert en premier : NBA par défaut ; Rugby Pro D2 choisi sur le Radar -> Dashboard Rugby Pro D2")

# 9. Bouton « Voir le profil radar » (st.switch_page remplacé, voir la docstring), en rugby (Pro D2
# 2023-24, phase régulière) puis en NBA (2022-23) : le Radar s'ouvre avec le joueur, le sport, la
# compétition, la saison et la période du Dashboard.
def top_player(sport_key, competition, season, period_label):
    sport = SPORTS[sport_key]
    periods = sport.stats_periods or {}
    kwargs = {"competition": competition} if competition else {}
    df = sport.get_player_stats(season, force_refresh=False, period=periods.get(period_label, "regular"), **kwargs)
    minutes = "minutes_total" if "minutes_total" in df.columns else "minutes_per_game"
    return df.sort_values(minutes, ascending=False)[sport.player_label_col or "player"].iloc[0]


switched = []
real_switch_page = st.switch_page
st.switch_page = lambda page, **kwargs: switched.append(page)
try:
    for strict in (False, True):
        mode = "strict" if strict else "AppTest"
        for sport_key, competition, season, period in (
            ("rugby", "prod2", "2023-24", "Phase régulière"),
            ("nba", None, "2022-23", None),
        ):
            s = Session(strict)
            select(s.at, "Sport", sport_key)
            if competition:
                select(s.at, "Compétition", competition)
            select(s.at, "Saison", season)
            if period:
                select(s.at, "Statistiques utilisées", period)
            # Joueur qui a le plus de minutes : il a forcément un radar (rugby : poste déterminé).
            name = top_player(sport_key, competition, season, period)
            select(s.at, "Rechercher un joueur", name)
            switched.clear()
            next(b for b in s.at.button if b.label == "Voir le profil radar").click().run()
            assert not s.at.exception, s.at.exception
            assert switched == [RADAR], switched
            player_key = s.at.session_state["radar_preselect_player"]
            s.go(RADAR)
            players = next(m for m in s.at.multiselect if m.label.startswith("Joueurs"))
            assert players.value == [player_key], (players.value, player_key)
            assert select(s.at, "Sport").value == sport_key
            if competition:
                assert select(s.at, "Compétition").value == competition
            assert s.season() == season, s.season()
            if period:
                assert select(s.at, "Statistiques utilisées").value == period
            assert "radar_preselect_player" not in s.at.session_state
            ok(f"{mode} : bouton « Voir le profil radar » ({sport_key}, {season}) -> Radar avec {name}")
finally:
    st.switch_page = real_switch_page

assert writes == [], writes
ok("aucune écriture disque")
print("\nTous les contrôles de navigation entre pages sont OK")
