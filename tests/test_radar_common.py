"""Moteur commun du radar (data_sources/radar_common.py) : z-score et centile par poste, padding,
axes inversés ou absents, et noms toujours accessibles depuis nba (déplacement du lot 5)."""

import unittest

import numpy as np
import pandas as pd

from data_sources import nba, radar_common as rc


def _df():
    return pd.DataFrame({
        "position_group": ["A", "A", "A", "B", "B", "B"],
        "v": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
        "made": [10, 30, 0, 5, 5, 0],
        "att": [20, 40, 0, 10, 10, 0],
    })


class TestByPosition(unittest.TestCase):
    def test_zscore_par_poste(self):
        df = _df()
        z = rc._zscore_by_position(df, df, "v", pd.Series(True, index=df.index))
        np.testing.assert_allclose(z.to_numpy(), [-1, 0, 1, -1, 0, 1])

    def test_reference_limitee_au_masque(self):
        df = _df()
        mask = pd.Series([True, True, False, True, True, True])
        z = rc._zscore_by_position(df, df, "v", mask)
        self.assertAlmostEqual(z.iloc[0], (1 - 1.5) / np.std([1, 2], ddof=1))
        self.assertFalse(np.isnan(z.iloc[2]))  # hors référence mais noté quand même

    def test_ecart_type_nul_donne_nan(self):
        df = pd.DataFrame({"position_group": ["A", "A"], "v": [5.0, 5.0]})
        z = rc._zscore_by_position(df, df, "v", pd.Series(True, index=df.index))
        self.assertTrue(z.isna().all())

    def test_centile_par_poste(self):
        df = _df()
        p = rc._percentile_by_position(df, df, "v", pd.Series(True, index=df.index))
        np.testing.assert_allclose(p.to_numpy(), [100 / 3, 200 / 3, 100] * 2)


    def test_centile_rang_moyen_des_ex_aequo(self):
        # Décision C3 de l'audit rugby : 3 valeurs égales sur 5 partagent leur rang moyen (2), les
        # autres gardent le leur ; une valeur absente de la référence n'est pas concernée.
        df = pd.DataFrame({"position_group": ["A"] * 6, "v": [0.0, 0.0, 0.0, 1.0, 2.0, 0.5]})
        mask = pd.Series([True] * 5 + [False])
        p = rc._percentile_by_position(df, df, "v", mask)
        np.testing.assert_allclose(p.to_numpy(), [40, 40, 40, 80, 100, 60])

    def test_centile_ex_aequo_hors_reference(self):
        # Joueur hors référence à égalité avec 3 joueurs de référence : même rang moyen qu'eux.
        df = pd.DataFrame({"position_group": ["A"] * 5, "v": [0.0, 0.0, 0.0, 1.0, 0.0]})
        p = rc._percentile_by_position(df, df, "v", pd.Series([True] * 4 + [False]))
        np.testing.assert_allclose(p.to_numpy(), [50, 50, 50, 100, 50])


class TestPadding(unittest.TestCase):
    def test_moyenne_du_poste(self):
        df = _df()
        out = rc.padded_pct(df, "made", "att", padding=10)
        # Poste A : 40/60 ; joueur 1 : (10 + 10 x 2/3) / 30
        self.assertAlmostEqual(out.iloc[0], (10 + 10 * 40 / 60) / 30)
        self.assertAlmostEqual(out.iloc[2], 40 / 60)  # aucune tentative : moyenne du poste, pas de masque ici
        self.assertAlmostEqual(out.iloc[3], (5 + 10 * 0.5) / 20)


class TestScoreAxes(unittest.TestCase):
    AXES = [
        {"key": "a", "stat_col": "v"},
        {"key": "inv", "stat_col": "v", "invert": True},
        {"key": "adj", "stat_col": "v", "score_col": "absente"},
    ]

    def setUp(self):
        self.df = _df()
        self.out = rc.score_axes(self.df, self.AXES, pd.Series(True, index=self.df.index))

    def test_colonnes_et_echelle(self):
        np.testing.assert_allclose(self.out["radar_a_z"].to_numpy(), [-1, 0, 1, -1, 0, 1])
        np.testing.assert_allclose(self.out["radar_a_score"].to_numpy(), [(z + 3) / 6 * 100 for z in [-1, 0, 1] * 2])

    def test_axe_inverse(self):
        np.testing.assert_allclose(self.out["radar_inv_z"].to_numpy(), -self.out["radar_a_z"].to_numpy())
        self.assertFalse([c for c in self.out.columns if c.startswith("_radar_")])
        pd.testing.assert_series_equal(self.out["v"], _df()["v"])  # vraie valeur conservée

    def test_colonne_absente(self):
        for suffix in ("_z", "_score", "_percentile"):
            self.assertTrue(self.out[f"radar_adj{suffix}"].isna().all())

    def test_centile_vide_quand_le_score_est_vide(self):
        # Décision C2 de l'audit rugby : référence dégénérée (valeurs identiques) -> score ET
        # centile vides, comme l'axe en mode Indice.
        df = pd.DataFrame({"position_group": ["A"] * 3 + ["B"] * 3, "v": [5.0] * 3 + [1.0, 2.0, 3.0]})
        out = rc.score_axes(df, [{"key": "a", "stat_col": "v"}], pd.Series(True, index=df.index))
        self.assertTrue(out.loc[:2, "radar_a_score"].isna().all())
        self.assertTrue(out.loc[:2, "radar_a_percentile"].isna().all())
        np.testing.assert_allclose(out.loc[3:, "radar_a_percentile"].to_numpy(), [100 / 3, 200 / 3, 100])

    def test_score_borne(self):
        df = pd.DataFrame({"position_group": ["A"] * 20, "v": [0.0] * 19 + [1000.0]})
        out = rc.score_axes(df, [{"key": "a", "stat_col": "v"}], pd.Series(True, index=df.index))
        self.assertTrue(out["radar_a_score"].between(0, 100).all())


class TestReexport(unittest.TestCase):
    def test_noms_nba_inchanges(self):
        self.assertIs(nba._zscore_by_position, rc._zscore_by_position)
        self.assertIs(nba._percentile_by_position, rc._percentile_by_position)


if __name__ == "__main__":
    unittest.main()
