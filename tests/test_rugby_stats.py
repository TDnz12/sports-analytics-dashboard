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

import pandas as pd

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


class FenetreTest(unittest.TestCase):
    def test_lecture_des_fenetres(self):
        for comp, season in (("top14", "2025-26"), ("top14", "2023-24"), ("prod2", "2024-25")):
            for period in schema.PERIODS:
                with self.subTest(comp=comp, season=season, period=period):
                    one = stats.get_player_stats(season, period=period, competition=comp)
                    df = stats.get_player_stats(season, period=period, competition=comp, window=3)
                    self.assertGreater(len(df), len(one))
                    self.assertTrue(set(one["player_uid"]) <= set(df["player_uid"]))
                    self.assertTrue((df["season"] == season).all())
                    self.assertNotIn("_schema_version", df.columns)
                    for m in stats.METRICS.values():
                        self.assertIn(m.key, df.columns)
                    self.assertFalse(df["player_label"].duplicated().any())

    def test_detail_par_saison_avec_noms_affiches(self):
        df = stats.get_player_stats("2025-26", competition="top14", window=3).set_index("player_uid")
        self.assertEqual([s[:2] for s in df.at["icw:101948", "seasons"]],   # Madosh Tambwe
                         [("2023-24", "Bordeaux-Bègles"), ("2024-25", "Montpellier"),
                          ("2025-26", "Bordeaux-Bègles")])
        self.assertNotIn("seasons", stats.get_player_stats("2025-26", competition="top14").columns)

    def test_fenetre_indisponible(self):
        with self.assertRaises(ValueError):
            stats.get_player_stats("2022-23", competition="top14", window=3)
        with self.assertRaises(ValueError):
            stats.get_player_stats("2025-26", competition="top14", window=2)

    def test_cache_de_fenetre_absent(self):
        with mock.patch.object(schema, "RUGBY_WINDOW_SCHEMA_VERSION", 999):
            with self.assertRaisesRegex(FileNotFoundError, "--comp top14 --windows-only"):
                stats.get_player_stats("2025-26", competition="top14", window=3)


class NomsDeJoueursTest(unittest.TestCase):
    def test_une_graphie_par_joueur(self):
        """Nom, prénom et nom de famille identiques sur toutes les saisons des deux compétitions
        (29 identifiants ont plusieurs graphies dans la source), sauf les identifiants exclus."""
        names = {}
        for comp in ("top14", "prod2"):
            for season in schema.season_labels(comp):
                df = stats.get_player_stats(season, competition=comp)
                for uid, *n in zip(df["player_uid"], df["player"], df["first_name"], df["last_name"]):
                    names.setdefault(uid, set()).add(tuple(n))
        several = {uid for uid, n in names.items() if len(n) > 1}
        self.assertEqual(several, stats.SINGLE_NAME_EXCLUDED)

    def test_identifiant_exclu_garde_ses_graphies(self):
        seasons = {s: stats.get_player_stats(s, competition="prod2") for s in ("2023-24", "2025-26")}
        shown = {s: df.loc[df["player_uid"] == "icw:229659", "player"].tolist() for s, df in seasons.items()}
        self.assertEqual(shown, {"2023-24": ["Aurelien Lisena"], "2025-26": ["Aurelien Lafforgue"]})

    def test_alldritt_en_2021_22(self):
        df = stats.get_player_stats("2021-22", competition="top14")
        self.assertEqual(df.loc[df["player_uid"] == "icw:157570", "player"].tolist(), ["Grégory Alldritt"])

    def test_graphie_accentuee_prioritaire(self):
        lineups = pd.DataFrame({
            "player_uid": ["a", "a", "b", "b"],
            "player_name": ["Grégory X", "Gregory X", "Grégory Y", "Greg Y"],
            "first_name": ["Grégory", "Gregory", "Grégory", "Greg"], "last_name": ["X", "X", "Y", "Y"],
            "date_utc": [1, 2, 1, 2],
        })
        out = stats.canonical_names(lineups)
        self.assertEqual(out.loc["a", "player"], "Grégory X")  # même nom sans accents : accentué
        self.assertEqual(out.loc["b", "player"], "Greg Y")     # autre nom : le plus récent

    def test_corrections_manuelles(self):
        df = stats.get_player_stats("2025-26", competition="top14")
        self.assertEqual(df.loc[df["player_uid"] == "icw:199515", "player"].tolist(), ["Gaël Fickou"])
        with mock.patch.dict(stats.PLAYER_DISPLAY_NAMES, {"icw:157570": "Test Alldritt"}):
            df = stats.get_player_stats("2025-26", competition="top14")
        self.assertEqual(df.loc[df["player_uid"] == "icw:157570", "player"].tolist(), ["Test Alldritt"])

    def test_hilsenbeck(self):
        for season in ("2022-23", "2023-24"):
            df = stats.get_player_stats(season, competition="prod2")
            self.assertEqual(df.loc[df["player_uid"] == "icw:137322", "player"].tolist(), ["Chris Hilsenbeck"])

    def test_berguet(self):
        """Un seul joueur sous "Charlesty Berguet" et "Martin Berguet" (règle 1), nom corrigé partout."""
        for comp, season in (("top14", "2024-25"), ("prod2", "2022-23"), ("prod2", "2023-24"),
                             ("prod2", "2025-26")):
            df = stats.get_player_stats(season, competition=comp)
            self.assertEqual(df.loc[df["player_uid"] == "icw:161580", "player"].tolist(),
                             ["Charles-Henri Berguet"])


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
