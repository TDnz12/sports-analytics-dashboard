"""Corrections des lots 3 et 4 de l'audit rugby, vérifiées sur les vrais caches de data_cache/ :
minute négative de Delannoy (B.3), compteurs de score faux (B.0), club principal par les minutes
(B.2), badge "poste mixte" et postes secondaires (B.1).

Lit les caches versionnés, n'écrit rien.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import json
import unittest

import pandas as pd

from data_sources.base import read_cache
from data_sources.rugby import schema, stats


def raw(competition: str, season: str, table: str) -> pd.DataFrame:
    return read_cache(schema.raw_table_path(competition, season, table),
                      schema_version=schema.RUGBY_RAW_TABLES_SCHEMA_VERSION)


def player(df: pd.DataFrame, uid: str) -> pd.Series:
    return df.set_index("player_uid").loc[uid]


DELANNOY, CHINARRO, RAMOS, NTAMACK = "icw:171430", "icw:244548", "icw:175123", "icw:122907"
GRAY, BOUDEHENT, OLLIVON = "icw:171323", "icw:216116", "icw:198942"


class MinuteNegativeTest(unittest.TestCase):
    def test_delannoy(self):
        pm = raw("prod2", "2023-24", "player_match")
        mine = pm[pm["player_uid"] == DELANNOY]
        line = mine.set_index("match_uid").loc["icw:276697"]
        self.assertTrue(pd.isna(line["minutes"]))
        self.assertEqual(line["minutes_method"], "echec")
        self.assertTrue(line["appeared"])
        d = player(stats.get_player_stats("2023-24", competition="prod2"), DELANNOY)
        self.assertEqual(d["games_played"], int(mine["appeared"].sum()))
        played = mine[mine["minutes"] > 0]
        self.assertEqual(d["minutes_total"], played["minutes"].sum())
        # Plaquages par 80 sans cette ligne (5 plaquages, minutes inconnues) ; total avec.
        self.assertAlmostEqual(d["tackles_per80"], played["tackles"].sum() / played["minutes"].sum() * 80)
        self.assertEqual(d["tackles"], mine["tackles"].sum())

    def test_aucune_minute_negative(self):
        for comp in ("top14", "prod2"):
            for season in schema.season_labels(comp):
                with self.subTest(competition=comp, saison=season):
                    self.assertFalse((raw(comp, season, "player_match")["minutes"] < 0).any())


class CompteursDeScoreTest(unittest.TestCase):
    def test_chinarro_deux_essais(self):
        self.assertEqual(player(stats.get_player_stats("2025-26", competition="top14"), CHINARRO)["tries"], 2)

    def test_transformation_de_ramos_rendue(self):
        pm = raw("top14", "2022-23", "player_match")
        pm = pm[pm["match_uid"] == "icw:270624"].set_index("player_uid")
        ev = raw("top14", "2022-23", "events")
        conv = ev[(ev["match_uid"] == "icw:270624") & (ev["type"] == "conversion")]["player_uid"].value_counts()
        for uid in (RAMOS, NTAMACK):
            self.assertEqual(pm.loc[uid, "conversions_made"], conv.get(uid, 0))
            self.assertEqual(pm.loc[uid, "score_source"], "evenements_ligne")

    def test_lignes_corrigees_coherentes(self):
        n = 0
        for comp in ("top14", "prod2"):
            for season in schema.season_labels(comp):
                pm = raw(comp, season, "player_match")
                fixed = pm[pm["score_source"] == "evenements_ligne"]
                n += len(fixed)
                points = (5 * fixed["tries"] + 2 * fixed["conversions_made"]
                          + 3 * fixed["penalty_goals_made"] + 3 * fixed["drop_goals_made"])
                self.assertTrue((points == fixed["points"]).all(), (comp, season))
        self.assertEqual(n, 19)


class ClubsEtPostesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = stats.get_player_stats("2025-26", competition="top14")

    def test_gray_club_principal_et_deux_clubs(self):
        g = player(self.df, GRAY)
        self.assertEqual(g["team"], "Bordeaux-Bègles")
        self.assertEqual(g["clubs"], "Bordeaux-Bègles (10), Perpignan (4)")
        self.assertEqual(g["club_names"], ("Bordeaux-Bègles", "Perpignan"))
        self.assertEqual(len(json.loads(g["clubs_detail"])), 2)

    def test_un_seul_club_sans_mention(self):
        one = self.df[self.df["club_names"].map(len) == 1]
        self.assertTrue(one["clubs"].isna().all())
        self.assertTrue((one["club_names"].map(lambda c: c[0]) == one["team"]).all())

    def test_poste_mixte_sous_60_pourcent(self):
        o = player(self.df, OLLIVON)                     # n° 8 la moitié de ses titularisations
        self.assertTrue(o["mixed_position"])
        self.assertEqual(o["secondary_positions"], "Deuxième ligne 38 %, Troisième ligne aile 12 %")
        b = player(self.df, BOUDEHENT)                   # 8 sur 13 en deuxième ligne : 62 %
        self.assertFalse(b["mixed_position"])
        self.assertEqual(b["secondary_positions"], "Troisième ligne aile 38 %")
        mixed = self.df[self.df["mixed_position"]]
        self.assertTrue((mixed["position_share"] < 0.6).all())
        self.assertTrue((mixed["position_source"] == "titulaire").all())


if __name__ == "__main__":
    unittest.main()
