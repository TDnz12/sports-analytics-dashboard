"""Agrégation par saison (data_sources/rugby/aggregate.py) sur une mini-saison construite à la main :
2 équipes, 3 matchs (2 de phase régulière, 1 phase finale). Club principal par les minutes, clubs_detail,
par 80 sur les seuls matchs à minutes > 0 où la stat est connue (décisions B.2, B.3 et C4 de l'audit).
Fenêtre de 3 saisons (aggregate_window, mode 3 saisons du radar) sur 3 mini-saisons.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import json
import math
import unittest

import numpy as np
import pandas as pd

from data_sources.base import COMMON_COLUMNS
from data_sources.rugby import schema
from data_sources.rugby.aggregate import aggregate_season, aggregate_window

A, B = "icw:1", "icw:2"


def mini_season():
    matches = pd.DataFrame({
        "match_uid": ["icw:101", "icw:102", "icw:103"], "season": "2025-26",
        "date_utc": pd.to_datetime(["2025-09-01", "2025-09-08", "2026-06-01"], utc=True),
        "phase": ["regular", "regular", "final"],
        "home_team_uid": [A, B, A], "home_team": ["Alpha", "Beta", "Alpha"],
        "away_team_uid": [B, A, B], "away_team": ["Beta", "Alpha", "Beta"],
    })
    # (match, équipe, joueur, nom, maillot, minutes, stats particulières)
    rows = [
        ("icw:101", A, "icw:10", "Dupont", 9, 80, {"tackles": 8, "missed_tackles": 2}),
        ("icw:102", A, "icw:10", "Dupont", 9, 40, {"tackles": 4}),
        ("icw:103", A, "icw:10", "Dupont", 9, np.nan, {"tackles": 100}),   # minutes inconnues
        ("icw:101", A, "icw:11", "Martin", 17, 0, {}),                      # sur le banc, pas entré
        ("icw:101", A, "icw:12", "Bernard", 4, 80, {}),
        ("icw:103", A, "icw:12", "Bernard", 4, 80, {}),
        ("icw:101", B, "icw:20", "Martin", 10, 80,
         {"conversions_made": 2, "conversions_missed": 1, "penalty_goals_made": 3,
          "penalty_goals_missed": 2, "drop_goals_made": 1}),
        ("icw:101", B, "icw:30", "Petit", 12, 80, {}),
        ("icw:103", A, "icw:30", "Petit", 12, 60, {}),                      # transféré chez Alpha
        ("icw:101", B, "icw:40", "Roux", 13, 40, {}),                       # 40 min de chaque côté :
        ("icw:103", A, "icw:40", "Roux", 13, 40, {}),                       # le plus récent l'emporte
        ("icw:101", A, "icw:50", "Blanc", 6, 80, {"tackles": 8}),
        ("icw:102", A, "icw:50", "Blanc", 20, 0, {"tackles": 3}),           # 0 min, mais des stats
        ("icw:101", A, "icw:60", "Leroy", 7, 80, {"tackles": 8, "carries": 4}),
        ("icw:102", A, "icw:60", "Leroy", 7, 40, {"tackles": np.nan, "carries": 2}),   # stat inconnue
    ]
    return build_tables(matches, rows)


def build_tables(matches, rows):
    """Tables brutes (matches, lineups, player_match) depuis des lignes (match, équipe, joueur,
    nom, maillot, minutes, stats particulières)."""
    lineups, pm = [], []
    for match, team, player, name, jersey, minutes, stats in rows:
        lineups.append({"match_uid": match, "team_uid": team, "player_uid": player,
                        "player_name": name, "first_name": "Prénom " + name, "last_name": name,
                        "jersey": jersey, "is_starter": jersey <= 15})
        row = {c: 0.0 for c in schema.PLAYER_MATCH_STAT_COLUMNS}
        row.update({"try_assists": np.nan, "lineout_throws": np.nan, "lineout_throws_won": np.nan})
        row.update(stats)
        row["goal_attempts"] = (row["conversions_made"] + row["conversions_missed"]
                                + row["penalty_goals_made"] + row["penalty_goals_missed"])
        row.update({"match_uid": match, "team_uid": team, "player_uid": player, "minutes": minutes,
                    "minutes_method": "source" if minutes == minutes else "echec",
                    "score_source": "source",
                    "appeared": bool(minutes > 0) if minutes == minutes else True})
        pm.append(row)
    return {"matches": matches, "lineups": pd.DataFrame(lineups),
            "player_match": pd.DataFrame(pm)[schema.PLAYER_MATCH_COLUMNS]}


class AggregateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = mini_season()
        cls.all = aggregate_season(cls.tables, "top14", "all").set_index("player_uid")
        cls.regular = aggregate_season(cls.tables, "top14", "regular").set_index("player_uid")

    def test_prenom_et_nom(self):
        # Repris de la composition du dernier match, comme le nom affiché.
        self.assertTrue((self.all["last_name"] == self.all["player"]).all())
        self.assertTrue((self.all["first_name"] == "Prénom " + self.all["player"]).all())

    def test_contrat_commun(self):
        for col in COMMON_COLUMNS:
            self.assertIn(col, self.all.columns)
        self.assertTrue((self.all["sport"] == "rugby").all())
        self.assertTrue((self.all["season"] == "2025-26").all())

    def test_par_80_sur_les_matchs_a_minutes_connues(self):
        d = self.all.loc["icw:10"]
        self.assertEqual(d["games_played"], 3)          # le match à minutes inconnues compte
        self.assertEqual(d["minutes_total"], 120)
        self.assertEqual(d["tackles"], 112)             # total : tous les matchs
        self.assertAlmostEqual(d["tackles_per80"], (8 + 4) / 120 * 80)   # sans le match 103

    def test_pourcentages_depuis_les_sommes(self):
        d = self.all.loc["icw:10"]
        self.assertAlmostEqual(d["tackle_pct"], 112 / 114)
        k = self.all.loc["icw:20"]
        self.assertEqual(k["goal_attempts"], 8)          # drops exclus
        self.assertAlmostEqual(k["goal_kick_pct"], 5 / 8)

    def test_stat_absente_reste_nan(self):
        self.assertTrue(self.all["try_assists"].isna().all())
        self.assertTrue(self.all["try_assists_per80"].isna().all())
        self.assertNotIn("yellow_cards_per80", self.all.columns)

    def test_periode_reguliere_sans_phases_finales(self):
        d = self.regular.loc["icw:10"]
        self.assertEqual((d["games_played"], d["minutes_total"], d["tackles"]), (2, 120, 12))
        self.assertEqual(self.regular.loc["icw:30", "team"], "Beta")   # avant son transfert

    def test_club_principal_le_plus_de_minutes_et_disponibilite(self):
        p = self.all.loc["icw:30"]                       # 80 min avec Beta, puis 60 avec Alpha
        self.assertEqual((p["team"], p["team_uid"]), ("Beta", B))
        self.assertEqual(json.loads(p["clubs_detail"]), [[B, "Beta", 1], [A, "Alpha", 1]])
        self.assertEqual(p["team_matches_span"], 2)      # 1 match avec Beta + 1 avec Alpha
        b = self.all.loc["icw:12"]                       # matchs 101 et 103 sur 3 d'Alpha
        self.assertEqual(b["team_matches_span"], 3)
        self.assertAlmostEqual(b["availability"], 2 / 3)

    def test_club_egalite_le_plus_recent(self):
        r = self.all.loc["icw:40"]                       # minutes et matchs à égalité
        self.assertEqual(r["team_uid"], A)
        self.assertEqual(json.loads(self.all.loc["icw:10", "clubs_detail"]), [[A, "Alpha", 3]])
        self.assertEqual(json.loads(self.all.loc["icw:11", "clubs_detail"]), [])   # jamais entré

    def test_par_80_sans_les_lignes_a_0_minute(self):
        b = self.all.loc["icw:50"]
        self.assertEqual(b["tackles"], 11)               # total : toutes les lignes
        self.assertAlmostEqual(b["tackles_per80"], 8)    # 8 / 80 x 80, sans la ligne à 0 min

    def test_par_80_stat_par_stat(self):
        r = self.all.loc["icw:60"]                       # plaquages inconnus au match 102
        self.assertAlmostEqual(r["tackles_per80"], 8)               # 8 / 80 x 80
        self.assertAlmostEqual(r["carries_per80"], 6 / 120 * 80)    # 2 matchs, 120 min

    def test_joueur_sur_la_feuille_sans_jouer(self):
        m = self.all.loc["icw:11"]
        self.assertEqual((m["games_played"], m["matchday_squads"], m["minutes_total"]), (0, 1, 0))
        self.assertTrue(math.isnan(m["minutes_per_game"]))
        self.assertTrue(math.isnan(m["tackles_per80"]))

    def test_homonymes(self):
        self.assertEqual(self.all.loc["icw:11", "player_label"], "Martin (Alpha)")
        self.assertEqual(self.all.loc["icw:20", "player_label"], "Martin (Beta)")
        self.assertEqual(self.all.loc["icw:10", "player_label"], "Dupont")

    def test_postes_et_seuil(self):
        self.assertEqual(self.all.loc["icw:11", "position_group"], "Pilier")     # banc, n° 17
        self.assertEqual(self.all.loc["icw:11", "position_source"], "banc")
        self.assertTrue(self.all["low_sample_size"].all())     # personne n'a 5 matchs
        self.assertTrue(self.all["height_cm"].isna().all())


def mini_window():
    """3 saisons de 2 matchs Alpha-Beta. icw:70 : Alpha, puis Beta, puis Alpha (un seul match sur
    2 en 2025-26). icw:71 : deuxième ligne en 2023-24, absent en 2024-25, troisième ligne aile en
    2025-26. icw:72 : seulement en 2024-25."""
    seasons = {}
    rows_by_season = {
        "2023-24": [("1", A, "icw:70", "Garcia", 9, 80, {"tackles": 10}),
                    ("2", A, "icw:70", "Garcia", 9, 80, {"tackles": 6}),
                    ("1", A, "icw:71", "Moreau", 4, 80, {}),
                    ("2", A, "icw:71", "Moreau", 4, 80, {})],
        "2024-25": [("1", B, "icw:70", "Garcia", 9, 80, {"tackles": 4}),
                    ("2", B, "icw:70", "Garcia", 9, 40, {"tackles": 2}),
                    ("1", B, "icw:72", "Simon", 10, 80, {})],
        "2025-26": [("1", A, "icw:70", "Garcia", 9, 60, {"tackles": 3}),
                    ("1", A, "icw:71", "Moreau", 6, 80, {})],
    }
    for i, (season, rows) in enumerate(rows_by_season.items()):
        year = 2023 + i
        uid = lambda n: f"icw:{year}{n}"
        matches = pd.DataFrame({
            "match_uid": [uid("1"), uid("2")], "season": season,
            "date_utc": pd.to_datetime([f"{year}-09-01", f"{year + 1}-03-01"], utc=True),
            "phase": "regular", "home_team_uid": [A, B], "home_team": ["Alpha", "Beta"],
            "away_team_uid": [B, A], "away_team": ["Beta", "Alpha"],
        })
        seasons[season] = build_tables(matches, [(uid(r[0]),) + r[1:] for r in rows])
    return seasons


class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seasons = mini_window()
        cls.win = aggregate_window(cls.seasons, "top14").set_index("player_uid")

    def test_saison_choisie_et_fenetre(self):
        self.assertTrue((self.win["season"] == "2025-26").all())
        self.assertTrue((self.win["window_label"] == "2023-24 à 2025-26").all())
        self.assertEqual((self.win["window_start"].iloc[0], self.win["window_end"].iloc[0]),
                         ("2023-24", "2025-26"))
        self.assertEqual(set(self.win.index), {"icw:70", "icw:71", "icw:72"})

    def test_sommes_puis_division(self):
        g = self.win.loc["icw:70"]
        self.assertEqual((g["games_played"], g["minutes_total"], g["tackles"]), (5, 340, 25))
        self.assertAlmostEqual(g["tackles_per80"], 25 / 340 * 80)
        per_season = [aggregate_season(t, "top14").set_index("player_uid") for t in self.seasons.values()]
        for col in ("games_played", "starts", "matchday_squads", "minutes_total", "tackles"):
            summed = sum(d[col].reindex(self.win.index).fillna(0) for d in per_season)
            pd.testing.assert_series_equal(summed, self.win[col].astype(float), check_names=False)

    def test_disponibilite_saison_par_saison(self):
        # Alpha 2 + Beta 2 + Alpha 1 (premier et dernier match de 2025-26 confondus) = 5 ; d'un
        # seul tenant sur la fenêtre, les 2 matchs d'Alpha en 2024-25 seraient comptés en plus.
        g = self.win.loc["icw:70"]
        self.assertEqual(g["team_matches_span"], 5)
        self.assertAlmostEqual(g["availability"], 1.0)
        self.assertEqual(self.win.loc["icw:71", "team_matches_span"], 3)

    def test_club_et_poste_sur_la_fenetre(self):
        g = self.win.loc["icw:70"]                      # 220 min avec Alpha, 120 avec Beta
        self.assertEqual(g["team_uid"], A)
        m = self.win.loc["icw:71"]                      # 2 titularisations en 4, 1 en 6
        self.assertEqual(m["position_group"], "Deuxième ligne")
        self.assertEqual(m["season_position_group"], "Troisième ligne aile")
        self.assertIsNone(self.win.loc["icw:72", "season_position_group"])   # absent en 2025-26

    def test_detail_par_saison(self):
        self.assertEqual(self.win.loc["icw:70", "seasons_played"], 3)
        self.assertEqual(json.loads(self.win.loc["icw:70", "season_detail"]),
                         [["2023-24", A, "Alpha", 2, 160], ["2024-25", B, "Beta", 2, 120],
                          ["2025-26", A, "Alpha", 1, 60]])
        self.assertEqual(self.win.loc["icw:71", "seasons_played"], 2)
        self.assertEqual(json.loads(self.win.loc["icw:72", "season_detail"]),
                         [["2024-25", B, "Beta", 1, 80]])

    def test_une_saison_inchangee(self):
        # Une fenêtre d'une seule saison redonne aggregate_season (même calcul).
        one = aggregate_window({"2025-26": mini_season()}, "top14")
        ref = aggregate_season(mini_season(), "top14")
        pd.testing.assert_frame_equal(one[ref.columns], ref)


if __name__ == "__main__":
    unittest.main()
