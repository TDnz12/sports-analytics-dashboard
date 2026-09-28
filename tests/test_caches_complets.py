"""Chaque cache lu par l'app existe dans data_cache/ pour les 30 saisons de nba.SEASONS, à la
version de schéma attendue par le code. Streamlit Cloud ne joint pas stats.nba.com : un cache
absent ou d'une ancienne version (montée de *_SCHEMA_VERSION sans relancer
scripts/prefill_cache.py) y coûte ~10-30s d'attente puis une erreur.

Aucun accès réseau : lit seulement les fichiers parquet du dépôt.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest

import pandas as pd

from data_sources import nba
from data_sources.base import SCHEMA_VERSION_COL

RAW = nba.NBA_RAW_DIR / "nba_api"
PROC = nba.NBA_PROCESSED_DIR

# {nom : (chemin pour une saison, version de schéma attendue)}
CACHES = {
    "traité saison régulière": (lambda s: PROC / f"{s}.parquet", nba.PROCESSED_SCHEMA_VERSION),
    "traité playoffs": (lambda s: PROC / f"{s}_playoffs.parquet", nba.PROCESSED_SCHEMA_VERSION),
    "mercato": (lambda s: PROC / f"mercato_{s}.parquet", nba.MERCATO_SCHEMA_VERSION),
    "stats brutes saison régulière": (lambda s: RAW / f"{s}.parquet", nba.NBA_API_STATS_SCHEMA_VERSION),
    "stats brutes playoffs": (lambda s: RAW / f"{s}_playoffs.parquet", nba.NBA_API_STATS_SCHEMA_VERSION),
    "game log": (lambda s: RAW / f"game_log_{s}.parquet", nba.NBA_API_GAME_LOG_SCHEMA_VERSION),
    "postes": (lambda s: RAW / f"positions_{s}.parquet", nba.NBA_API_POSITIONS_SCHEMA_VERSION),
    "fiabilité": (lambda s: RAW / f"reliability_{s}.parquet", nba.NBA_API_RELIABILITY_SCHEMA_VERSION),
    "matchs possibles": (lambda s: RAW / f"team_games_{s}.parquet", nba.NBA_API_TEAM_GAMES_SCHEMA_VERSION),
    "stats équipes saison régulière": (lambda s: RAW / f"team_stats_{s}_regular.parquet", nba.NBA_API_TEAM_STATS_SCHEMA_VERSION),
    "stats équipes playoffs": (lambda s: RAW / f"team_stats_{s}_playoffs.parquet", nba.NBA_API_TEAM_STATS_SCHEMA_VERSION),
}


class CachesCompletsTest(unittest.TestCase):
    def test_30_saisons(self):
        self.assertEqual(len(nba.SEASONS), 30)

    def test_caches_par_saison(self):
        for name, (path_of, version) in CACHES.items():
            for season in nba.SEASONS:
                with self.subTest(cache=name, saison=season):
                    path = path_of(season)
                    self.assertTrue(path.exists(), f"absent : {path.name}")
                    df = pd.read_parquet(path)
                    self.assertGreater(len(df), 0, f"vide : {path.name}")
                    self.assertIn(SCHEMA_VERSION_COL, df.columns, f"sans version : {path.name}")
                    self.assertEqual(df[SCHEMA_VERSION_COL].iloc[0], version, f"version : {path.name}")

    def test_caches_salaires(self):
        # kaggle_raw est lu sans version de schéma (voir nba._load_kaggle_raw) ; legacy l'est.
        self.assertGreater(len(pd.read_parquet(nba.KAGGLE_RAW_CACHE)), 0)
        legacy = pd.read_parquet(nba.LEGACY_KAGGLE_RAW_CACHE)
        self.assertEqual(legacy[SCHEMA_VERSION_COL].iloc[0], nba.LEGACY_KAGGLE_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
