"""Mode 3 saisons du radar rugby (chantier E), vérifié sur les vrais caches de data_cache/ :
- non-régression : aggregate_season, relancée sur les tables brutes versionnées, redonne les 18
  caches saison à l'identique (valeurs exactes, vide = vide), après le calcul de la disponibilité
  saison par saison ;
- les 10 caches de fenêtre (Top 14 2023-24 à 2025-26, Pro D2 2024-25 et 2025-26, 2 périodes)
  existent et leurs totaux sont la somme des 3 caches saison, pour tous les joueurs ; une fenêtre
  recalculée par aggregate_window redonne son cache à l'identique.

Environ 30 s (aggregate_season relancée 22 fois).

Lit les caches versionnés, n'écrit rien.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import json
import unittest

import pandas as pd

from data_sources.base import read_cache
from data_sources.rugby import schema
from data_sources.rugby.aggregate import aggregate_season, aggregate_window

CLUB_COMPETITIONS = ("top14", "prod2")
TOTALS = ["games_played", "starts", "matchday_squads", "minutes_total", "tackles",
          "missed_tackles", "metres", "carries", "penalties_conceded", "turnovers_won"]


def raw_tables(competition: str, season: str) -> dict[str, pd.DataFrame]:
    return {t: read_cache(schema.raw_table_path(competition, season, t),
                          schema_version=schema.RUGBY_RAW_TABLES_SCHEMA_VERSION)
            for t in schema.RAW_TABLES}


def processed(competition: str, season: str, period: str) -> pd.DataFrame:
    return read_cache(schema.processed_path(competition, season, period),
                      schema_version=schema.RUGBY_PROCESSED_SCHEMA_VERSION)


def windows():
    """(compétition, saison de fin, libellés de la fenêtre) des fenêtres disponibles."""
    return [(comp, season, schema.window_seasons(comp, season)) for comp in CLUB_COMPETITIONS
            for season in schema.season_labels(comp) if schema.window_seasons(comp, season)]


def differences(fresh: pd.DataFrame, cached: pd.DataFrame) -> dict[str, int]:
    """{colonne : lignes différentes}, égalité exacte, deux vides (None, NaN) égaux. Les colonnes
    et l'ordre des lignes doivent déjà être les mêmes."""
    out = {}
    for col in fresh.columns:
        a, b = fresh[col].reset_index(drop=True), cached[col].reset_index(drop=True)
        differ = ~((a == b) | (a.isna() & b.isna()))
        if differ.any():
            out[col] = int(differ.sum())
    return out


class NonRegressionSaisonTest(unittest.TestCase):
    def test_18_caches_saison_identiques(self):
        n = 0
        for comp in CLUB_COMPETITIONS:
            for season in schema.season_labels(comp):
                tables = raw_tables(comp, season)
                for period in schema.PERIODS:
                    with self.subTest(comp=comp, season=season, period=period):
                        fresh, cached = aggregate_season(tables, comp, period), processed(comp, season, period)
                        self.assertEqual(list(fresh.columns), list(cached.columns))
                        self.assertEqual(list(fresh["player_uid"]), list(cached["player_uid"]))
                        self.assertEqual(differences(fresh, cached), {})
                        n += 1
        self.assertEqual(n, 18)


class FenetresTest(unittest.TestCase):
    def test_10_fenetres(self):
        self.assertEqual([(c, s) for c, s, _ in windows()],
                         [("top14", "2025-26"), ("top14", "2024-25"), ("top14", "2023-24"),
                          ("prod2", "2025-26"), ("prod2", "2024-25")])

    def test_caches_presents(self):
        for comp, season, _ in windows():
            for period in schema.PERIODS:
                with self.subTest(comp=comp, season=season, period=period):
                    self.assertIsNotNone(
                        read_cache(schema.window_path(comp, season, period),
                                   schema_version=schema.RUGBY_WINDOW_SCHEMA_VERSION),
                        "cache absent ou ancien : rugby_build.py --comp ... --windows-only")

    def test_cache_a_jour(self):
        # Une seule fenêtre recalculée (environ 6 s ; les 10 en prendraient 60, la boucle par
        # joueur de positions.assign_positions dominant) : Top 14 2023-24 à 2025-26, saison complète.
        labels = schema.window_seasons("top14", "2025-26")
        fresh = aggregate_window({s: raw_tables("top14", s) for s in labels}, "top14")
        cached = read_cache(schema.window_path("top14", "2025-26"),
                            schema_version=schema.RUGBY_WINDOW_SCHEMA_VERSION)
        self.assertEqual(list(fresh.columns), list(cached.columns))
        self.assertEqual(list(fresh["player_uid"]), list(cached["player_uid"]))
        self.assertEqual(differences(fresh, cached), {})

    def test_totaux_somme_des_saisons(self):
        for comp, season, labels in windows():
            for period in schema.PERIODS:
                with self.subTest(comp=comp, season=season, period=period):
                    w = read_cache(schema.window_path(comp, season, period),
                                   schema_version=schema.RUGBY_WINDOW_SCHEMA_VERSION).set_index("player_uid")
                    per_season = [processed(comp, s, period).set_index("player_uid") for s in labels]
                    self.assertEqual(set(w.index), set().union(*(d.index for d in per_season)))
                    summed = sum(d[TOTALS].reindex(w.index).fillna(0) for d in per_season)
                    gap = (summed - w[TOTALS].astype(float).fillna(0)).abs().max()
                    self.assertEqual(gap.max(), 0, gap[gap > 0].to_dict())
                    self.assertTrue((w["season"] == season).all())
                    self.assertTrue((w["window_label"] == f"{labels[0]} à {labels[-1]}").all())

    def test_detail_par_saison(self):
        for comp, season, labels in windows():
            w = read_cache(schema.window_path(comp, season),
                           schema_version=schema.RUGBY_WINDOW_SCHEMA_VERSION)
            detail = w["season_detail"].map(json.loads)
            with self.subTest(comp=comp, season=season):
                self.assertTrue((detail.map(len) == w["seasons_played"]).all())
                self.assertTrue(detail.map(lambda d: [x[0] for x in d] == sorted(x[0] for x in d)).all())
                games = detail.map(lambda d: sum(x[3] for x in d))
                self.assertTrue((games == w["games_played"]).all())
                minutes = detail.map(lambda d: sum(x[4] for x in d))
                self.assertLessEqual((minutes - w["minutes_total"]).abs().max(), 1.5)   # arrondis
                last = processed(comp, season, "all").set_index("player_uid")["position_group"]
                self.assertTrue((w["season_position_group"].fillna("-")
                                 == w["player_uid"].map(last).fillna("-")).all())


if __name__ == "__main__":
    unittest.main()
