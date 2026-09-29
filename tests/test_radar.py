"""Calcul des axes du radar de comparaison (nba.compute_radar_scores), en particulier "Protection
du ballon" (TOV% estimé à partir de l'USG%, voir TOV_PCT_ESTIMATE_SCALE) et l'ajustement de
"Tir extérieur"/"Lancers francs" vers la moyenne du poste (voir SHOOTING_PADDING).

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
    base["fg3a_total"] = [200] * n
    base["fg3m_total"] = list(range(60, 60 + n))
    base["fta_total"] = [150] * n
    base["ftm_total"] = list(range(100, 100 + n))
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


def _shooters(ftm, fta, positions=None, games=None) -> pd.DataFrame:
    """Population de lanceurs francs : réussis/tentés donnés, un poste et un nombre de matchs par
    joueur (20 par défaut)."""
    n = len(ftm)
    return _players(
        player=[f"J{i}" for i in range(n)], position_group=positions or ["Extérieur"] * n,
        games_played=games or [20] * n, minutes_per_game=[30.0] * n, usg_pct=[0.20] * n, turnovers_per_game=[1.5] * n,
        **{c: [1.0] * n for c in ("points_per_game", "assists_per_game", "rebounds_per_game", "steals_per_game",
                                   "blocks_per_game", "ts_pct", "pie", "fg3_pct")},
        fg3a_total=[200] * n, fg3m_total=[70] * n,
        ftm_total=ftm, fta_total=fta, ft_pct=[m / a if a else 0.0 for m, a in zip(ftm, fta)],
    )


class AjustementTirTest(unittest.TestCase):
    def test_deux_sur_deux_aux_lancers_francs(self):
        # 18 joueurs à 300/400 (75 %), un joueur à 450/500 (90 %) et un joueur à 2/2 en 4 matchs
        # (0,5 tentative par match : juste au seuil, donc ajusté et non vide).
        ftm, fta = [300] * 18 + [450, 2], [400] * 18 + [500, 2]
        out = nba.compute_radar_scores(_shooters(ftm, fta, games=[20] * 19 + [4]))
        position_pct = sum(ftm) / sum(fta)
        self.assertAlmostEqual(out["ft_pct_adj"].iloc[19], (2 + 156 * position_pct) / (2 + 156))
        self.assertAlmostEqual(out["ft_pct_adj"].iloc[19], position_pct, delta=0.005)
        self.assertEqual(out["ft_pct"].iloc[19], 1.0, "le vrai pourcentage affiché ne doit pas changer")
        self.assertLess(out["radar_lancers_francs_percentile"].iloc[19], 100)
        self.assertGreater(out["radar_lancers_francs_score"].iloc[18], out["radar_lancers_francs_score"].iloc[19])
        self.assertEqual(out["radar_lancers_francs_percentile"].iloc[18], 100)

    def test_moyenne_du_poste_et_non_de_la_ligue(self):
        # Extérieurs à 80 %, intérieurs à 60 % : un 2/2 est ramené vers la moyenne de SON poste.
        pos = ["Extérieur"] * 10 + ["Intérieur"] * 10
        ftm, fta = [320] * 9 + [2] + [240] * 9 + [2], [400] * 9 + [2] + [400] * 9 + [2]
        out = nba.compute_radar_scores(_shooters(ftm, fta, pos, games=[20] * 9 + [4] + [20] * 9 + [4]))
        ext, inte = (320 * 9 + 2) / (400 * 9 + 2), (240 * 9 + 2) / (400 * 9 + 2)
        self.assertAlmostEqual(out["ft_pct_adj"].iloc[9], (2 + 156 * ext) / 158)
        self.assertAlmostEqual(out["ft_pct_adj"].iloc[19], (2 + 156 * inte) / 158)

    def test_moyenne_calculee_sur_le_dataframe_recu(self):
        # Même joueur, deux populations (ex. saison régulière et playoffs) : deux moyennes.
        games = [20] * 19 + [4]
        a = nba.compute_radar_scores(_shooters([300] * 19 + [2], [400] * 19 + [2], games=games))
        b = nba.compute_radar_scores(_shooters([200] * 19 + [2], [400] * 19 + [2], games=games))
        self.assertGreater(a["ft_pct_adj"].iloc[19], b["ft_pct_adj"].iloc[19] + 0.1)

    def test_aucune_tentative_axe_vide(self):
        out = nba.compute_radar_scores(_shooters(list(range(281, 300)) + [0], [400] * 19 + [0]))
        for col in ("ft_pct_adj", "radar_lancers_francs_z", "radar_lancers_francs_score",
                    "radar_lancers_francs_percentile"):
            self.assertTrue(np.isnan(out[col].iloc[19]), col)
        self.assertTrue(out["radar_lancers_francs_score"].iloc[:19].notna().all())


class SeuilVolumeTest(unittest.TestCase):
    """Sous MIN_FG3A_PER_GAME / MIN_FTA_PER_GAME tentatives par match, l'axe est vide (comme sans
    tentative) et le joueur sort de la population de référence de l'axe."""

    def test_seuil_trois_points(self):
        self.assertEqual(nba.MIN_FG3A_PER_GAME, 1.0)
        # J0 : 18 tentatives en 20 matchs (0,9/match), J1 : 20 en 20 (1,0/match).
        out = nba.compute_radar_scores(_players(
            fg3a_total=[18, 20] + [200] * 18, fg3m_total=[6, 7] + list(range(60, 78)),
        ))
        self.assertTrue(np.isnan(out["fg3_pct_adj"].iloc[0]))
        self.assertTrue(np.isnan(out["radar_tir_exterieur_score"].iloc[0]))
        self.assertTrue(np.isnan(out["radar_tir_exterieur_percentile"].iloc[0]))
        self.assertFalse(np.isnan(out["fg3_pct_adj"].iloc[1]))
        self.assertFalse(np.isnan(out["radar_tir_exterieur_score"].iloc[1]))

    def test_seuil_lancers_francs(self):
        self.assertEqual(nba.MIN_FTA_PER_GAME, 0.5)
        # J0 : 8 tentatives en 20 matchs (0,4/match), J1 : 10 en 20 (0,5/match).
        out = nba.compute_radar_scores(_shooters(
            [6, 8] + list(range(281, 299)), [8, 10] + [400] * 18,
        ))
        self.assertTrue(np.isnan(out["ft_pct_adj"].iloc[0]))
        self.assertTrue(np.isnan(out["radar_lancers_francs_score"].iloc[0]))
        self.assertFalse(np.isnan(out["radar_lancers_francs_score"].iloc[1]))

    def test_seuil_sur_les_matchs_de_la_periode(self):
        # 4 lancers francs : sous le seuil en 20 matchs (0,2/match), au-dessus en 4 matchs de
        # playoffs (1/match). Le seuil suit les matchs de la période affichée.
        ftm, fta = [3] + list(range(281, 300)), [4] + [400] * 19
        regular = nba.compute_radar_scores(_shooters(ftm, fta))
        playoffs = nba.compute_radar_scores(_shooters(ftm, fta, games=[4] * 20), period="playoffs")
        self.assertTrue(np.isnan(regular["ft_pct_adj"].iloc[0]))
        self.assertFalse(np.isnan(playoffs["ft_pct_adj"].iloc[0]))

    def test_exclus_de_la_reference(self):
        # Un joueur sous le seuil ne pèse plus sur la moyenne/l'écart-type de l'axe : ajouter un
        # tireur à 0/15 en 20 matchs (0,75/match) aux 19 mêmes joueurs ne change quasiment pas
        # leurs scores (seule la moyenne du poste bouge, de 15 tentatives sur 3 800).
        with_low = _players(fg3a_total=[15] + [200] * 19, fg3m_total=[0] + list(range(61, 80)))
        without = with_low.iloc[1:].reset_index(drop=True)
        a = nba.compute_radar_scores(without)["radar_tir_exterieur_score"]
        b = nba.compute_radar_scores(with_low)["radar_tir_exterieur_score"].iloc[1:].reset_index(drop=True)
        self.assertLess((a - b).abs().max(), 1.0)


class Saison2020_21Test(unittest.TestCase):
    """Cas qui a motivé le seuil : Gobert (0/4) et Simmons (3/10) à 3 points en 2020-21."""

    @classmethod
    def setUpClass(cls):
        df = pd.read_parquet(nba.NBA_PROCESSED_DIR / "2020-21.parquet")
        cls.out = nba.compute_radar_scores(df, period="regular").set_index("player")

    def test_non_tireurs_axe_vide(self):
        for player in ("Rudy Gobert", "Ben Simmons"):
            self.assertTrue(np.isnan(self.out.loc[player, "radar_tir_exterieur_score"]), player)
            self.assertFalse(np.isnan(self.out.loc[player, "radar_lancers_francs_score"]), player)
        self.assertEqual(self.out.loc["Rudy Gobert", "fg3a_total"], 4)

    def test_tireurs_axes_renseignes(self):
        for player in ("Nikola Jokić", "Stephen Curry"):
            self.assertFalse(np.isnan(self.out.loc[player, "radar_tir_exterieur_score"]), player)
            self.assertFalse(np.isnan(self.out.loc[player, "radar_lancers_francs_score"]), player)


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

    def test_tir_ajuste(self):
        ref = self.out[self.out["games_played"] >= nba.MIN_GAMES_FOR_FIT]
        top_ft = ref.nlargest(10, "ft_pct_adj")
        self.assertTrue((top_ft["fta_total"] >= 100).all(), top_ft[["ft_pct", "fta_total"]])
        top_3pt = ref.nlargest(10, "fg3_pct_adj")
        self.assertTrue((top_3pt["fg3a_total"] >= 100).all(), top_3pt[["fg3_pct", "fg3a_total"]])
        # Matt Ryan : 2/2 aux lancers francs sur toute sa saison, sous 0,5 tentative par match :
        # axe vide plutôt qu'au sommet (100 %) ou ramené à la moyenne du poste.
        self.assertEqual(self.out.loc["Matt Ryan", "fta_total"], 2)
        self.assertTrue(np.isnan(self.centile_axe("Matt Ryan", "lancers_francs")))

    def test_bon_tireur_peu_de_fautes_garde_son_axe_lf(self):
        # Tyus Jones : 51/57 aux lancers francs, 0,70 tentative par match (au-dessus de 0,5).
        self.assertFalse(np.isnan(self.out.loc["Tyus Jones", "radar_lancers_francs_score"]))

    def centile_axe(self, player, key):
        return self.out.loc[player, f"radar_{key}_percentile"]

    def test_valeurs_realistes(self):
        ref = self.out[self.out["games_played"] >= nba.MIN_GAMES_FOR_FIT]
        self.assertTrue(ref["tov_pct_est"].notna().all())
        self.assertTrue(ref["tov_pct_est"].between(0, 40).all())
        self.assertAlmostEqual(self.out.loc["Shai Gilgeous-Alexander", "tov_pct_est"], 8.6, delta=0.5)


if __name__ == "__main__":
    unittest.main()
