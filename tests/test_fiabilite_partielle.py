"""Fiabilité partielle : get_player_stats ne doit jamais écrire dans le cache traité une
reliability_pct calculée sur un nombre de saisons incomplet (bug constaté sur 2022-23 : 2
saisons sur 3 après une erreur réseau, persisté tel quel dans data_cache/processed).

Aucun accès disque ni réseau : lectures de cache, écritures de cache et appels nba_api sont
tous remplacés par des doublures.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest
from unittest import mock

import pandas as pd

from data_sources import nba

SEASON = "2022-23"  # fenêtre de fiabilité : 2022-23, 2021-22, 2020-21
MISSING_SEASON = "2020-21"


def _fake_stats(season, force_refresh=False):
    if season == MISSING_SEASON:
        raise ConnectionError("timeout simulé")
    return pd.DataFrame({"player_id": [1, 2], "games_played": [60, 41]})


def _fake_stats_all_ok(season, force_refresh=False):
    return pd.DataFrame({"player_id": [1, 2], "games_played": [60, 41]})


def _fake_enrich(stats, season, force_refresh):
    return stats.assign(salary=[10_000_000.0, 5_000_000.0])


class FiabilitePartielleTest(unittest.TestCase):
    def _run(self, fetch_stats):
        written = []
        with mock.patch.object(nba, "read_cache", return_value=None), \
             mock.patch.object(nba, "write_cache", side_effect=lambda df, path, **k: written.append((path, df))), \
             mock.patch.object(nba, "_fetch_nba_api_stats", side_effect=fetch_stats), \
             mock.patch.object(nba, "_fetch_team_games_possible", return_value=82), \
             mock.patch.object(nba, "_with_final_game_team", side_effect=lambda stats, s, f: (stats, True)), \
             mock.patch.object(nba, "_enrich_stats", side_effect=_fake_enrich):
            result = nba.get_player_stats(SEASON)
        processed = [df for path, df in written if "processed" in str(path)]
        reliability = [df for path, df in written if "reliability_" in str(path)]
        return result, processed, reliability

    def test_saison_manquante_rien_de_partiel_enregistre(self):
        result, processed, reliability = self._run(_fake_stats)
        self.assertEqual(processed, [], "cache traité écrit malgré une fiabilité incomplète")
        self.assertEqual(reliability, [], "cache brut de fiabilité écrit malgré un résultat partiel")
        # Valeur laissée manquante plutôt qu'une valeur fausse calculée sur 2 saisons sur 3.
        self.assertTrue(result["reliability_pct"].isna().all())

    def test_fiabilite_en_erreur_cache_traite_non_ecrit(self):
        with mock.patch.object(nba, "_fetch_reliability", side_effect=RuntimeError("échec simulé")):
            result, processed, _ = self._run(_fake_stats_all_ok)
        self.assertEqual(processed, [])
        self.assertTrue(result["reliability_pct"].isna().all())

    def test_temoin_saisons_completes_cache_ecrit(self):
        # Témoin : sans saison manquante, tout est bien enregistré (prouve que les doublures
        # ci-dessus ne court-circuitent pas l'écriture pour une autre raison).
        result, processed, reliability = self._run(_fake_stats_all_ok)
        self.assertEqual(len(processed), 1)
        self.assertEqual(len(reliability), 1)
        expected = {1: 180 / 246, 2: 123 / 246}
        for pid, value in expected.items():
            self.assertAlmostEqual(processed[0].set_index("player_id").loc[pid, "reliability_pct"], value)


if __name__ == "__main__":
    unittest.main()
