"""Registre des sports et compétitions (data_sources/__init__.py, data_sources/rugby/schema.py) :
la NBA reste sans compétition (comportement inchangé), le rugby déclare Top 14, Pro D2 et
Six Nations avec leurs saisons, et les chemins de cache restent dans data_cache/ (les JSON bruts,
eux, hors du dépôt).

Aucun accès réseau ni disque.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import os
import unittest
from pathlib import Path
from unittest import mock

from data_sources import SPORTS
from data_sources.base import CACHE_ROOT
from data_sources.rugby import schema

PROJECT_ROOT = CACHE_ROOT.parent


class RegistreTest(unittest.TestCase):
    def test_ordre_des_sports_inchange(self):
        self.assertEqual(list(SPORTS), ["nba", "rugby", "mma", "tennis"])

    def test_nba_sans_competition(self):
        self.assertIsNone(SPORTS["nba"].competitions)
        self.assertTrue(SPORTS["nba"].available)

    def test_rugby(self):
        rugby = SPORTS["rugby"]
        self.assertEqual(rugby.label, "Rugby")
        self.assertEqual([c.key for c in rugby.competitions], ["top14", "prod2", "six_nations"])
        self.assertEqual([c.mode for c in rugby.competitions], ["club", "club", "international"])
        # Lot 1 : rien n'est encore livré.
        self.assertFalse(rugby.available)
        self.assertFalse(any(c.available for c in rugby.competitions))


class SaisonsTest(unittest.TestCase):
    def test_listes(self):
        self.assertEqual(schema.season_labels("top14"),
                         ["2025-26", "2024-25", "2023-24", "2022-23", "2021-22"])
        self.assertEqual(schema.season_labels("prod2"), ["2025-26", "2024-25", "2023-24", "2022-23"])
        six = schema.season_labels("six_nations")
        self.assertEqual((six[0], six[-1], len(six)), ("2026", "2010", 17))

    def test_competitions_portent_leurs_saisons(self):
        for comp in SPORTS["rugby"].competitions:
            self.assertEqual(comp.seasons, schema.season_labels(comp.key))

    def test_aller_retour(self):
        self.assertEqual(schema.season_label("top14", 202401), "2024-25")
        self.assertEqual(schema.season_id("top14", "2024-25"), 202401)
        self.assertEqual(schema.season_id("six_nations", "2020"), 2020)

    def test_hors_perimetre(self):
        with self.assertRaises(ValueError):
            schema.season_label("top14", 202601)   # saison en cours, hors V1
        with self.assertRaises(ValueError):
            schema.season_label("prod2", 202101)   # Pro D2 à partir de 2022-23
        with self.assertRaises(ValueError):
            schema.season_id("six_nations", "2009")


class CheminsTest(unittest.TestCase):
    def test_caches_dans_data_cache(self):
        path = schema.raw_table_path("top14", "2024-25", "player_match")
        self.assertEqual(path, CACHE_ROOT / "raw" / "rugby" / "top14" / "2024-25" / "player_match.parquet")
        self.assertEqual(schema.processed_path("six_nations", "2026"),
                         CACHE_ROOT / "processed" / "rugby" / "six_nations" / "2026.parquet")

    def test_refus(self):
        with self.assertRaises(ValueError):
            schema.raw_table_path("top14", "2024-25", "inconnue")
        with self.assertRaises(ValueError):
            schema.processed_path("top14", "2026")

    def test_json_hors_du_depot(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RUGBY_JSON_DIR", None)
            # Dossier personnel, ni dans le dépôt ni sur le Bureau (synchronisé avec iCloud).
            self.assertEqual(schema.json_dir(), Path.home() / "rugby_raw_json")
            self.assertFalse(schema.json_dir().resolve().is_relative_to(PROJECT_ROOT.resolve()))
            self.assertFalse(schema.json_dir().resolve().is_relative_to((Path.home() / "Desktop").resolve()))
        with mock.patch.dict(os.environ, {"RUGBY_JSON_DIR": "/tmp/ailleurs"}):
            self.assertEqual(str(schema.json_dir()), "/tmp/ailleurs")


class ColonnesTest(unittest.TestCase):
    def test_pas_de_doublon(self):
        for cols in (schema.MATCH_COLUMNS, schema.LINEUP_COLUMNS, schema.PLAYER_MATCH_COLUMNS,
                     schema.EVENT_COLUMNS, schema.PROFILE_COLUMNS):
            self.assertEqual(len(cols), len(set(cols)))

    def test_touches_nommees_par_leur_sens(self):
        # "lineoutsWon" : sauteur chez InCrowd, lanceur chez ESPN (lot 0).
        for col in ("lineouts_won_jumper", "lineout_throws", "lineout_throws_won"):
            self.assertIn(col, schema.PLAYER_MATCH_STAT_COLUMNS)
        self.assertNotIn("lineouts_won", schema.PLAYER_MATCH_STAT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
