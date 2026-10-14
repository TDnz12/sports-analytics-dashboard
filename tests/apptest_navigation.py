"""Vérifie que le sport et la compétition persistent d'une page à l'autre (Dashboard <-> Radar), avec
de vrais changements de page dans une même session (AppTest.switch_page), sans injecter
selected_sport ni selected_competition.

Deux modes :
- "AppTest" : changement de page tel qu'AppTest l'exécute. Streamlit y efface l'état des widgets de
  la page quittée à la fin du premier run de la nouvelle page (ce mode reproduisait le retour en
  NBA du Dashboard avant la correction) ;
- "strict" : comme dans le navigateur, la nouvelle page démarre sans aucun état des widgets de la
  page quittée. AppTest.switch_page renvoie au premier run les valeurs des widgets encore affichés
  (ceux de l'ancienne page) : le mode strict ouvre donc la page dans une nouvelle session AppTest,
  avec seulement les clés de session qui ne sont pas des widgets de la page quittée (ce mode
  reproduisait aussi le Radar ouvert en NBA depuis un Dashboard en rugby).

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
from streamlit.testing.v1 import AppTest

DASHBOARD, RADAR = "Dashboard.py", "pages/1_Radar_de_comparaison.py"
# Clés de widgets de chaque page (effacées par le navigateur quand on la quitte).
WIDGET_KEYS = {
    DASHBOARD: ["main_sport", "main_competition", "main_season", "min_minutes", "min_games",
                "show_low_sample"],
    RADAR: ["radar_sport", "radar_competition", "radar_season", "radar_period", "radar_players"],
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
    assert s.title() == "Radar de comparaison · 2024-25", s.title()
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

# 5. Radar ouvert en premier, sans passer par le Dashboard : NBA ; Rugby choisi -> Dashboard Rugby
at = AppTest.from_file(str(ROOT / RADAR), default_timeout=300).run()
assert select(at, "Sport").value == "nba" and at.title[0].value == "Radar de comparaison · 2024-25"
select(at, "Sport", "rugby")
select(at, "Compétition", "prod2")
kept = {k: v for k, v in at.session_state.to_dict().items() if k not in WIDGET_KEYS[RADAR]}
at = AppTest.from_file(str(ROOT / DASHBOARD), default_timeout=300)
for k, v in kept.items():
    at.session_state[k] = v
at.run()
assert not at.exception and at.title[0].value == "Rugby · Pro D2 · 2025-26", at.title[0].value
ok("Radar ouvert en premier : NBA par défaut ; Rugby Pro D2 choisi sur le Radar -> Dashboard Rugby Pro D2")

assert writes == [], writes
ok("aucune écriture disque")
print("\nTous les contrôles de navigation entre pages sont OK")
