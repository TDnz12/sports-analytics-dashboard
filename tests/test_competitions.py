"""Registre des sports et compétitions (data_sources/__init__.py, data_sources/rugby/schema.py) :
la NBA reste sans compétition (comportement inchangé), le rugby déclare Top 14, Pro D2 et
Six Nations avec leurs saisons, et les chemins de cache restent dans data_cache/ (les JSON bruts,
eux, hors du dépôt).

Aucun accès réseau ni disque.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import dataclasses
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
        # Lot 4 : Top 14 et Pro D2 livrés, Six Nations au lot 8.
        self.assertTrue(rugby.available)
        self.assertEqual({c.key: c.available for c in rugby.competitions},
                         {"top14": True, "prod2": True, "six_nations": False})
        self.assertIsNotNone(rugby.get_player_stats)
        # Radar branché au lot 6 ; pas encore de classement des équipes (après la V1).
        self.assertIsNotNone(rugby.compute_radar_scores)
        self.assertEqual(rugby.player_key_col, "player_uid")
        self.assertIsNone(rugby.get_team_ranking)

    def test_reglages_dashboard_nba_explicites(self):
        nba = SPORTS["nba"]
        self.assertEqual((nba.default_season, nba.default_x, nba.default_y, nba.default_color),
                         ("2024-25", "salary_musd", "points_per_game", "pie"))
        # Champs propres au rugby : vides pour la NBA, donc rendu historique.
        for field in ("stats_periods", "show_low_sample_default", "player_label_col",
                      "categorical_colors", "position_filter_col", "detail_lead_columns",
                      "low_sample_label", "source_caption", "player_key_col", "radar_axes_for",
                      "radar_notes_fn", "radar_card_lines", "radar_extra_columns",
                      "radar_extra_help", "radar_reference_caption"):
            self.assertIsNone(getattr(nba, field), field)

    def test_defauts_rugby_dans_le_catalogue(self):
        rugby = SPORTS["rugby"]
        for key in (rugby.default_x, rugby.default_y):
            self.assertIn(key, rugby.metrics)
        self.assertIn(rugby.default_color, rugby.categorical_colors)
        self.assertEqual(list(rugby.stats_periods.values()), ["all", "regular"])


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
        self.assertEqual(schema.processed_path("top14", "2024-25", "regular"),
                         CACHE_ROOT / "processed" / "rugby" / "top14" / "2024-25_regular.parquet")

    def test_racine_d_essai(self):
        root = Path("/tmp/essai")
        self.assertEqual(schema.raw_table_path("top14", "2024-25", "events", root=root),
                         root / "raw" / "rugby" / "top14" / "2024-25" / "events.parquet")
        self.assertEqual(schema.processed_path("top14", "2024-25", root=root),
                         root / "processed" / "rugby" / "top14" / "2024-25.parquet")

    def test_refus(self):
        with self.assertRaises(ValueError):
            schema.raw_table_path("top14", "2024-25", "inconnue")
        with self.assertRaises(ValueError):
            schema.processed_path("top14", "2026")
        with self.assertRaises(ValueError):
            schema.processed_path("top14", "2024-25", "playoffs")

    def test_fenetres_de_3_saisons(self):
        self.assertEqual(schema.window_seasons("top14", "2025-26"), ["2023-24", "2024-25", "2025-26"])
        self.assertEqual(schema.window_seasons("top14", "2023-24"), ["2021-22", "2022-23", "2023-24"])
        self.assertEqual(schema.window_seasons("prod2", "2024-25"), ["2022-23", "2023-24", "2024-25"])
        available = {comp: [s for s in schema.season_labels(comp) if schema.window_seasons(comp, s)]
                     for comp in schema.COMPETITION_SPECS}
        self.assertEqual(available, {"top14": ["2025-26", "2024-25", "2023-24"],
                                     "prod2": ["2025-26", "2024-25"], "six_nations": []})
        self.assertIsNone(schema.window_seasons("top14", "2019-20"))
        self.assertEqual(schema.window_path("top14", "2025-26"),
                         CACHE_ROOT / "processed" / "rugby" / "top14" / "2025-26_3saisons.parquet")
        self.assertEqual(schema.window_path("prod2", "2024-25", "regular", root=Path("/tmp/essai")),
                         Path("/tmp/essai/processed/rugby/prod2/2024-25_3saisons_regular.parquet"))
        for args in (("top14", "2022-23"), ("prod2", "2023-24"), ("six_nations", "2026"),
                     ("top14", "2025-26", "playoffs")):
            with self.assertRaises(ValueError):
                schema.window_path(*args)

    def test_json_hors_du_depot(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RUGBY_JSON_DIR", None)
            # Dossier personnel, ni dans le dépôt ni sur le Bureau (synchronisé avec iCloud).
            self.assertEqual(schema.json_dir(), Path.home() / "rugby_raw_json")
            self.assertFalse(schema.json_dir().resolve().is_relative_to(PROJECT_ROOT.resolve()))
            self.assertFalse(schema.json_dir().resolve().is_relative_to((Path.home() / "Desktop").resolve()))
        with mock.patch.dict(os.environ, {"RUGBY_JSON_DIR": "/tmp/ailleurs"}):
            self.assertEqual(str(schema.json_dir()), "/tmp/ailleurs")


def _top14_espn_published():
    """Top 14 avec ses saisons ESPN publiées (état visé au lot 5 du plan ESPN)."""
    spec = schema.COMPETITION_SPECS["top14"]
    seasons = tuple(dataclasses.replace(s, published=True) for s in spec.seasons)
    return mock.patch.dict(schema.COMPETITION_SPECS,
                           {"top14": dataclasses.replace(spec, seasons=seasons)})


class SourceParSaisonTest(unittest.TestCase):
    """« Une saison = une source » (rugby_notes/plan_espn.md, lot 1)."""

    def test_top14_espn_declare_mais_non_publie(self):
        self.assertEqual(schema.season_labels("top14", published_only=False),
                         ["2025-26", "2024-25", "2023-24", "2022-23", "2021-22",
                          "2020-21", "2018-19", "2017-18", "2016-17"])
        for label, espn_id in (("2020-21", 2021), ("2018-19", 2019), ("2017-18", 2018),
                               ("2016-17", 2017)):
            s = schema.season_source("top14", label)
            self.assertEqual((s.source, s.native_comp_id, s.season_id, s.published),
                             (schema.SOURCE_ESPN, 270559, espn_id, False))
            self.assertEqual(schema.season_label("top14", espn_id), label)
            self.assertEqual(schema.season_id("top14", label), espn_id)
        self.assertEqual(schema.season_source("top14", "2021-22").source, schema.SOURCE_INCROWD)
        with self.assertRaises(ValueError):
            schema.season_source("top14", "2019-20")   # saison arrêtée, refusée au lot A

    def test_caches_constructibles_avant_publication(self):
        self.assertEqual(schema.raw_table_path("top14", "2018-19", "matches"),
                         CACHE_ROOT / "raw" / "rugby" / "top14" / "2018-19" / "matches.parquet")
        self.assertEqual(schema.processed_path("top14", "2016-17", "regular"),
                         CACHE_ROOT / "processed" / "rugby" / "top14" / "2016-17_regular.parquet")

    def test_sources(self):
        self.assertEqual(schema.source_season_ids("top14", schema.SOURCE_INCROWD),
                         [202501, 202401, 202301, 202201, 202101])
        self.assertEqual(schema.source_season_ids("top14", schema.SOURCE_ESPN), [2021, 2019, 2018, 2017])
        self.assertEqual(schema.source_comp_id("top14", schema.SOURCE_INCROWD), 1002)
        self.assertEqual(schema.source_comp_id("top14", schema.SOURCE_ESPN), 270559)
        self.assertEqual(schema.source_comp_id("prod2", schema.SOURCE_INCROWD), 1013)
        with self.assertRaises(ValueError):
            schema.source_comp_id("prod2", schema.SOURCE_ESPN)
        self.assertEqual(schema.competitions_with_source(schema.SOURCE_INCROWD), ["top14", "prod2"])
        self.assertEqual(schema.competitions_with_source(schema.SOURCE_ESPN), ["top14", "six_nations"])

    def test_profils_de_calibration(self):
        self.assertEqual(schema.calibration_profile("top14", "2024-25"), schema.CLUB_ICW)
        self.assertEqual(schema.calibration_profile("top14"), schema.CLUB_ICW)
        self.assertEqual(schema.calibration_profile("top14", "2018-19"), (schema.CLUB, schema.SOURCE_ESPN))
        self.assertEqual(schema.calibration_profile("prod2"), schema.CLUB_ICW)
        self.assertEqual(schema.calibration_profile("six_nations", "2020"), schema.INTERNATIONAL_ESPN)

    def test_fenetres_une_seule_source_et_annees_consecutives(self):
        with _top14_espn_published():
            self.assertEqual(schema.season_labels("top14")[-4:], ["2020-21", "2018-19", "2017-18", "2016-17"])
            self.assertEqual(schema.window_seasons("top14", "2018-19"), ["2016-17", "2017-18", "2018-19"])
            # 2019-20 absente : la fenêtre de 2020-21 ne saute pas le trou.
            self.assertIsNone(schema.window_seasons("top14", "2020-21"))
            self.assertIsNone(schema.window_seasons("top14", "2021-22"))
            # À cheval sur ESPN (2020-21) et InCrowd.
            self.assertIsNone(schema.window_seasons("top14", "2022-23"))
            self.assertEqual(schema.window_seasons("top14", "2023-24"), ["2021-22", "2022-23", "2023-24"])
            available = [s for s in schema.season_labels("top14") if schema.window_seasons("top14", s)]
            self.assertEqual(available, ["2025-26", "2024-25", "2023-24", "2018-19"])

    def test_raisons_des_fenetres_indisponibles(self):
        from data_sources.rugby import radar
        with _top14_espn_published():
            self.assertEqual(radar.window_status("top14", "2018-19"), ("2016-17 à 2018-19", None))
            for season in ("2020-21", "2021-22"):
                self.assertEqual(radar.window_status("top14", season)[1],
                                 f"Mode 3 saisons indisponible pour {season} : la saison 2019-20 "
                                 "n'est pas couverte par les données Top 14.")
            self.assertEqual(radar.window_status("top14", "2022-23")[1],
                             "Mode 3 saisons indisponible pour 2022-23 : les saisons 2020-21 à "
                             "2022-23 viennent de deux sources différentes (ESPN, puis InCrowd), "
                             "qui ne comptent pas les stats de la même façon.")
            self.assertTrue(radar.window_status("top14", "2017-18")[1].endswith(
                "et les données Top 14 commencent en 2016-17."))
        # Saisons ESPN non publiées : messages d'aujourd'hui inchangés.
        self.assertTrue(radar.window_status("top14", "2022-23")[1].endswith(
            "et les données Top 14 commencent en 2021-22."))


class ColonnesTest(unittest.TestCase):
    def test_pas_de_doublon(self):
        for cols in (schema.MATCH_COLUMNS, schema.LINEUP_COLUMNS, schema.PLAYER_MATCH_COLUMNS,
                     schema.EVENT_COLUMNS, schema.TEAM_MATCH_COLUMNS, schema.PROFILE_COLUMNS):
            self.assertEqual(len(cols), len(set(cols)))

    def test_touches_nommees_par_leur_sens(self):
        # "lineoutsWon" : sauteur chez InCrowd, lanceur chez ESPN (lot 0).
        for col in ("lineouts_won_jumper", "lineout_throws", "lineout_throws_won"):
            self.assertIn(col, schema.PLAYER_MATCH_STAT_COLUMNS)
        self.assertNotIn("lineouts_won", schema.PLAYER_MATCH_STAT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
