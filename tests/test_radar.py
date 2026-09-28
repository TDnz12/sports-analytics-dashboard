"""Calcul des axes du radar de comparaison (nba.compute_radar_scores), en particulier "Protection
du ballon" (TOV% estimé à partir de l'USG%, voir TOV_PCT_ESTIMATE_SCALE).

Aucun accès réseau : cas construits à la main, plus le cache 2024-25 du dépôt en lecture seule.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest

import numpy as np
import pandas as pd

from data_sources import nba

AXIS = "protection_ballon"


def _players(**cols) -> pd.DataFrame:
    """Petite population de référence : 20 extérieurs à 20 matchs, colonnes de stats neutres,
    surchargées par `cols` (listes de 20 valeurs)."""
    n = 20
    base = {
        "player": [f"J{i}" for i in range(n)], "position_group": ["Extérieur"] * n, "games_played": [20] * n,
        "minutes_per_game": [30.0] * n, "usg_pct": [0.20] * n, "turnovers_per_game": [1.5] * n,
    }
    for col in ("points_per_game", "assists_per_game", "rebounds_per_game", "steals_per_game",
                "blocks_per_game", "ts_pct", "pie", "fg3_pct", "ft_pct"):
        base[col] = list(np.linspace(0.1, 2.0, n))
    base.update(cols)
    return pd.DataFrame(base)


class ProtectionDuBallonTest(unittest.TestCase):
    def test_libelle_et_colonnes(self):
        labels = [a["label"] for a in nba.RADAR_AXES]
        self.assertIn("Protection du ballon", labels)
        self.assertNotIn("Sécurité de balle", labels)
        self.assertTrue(all(a.get("help") for a in nba.RADAR_AXES), "chaque axe doit avoir une infobulle")
        out = nba.compute_radar_scores(_players(turnovers_per_game=list(np.linspace(0.5, 3.0, 20))))
        for a in nba.RADAR_AXES:
            for suffix in ("_z", "_score", "_percentile"):
                self.assertIn(f"radar_{a['key']}{suffix}", out.columns)
                self.assertTrue(out[f"radar_{a['key']}{suffix}"].notna().all(), a["key"])

    def test_estimation_proche_du_tov_pct_exact(self):
        # Joueur fictif : 17 tirs, 6 lancers francs, 3 pertes -> TOV% exact = 3 / (17 + 2,64 + 3).
        # Une équipe termine ~111,6 actions en 48 minutes (ordre de grandeur de 2024-25) : avec
        # 34 minutes jouées, ses 22,64 actions donnent un USG% de 22,64 / (111,6 x 34 / 48).
        exact = 100 * 3 / (17 + 0.44 * 6 + 3)
        usg = 22.64 / (111.6 * 34 / 48)
        out = nba.compute_radar_scores(_players(
            minutes_per_game=[34.0] * 20, usg_pct=[usg] * 20, turnovers_per_game=[3.0] * 20,
        ))
        self.assertAlmostEqual(out["tov_pct_est"].iloc[0], exact, delta=1.0)

    def test_invariant_au_volume(self):
        # J0 joue deux fois plus que J1 et perd deux fois plus de ballons, à usage égal : même
        # proportion de pertes, donc même score (l'ancien axe pénalisait J0).
        # Valeurs exactement représentables : 0,25 x 32 = 8 et 0,25 x 16 = 4, sans arrondi flottant.
        minutes = [32.0, 16.0] + [25.0] * 18
        tov = [2.0, 1.0] + list(np.linspace(0.8, 3.0, 18))
        out = nba.compute_radar_scores(_players(
            minutes_per_game=minutes, turnovers_per_game=tov, usg_pct=[0.25] * 20,
        ))
        self.assertAlmostEqual(out[f"radar_{AXIS}_score"].iloc[0], out[f"radar_{AXIS}_score"].iloc[1])
        self.assertEqual(out[f"radar_{AXIS}_percentile"].iloc[0], out[f"radar_{AXIS}_percentile"].iloc[1])

    def test_moins_de_pertes_meilleur_score(self):
        out = nba.compute_radar_scores(_players(turnovers_per_game=list(np.linspace(0.5, 3.0, 20))))
        scores = out[f"radar_{AXIS}_score"]
        self.assertTrue(scores.is_monotonic_decreasing)

    def test_usage_nul_donne_nan(self):
        usg = [0.0] + [0.20] * 19
        out = nba.compute_radar_scores(_players(usg_pct=usg, turnovers_per_game=[0.5] + list(np.linspace(0.8, 3.0, 19))))
        self.assertTrue(np.isnan(out["tov_pct_est"].iloc[0]))
        self.assertFalse(np.isinf(out["tov_pct_est"]).any())
        for suffix in ("_z", "_score", "_percentile"):
            self.assertTrue(np.isnan(out[f"radar_{AXIS}{suffix}"].iloc[0]))
            self.assertTrue(out[f"radar_{AXIS}{suffix}"].iloc[1:].notna().all())


class Saison2024_25Test(unittest.TestCase):
    """Garde-fou sur les vraies données : les porteurs de balle principaux ne sont plus écrasés."""

    @classmethod
    def setUpClass(cls):
        df = pd.read_parquet(nba.NBA_PROCESSED_DIR / "2024-25.parquet")
        cls.out = nba.compute_radar_scores(df, period="regular").set_index("player")

    def centile(self, player):
        return self.out.loc[player, f"radar_{AXIS}_percentile"]

    def test_porteurs_de_balle(self):
        self.assertGreater(self.centile("Shai Gilgeous-Alexander"), 70)
        self.assertGreater(self.centile("Luka Dončić"), 20)
        self.assertGreater(self.centile("Nikola Jokić"), 20)

    def test_valeurs_realistes(self):
        ref = self.out[self.out["games_played"] >= nba.MIN_GAMES_FOR_FIT]
        self.assertTrue(ref["tov_pct_est"].notna().all())
        self.assertTrue(ref["tov_pct_est"].between(0, 40).all())
        self.assertAlmostEqual(self.out.loc["Shai Gilgeous-Alexander", "tov_pct_est"], 8.6, delta=0.5)


if __name__ == "__main__":
    unittest.main()
