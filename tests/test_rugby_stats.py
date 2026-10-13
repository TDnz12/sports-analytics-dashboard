"""Lecture des stats joueurs rugby pour le Dashboard (data_sources/rugby/stats.py) : chaque saison
des compétitions livrées se lit depuis data_cache/ avec les colonnes du catalogue METRICS, les
colonnes d'affichage sont ajoutées, et un cache absent lève une erreur claire au lieu d'un appel
réseau.

Lit les caches versionnés, n'écrit rien.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest
from pathlib import Path
from unittest import mock

from data_sources import SPORTS
from data_sources.rugby import schema, stats


class LectureTest(unittest.TestCase):
    def test_toutes_les_saisons_livrees(self):
        for comp in SPORTS["rugby"].competitions:
            if not comp.available:
                continue
            for season in comp.seasons:
                for period in schema.PERIODS:
                    with self.subTest(competition=comp.key, saison=season, periode=period):
                        df = stats.get_player_stats(season, period=period, competition=comp.key)
                        self.assertGreater(len(df), 300)
                        self.assertTrue((df["competition"] == comp.key).all())
                        self.assertNotIn("_schema_version", df.columns)
                        for m in stats.METRICS.values():
                            self.assertIn(m.key, df.columns)
                            for col in (m.made_col, m.attempts_col):
                                if col:
                                    self.assertIn(col, df.columns)
                        for col in list(stats.DETAIL_LEAD_COLUMNS) + list(stats.DETAIL_TAIL_COLUMNS):
                            self.assertIn(col, df.columns)

    def test_colonnes_d_affichage(self):
        df = stats.get_player_stats("2024-25", competition="top14")
        banc = df[df["position_source"] == "banc"]
        self.assertTrue(len(banc))
        self.assertTrue(banc["position_label"].str.endswith(" (banc)").all())
        titulaires = df[df["position_source"] == "titulaire"]
        self.assertTrue((titulaires["position_label"] == titulaires["position_group"]).all())
        self.assertEqual(set(df["position_family"]), {"Avants", "Arrières", "Indéterminé"})
        self.assertTrue(df["cards"].str.fullmatch(r"\d+ / \d+").all())
        # Homonymes : libellé "Nom (Club)" unique dans la saison.
        self.assertFalse(df["player_label"].duplicated().any())

    def test_noms_d_equipes_accentues(self):
        teams = set()
        for comp in ("top14", "prod2"):
            for season in schema.season_labels(comp):
                teams |= set(stats.get_player_stats(season, competition=comp)["team"])
        for name in stats.TEAM_DISPLAY_NAMES.values():
            self.assertIn(name, teams)
        for raw in ("Bordeaux-Begles", "Stade Francais Paris", "Beziers", "Soyaux Angouleme"):
            self.assertNotIn(raw, teams)
        # Cache inchangé : le nom de la source y reste.
        import pandas as pd
        cached = pd.read_parquet(schema.processed_path("top14", "2025-26"))
        self.assertIn("Bordeaux-Begles", set(cached["team"]))

    def test_cache_absent(self):
        with mock.patch.object(schema, "RUGBY_PROCESSED_DIR", Path("/nonexistent/rugby")):
            with self.assertRaisesRegex(FileNotFoundError, "rugby_build.py --comp prod2"):
                stats.get_player_stats("2024-25", competition="prod2")

    def test_cache_d_une_autre_version(self):
        with mock.patch.object(schema, "RUGBY_PROCESSED_SCHEMA_VERSION", 999):
            with self.assertRaises(FileNotFoundError):
                stats.get_player_stats("2024-25", competition="top14")


class CatalogueTest(unittest.TestCase):
    def test_seuils_nc_de_la_calibration(self):
        m = stats.METRICS
        self.assertEqual((m["tackle_pct"].min_attempts, m["gain_line_pct"].min_attempts,
                          m["goal_kick_pct"].min_attempts), (25, 20, 35))

    def test_peu_fiables(self):
        # Fiabilité sous 0,4 à 520 min, tous postes (calibration_v1.md, section 5).
        unreliable = {k for k, m in stats.METRICS.items() if m.unreliable}
        self.assertEqual(unreliable, {
            "penalties_conceded_per80", "turnovers_conceded_per80", "missed_tackles_per80",
            "clean_breaks_per80", "tries_per80",
        })

    def test_pas_de_colonne_vide_en_club(self):
        df = stats.get_player_stats("2025-26", competition="top14")
        for key in stats.METRICS:
            with self.subTest(metrique=key):
                self.assertTrue(df[key].notna().any())


if __name__ == "__main__":
    unittest.main()
