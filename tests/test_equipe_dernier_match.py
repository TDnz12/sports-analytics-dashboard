"""Équipe de get_player_stats = équipe du DERNIER match de saison régulière (game log), pas la
dernière équipe d'inscription renvoyée par la NBA (ex: Desmond Bane, ORL au lieu de MEM en
2024-25). Voir nba._with_final_game_team.

Aucun accès disque ni réseau : lectures de cache, écritures de cache et appels nba_api sont
tous remplacés par des doublures.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest
from unittest import mock

import pandas as pd

from data_sources import nba

SEASON = "2024-25"


def _fake_stats(season, force_refresh=False):
    # 1 : échangé après son dernier match (équipe NBA = ORL) ; 2 : transféré en cours de saison,
    # dernier match avec BOS ; 3 : aucun match dans le log.
    return pd.DataFrame({"player_id": [1, 2, 3], "team": ["ORL", "BOS", "LAL"], "games_played": [69, 40, 0]})


def _fake_game_log(season, force_refresh=False):
    return pd.DataFrame({
        "player_id": [1, 1, 2, 2],
        "team": ["MEM", "MEM", "ATL", "BOS"],
        "game_date": ["2024-10-23", "2025-04-13", "2024-10-24", "2025-03-01"],
    })


def _fake_enrich(stats, season, force_refresh):
    return stats.assign(salary=[1.0, 2.0, 3.0])


class EquipeDernierMatchTest(unittest.TestCase):
    def _run(self, game_log):
        written = []
        with mock.patch.object(nba, "read_cache", return_value=None), \
             mock.patch.object(nba, "write_cache", side_effect=lambda df, path, **k: written.append((path, df))), \
             mock.patch.object(nba, "_fetch_nba_api_stats", side_effect=_fake_stats), \
             mock.patch.object(nba, "_fetch_player_game_log", side_effect=game_log), \
             mock.patch.object(nba, "_fetch_reliability", return_value=(pd.DataFrame({"player_id": [1, 2, 3], "reliability_pct": [1.0, 0.5, 0.0]}), True)), \
             mock.patch.object(nba, "_enrich_stats", side_effect=_fake_enrich):
            result = nba.get_player_stats(SEASON)
        processed = [df for path, df in written if "processed" in str(path)]
        return result, processed

    def test_equipe_du_dernier_match(self):
        result, processed = self._run(_fake_game_log)
        self.assertEqual(result.set_index("player_id")["team"].to_dict(), {1: "MEM", 2: "BOS", 3: "LAL"})
        self.assertEqual(len(processed), 1)

    def test_game_log_indisponible_cache_traite_non_ecrit(self):
        def failing(season, force_refresh=False):
            raise ConnectionError("timeout simulé")
        result, processed = self._run(failing)
        # Valeurs NBA gardées telles quelles, et rien d'écrit : recalcul au prochain chargement.
        self.assertEqual(result["team"].tolist(), ["ORL", "BOS", "LAL"])
        self.assertEqual(processed, [])


if __name__ == "__main__":
    unittest.main()
