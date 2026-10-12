"""Reconstruction des minutes depuis les événements (data_sources/rugby/minutes.py), cas du plan
(6.1) plus la prolongation et le rouge de 20 minutes. Temps en minutes dans les tests (x 60).

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import math
import unittest

import pandas as pd

from data_sources.rugby.minutes import (
    player_minutes, reconstruct_minutes, t80_seconds, team_minutes_check,
)

END = 4800.0


def ev(*pairs):
    return [(m * 60.0, typ) for m, typ in pairs]


class T80Test(unittest.TestCase):
    def test_bornes_des_periodes(self):
        self.assertEqual(t80_seconds(1, 600), 600)
        self.assertEqual(t80_seconds(1, 42 * 60), 2400)          # arrêts de jeu 1re mi-temps
        self.assertEqual(t80_seconds(2, 40 * 60), 2400)          # la 2e repart à 40:00
        self.assertEqual(t80_seconds(2, 84 * 60), 4800)
        self.assertEqual(t80_seconds(4, 95 * 60), 5700)          # prolongation
        self.assertTrue(math.isnan(t80_seconds(None, 100)))      # après-match


class PlayerMinutesTest(unittest.TestCase):
    def m(self, starter, events, end=END):
        return player_minutes(starter, events, end)["minutes"]

    def test_titulaire_80(self):
        self.assertEqual(self.m(True, []), 80)

    def test_remplacement_simple(self):
        self.assertEqual(self.m(True, ev((55, "sub_off"))), 55)
        self.assertEqual(self.m(False, ev((55, "sub_on"))), 25)

    def test_retours_multiples(self):
        # Cas Ben Earl : sorti 39', rentré 41', sorti 44', rentré 52', sorti 76'.
        events = ev((39, "sub_off"), (41, "sub_on"), (44, "sub_off"), (52, "sub_on"), (76, "sub_off"))
        self.assertEqual(self.m(True, events), 39 + 3 + 24)

    def test_jaune_milieu_de_mi_temps(self):
        self.assertEqual(self.m(True, ev((20, "yellow"))), 70)

    def test_jaune_a_75(self):
        self.assertEqual(self.m(True, ev((75, "yellow"))), 75)

    def test_jaune_dans_les_arrets_de_jeu(self):
        # Jaune à 42' de la 1re mi-temps : ramené à 40', exclusion 40'-50'.
        self.assertEqual(self.m(True, [(t80_seconds(1, 42 * 60), "yellow")]), 70)

    def test_rouge(self):
        self.assertEqual(self.m(True, ev((30, "red"))), 30)

    def test_jaune_puis_remplace_pendant_l_exclusion(self):
        # Pas de double déduction : sur le terrain 0-20, exclu 20-25 puis remplacé.
        res = player_minutes(True, ev((20, "yellow"), (25, "sub_off")), END)
        self.assertEqual(res["minutes"], 20)
        self.assertEqual(res["team_excluded_s"], 600)   # l'équipe joue 10 min à 14

    def test_rouge_de_20_minutes(self):
        # Rouge à 10', "sortie" notée à 30' quand un remplaçant entre : joueur 10 min,
        # infériorité de l'équipe 20 min.
        res = player_minutes(True, ev((10, "red"), (30, "sub_off")), END)
        self.assertEqual(res["minutes"], 10)
        self.assertEqual(res["team_excluded_s"], 1200)

    def test_rouge_definitif(self):
        self.assertEqual(player_minutes(True, ev((10, "red")), END)["team_excluded_s"], 4200)

    def test_carton_recu_sur_le_banc(self):
        res = player_minutes(False, ev((20, "yellow")), END)
        self.assertEqual((res["minutes"], res["team_excluded_s"]), (0, 0))

    def test_prolongation(self):
        self.assertEqual(self.m(True, [], end=6000.0), 100)
        self.assertEqual(self.m(False, ev((91, "sub_on")), end=6000.0), 9)

    def test_incoherent_nan(self):
        self.assertTrue(math.isnan(self.m(False, ev((30, "sub_on"), (50, "sub_on")))))
        self.assertTrue(math.isnan(self.m(False, ev((30, "sub_off")))))
        self.assertTrue(math.isnan(self.m(True, ev((30, "sub_on")))))


class TeamCheckTest(unittest.TestCase):
    def test_somme_par_equipe(self):
        # Équipe A : 15 titulaires, le n° 1 remplacé à 50' par le n° 16, le n° 10 a un jaune à 20'.
        # Somme attendue : 15 x 80 - 10 = 1 190.
        players = [f"icw:{i}" for i in range(1, 17)]
        lineups = pd.DataFrame({"match_uid": "icw:1", "team_uid": "icw:100", "player_uid": players,
                                "is_starter": [True] * 15 + [False]})
        events = pd.DataFrame({
            "match_uid": "icw:1", "team_uid": "icw:100",
            "player_uid": ["icw:1", "icw:16", "icw:10"], "type": ["sub_off", "sub_on", "yellow"],
            "t80_s": [3000.0, 3000.0, 1200.0]})
        matches = pd.DataFrame({"match_uid": ["icw:1"], "duration_min": [80], "extra_time": [False]})
        rebuilt = reconstruct_minutes(lineups, events, matches)
        minutes = dict(zip(rebuilt["player_uid"], rebuilt["minutes_rebuilt"]))
        self.assertEqual((minutes["icw:1"], minutes["icw:16"], minutes["icw:10"]), (50, 30, 70))
        pm = rebuilt.rename(columns={"minutes_rebuilt": "minutes"})
        check = team_minutes_check(pm, rebuilt, matches).iloc[0]
        self.assertEqual(check["minutes_sum"], 1190)
        self.assertEqual(check["expected_min"], 1190)
        self.assertTrue(check["ok"])

    def test_tolerance_5_minutes(self):
        lineups = pd.DataFrame({"match_uid": "icw:1", "team_uid": "icw:100",
                                "player_uid": [f"icw:{i}" for i in range(1, 16)], "is_starter": True})
        events = pd.DataFrame(columns=["match_uid", "team_uid", "player_uid", "type", "t80_s"])
        matches = pd.DataFrame({"match_uid": ["icw:1"], "duration_min": [80], "extra_time": [False]})
        rebuilt = reconstruct_minutes(lineups, events, matches)
        for gap, ok in ((-5, True), (4, True), (6, False), (-6, False)):
            pm = rebuilt.rename(columns={"minutes_rebuilt": "minutes"})
            pm.loc[0, "minutes"] += gap
            with self.subTest(ecart=gap):
                self.assertEqual(bool(team_minutes_check(pm, rebuilt, matches).iloc[0]["ok"]), ok)

    def test_reference_100_minutes_en_prolongation(self):
        lineups = pd.DataFrame({"match_uid": "icw:1", "team_uid": "icw:100",
                                "player_uid": [f"icw:{i}" for i in range(1, 16)], "is_starter": True})
        events = pd.DataFrame(columns=["match_uid", "team_uid", "player_uid", "type", "t80_s"])
        matches = pd.DataFrame({"match_uid": ["icw:1"], "duration_min": [100], "extra_time": [True]})
        rebuilt = reconstruct_minutes(lineups, events, matches)
        check = team_minutes_check(rebuilt.rename(columns={"minutes_rebuilt": "minutes"}),
                                   rebuilt, matches).iloc[0]
        self.assertEqual((check["minutes_sum"], check["expected_min"]), (1500, 1500))


if __name__ == "__main__":
    unittest.main()
