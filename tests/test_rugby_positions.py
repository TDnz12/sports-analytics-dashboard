"""Postes (data_sources/rugby/positions.py) : poste principal, égalités, postes secondaires, repli
banc 16/17/18, 19 à 23 "Indéterminé", familles. Données construites à la main.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest

import pandas as pd

from data_sources.rugby.positions import assign_positions


def build(rows):
    """rows : (match n°, joueur, maillot, minutes). Le match n est joué le jour n."""
    lineups = pd.DataFrame([{"match_uid": f"icw:{m}", "player_uid": p, "jersey": j,
                             "is_starter": j <= 15} for m, p, j, _ in rows])
    pm = pd.DataFrame([{"match_uid": f"icw:{m}", "player_uid": p, "minutes": mins}
                       for m, p, _, mins in rows])
    matches = pd.DataFrame({"match_uid": [f"icw:{m}" for m in sorted({r[0] for r in rows})]})
    matches["date_utc"] = pd.to_datetime("2025-09-01") + pd.to_timedelta(
        matches["match_uid"].str[4:].astype(int), unit="D")
    return assign_positions(lineups, pm, matches).set_index("player_uid")


class PositionsTest(unittest.TestCase):
    def test_poste_principal_et_secondaires(self):
        rows = [(1, "a", 12, 80), (2, "a", 12, 80), (3, "a", 13, 80), (4, "a", 14, 80),
                (5, "a", 20, 10)]
        p = build(rows).loc["a"]
        self.assertEqual(p["position_group"], "Centre")
        self.assertEqual(p["position_family"], "Arrières")
        self.assertEqual(p["position_source"], "titulaire")
        self.assertEqual(p["secondary_positions"], "Ailier 25 %")
        self.assertIn("Centre : 12 (67 %), 13 (33 %)", p["position_detail"])

    def test_pilier_1_et_3_meme_groupe(self):
        p = build([(1, "a", 1, 80), (2, "a", 3, 80)]).loc["a"]
        self.assertEqual(p["position_group"], "Pilier")
        self.assertIsNone(p["secondary_positions"])
        self.assertEqual(p["position_family"], "Avants")

    def test_egalite_minutes_puis_recent(self):
        # 1 titularisation chacun : plus de minutes en 8 -> Troisième ligne centre.
        p = build([(1, "a", 6, 80), (2, "a", 8, 80), (3, "a", 6, 40)])
        self.assertEqual(p.loc["a", "position_group"], "Troisième ligne aile")   # 2 contre 1
        p = build([(1, "b", 6, 50), (2, "b", 8, 70)])
        self.assertEqual(p.loc["b", "position_group"], "Troisième ligne centre")
        p = build([(1, "c", 6, 60), (2, "c", 8, 60)])                            # le plus récent
        self.assertEqual(p.loc["c", "position_group"], "Troisième ligne centre")

    def test_repli_banc_premiere_ligne(self):
        p = build([(1, "h", 16, 20), (2, "h", 16, 25), (3, "h", 20, 10),
                   (1, "p", 17, 20), (2, "p", 18, 20)])
        self.assertEqual(p.loc["h", "position_group"], "Talonneur")
        self.assertEqual(p.loc["h", "position_source"], "banc")
        self.assertEqual(p.loc["p", "position_group"], "Pilier")
        self.assertEqual(p.loc["p", "position_family"], "Avants")

    def test_banc_19_a_23_indetermine(self):
        # Maillot de banc le plus porté : 20 (2 fois) contre 16 (1 fois) -> pas de repli.
        p = build([(1, "x", 20, 20), (2, "x", 20, 20), (3, "x", 16, 30)]).loc["x"]
        self.assertEqual(p["position_group"], "Indéterminé")
        self.assertIsNone(p["position_source"])
        self.assertIsNone(p["position_family"])

    def test_banc_egalite_minutes(self):
        p = build([(1, "x", 16, 30), (2, "x", 21, 10)]).loc["x"]
        self.assertEqual(p["position_group"], "Talonneur")

    def test_un_titulaire_n_est_jamais_en_repli(self):
        p = build([(1, "a", 16, 30), (2, "a", 16, 30), (3, "a", 11, 80)]).loc["a"]
        self.assertEqual((p["position_group"], p["position_source"]), ("Ailier", "titulaire"))


if __name__ == "__main__":
    unittest.main()
