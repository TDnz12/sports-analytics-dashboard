"""Agrégation par saison (data_sources/rugby/aggregate.py) sur une mini-saison construite à la main :
2 équipes, 3 matchs (2 de phase régulière, 1 phase finale).

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import math
import unittest

import numpy as np
import pandas as pd

from data_sources.base import COMMON_COLUMNS
from data_sources.rugby import schema
from data_sources.rugby.aggregate import aggregate_season

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
    ]
    lineups, pm = [], []
    for match, team, player, name, jersey, minutes, stats in rows:
        lineups.append({"match_uid": match, "team_uid": team, "player_uid": player,
                        "player_name": name, "jersey": jersey, "is_starter": jersey <= 15})
        row = {c: 0.0 for c in schema.PLAYER_MATCH_STAT_COLUMNS}
        row.update({"try_assists": np.nan, "lineout_throws": np.nan, "lineout_throws_won": np.nan})
        row.update(stats)
        row["goal_attempts"] = (row["conversions_made"] + row["conversions_missed"]
                                + row["penalty_goals_made"] + row["penalty_goals_missed"])
        row.update({"match_uid": match, "team_uid": team, "player_uid": player, "minutes": minutes,
                    "minutes_method": "source" if minutes == minutes else "echec",
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

    def test_equipe_du_dernier_match_et_disponibilite(self):
        p = self.all.loc["icw:30"]
        self.assertEqual((p["team"], p["team_uid"]), ("Alpha", A))
        self.assertEqual(p["team_matches_span"], 2)      # 1 match avec Beta + 1 avec Alpha
        b = self.all.loc["icw:12"]                       # matchs 101 et 103 sur 3 d'Alpha
        self.assertEqual(b["team_matches_span"], 3)
        self.assertAlmostEqual(b["availability"], 2 / 3)

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


if __name__ == "__main__":
    unittest.main()
