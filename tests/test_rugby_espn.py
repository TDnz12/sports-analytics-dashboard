"""Extraction ESPN (data_sources/rugby/espn.py) : summary + plays d'un match -> 5 tables brutes.

Deux vrais matchs réduits aux clés utilisées (tests/fixtures/rugby/espn_<match>.json.gz, summary
et plays dans un seul fichier) :
- 293052, Montpellier-La Rochelle, Top 14 2018-19 : jaune de Gourdon, remplacements temporaires ;
- 290386, Grenoble-Castres, Top 14 2016-17 : essai de pénalité à 5 points, 3 drops réussis et un
  manqué (Mélé).
Aucun accès réseau ; la lecture de saison passe par un dossier temporaire.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources.rugby import espn, incrowd, schema

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rugby"
MONTPELLIER, GRENOBLE = "293052", "290386"


def load_fixture(match: str) -> dict:
    with gzip.open(FIXTURES / f"espn_{match}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def extract(match: str) -> dict[str, pd.DataFrame]:
    d = load_fixture(match)
    return espn.extract_match(d["summary"], d["plays"], "top14")


def write_season(root: Path, season_id: int, matches: dict[str, dict], listed: list[str]) -> None:
    """Dossier ESPN d'une saison : events.json.gz (matchs `listed`), sum/ et plays/."""
    folder = root / "espn" / "270559" / str(season_id)
    for sub in ("sum", "plays"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    items = [{"$ref": f"http://x/leagues/270559/events/{m}?lang=en"} for m in listed]
    with gzip.open(folder / "events.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"items": items}, f)
    for match, d in matches.items():
        for key, sub in (("summary", "sum"), ("plays", "plays")):
            with gzip.open(folder / sub / f"{match}.json.gz", "wt", encoding="utf-8") as f:
                json.dump(d[key], f)


def write_exclusions(path: Path, rows: list[tuple]) -> None:
    lines = ["competition,season,match,date,teams,cause"]
    lines += [",".join(map(str, r)) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ExtractMatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = extract(MONTPELLIER)
        cls.grenoble = extract(GRENOBLE)

    def test_colonnes_du_schema(self):
        expected = {"matches": schema.MATCH_COLUMNS, "lineups": schema.LINEUP_COLUMNS,
                    "player_match": schema.PLAYER_MATCH_COLUMNS, "events": schema.EVENT_COLUMNS,
                    "team_match": schema.TEAM_MATCH_COLUMNS}
        for tables in (self.tables, self.grenoble):
            self.assertEqual(set(tables), set(schema.RAW_TABLES))
            for name, cols in expected.items():
                self.assertEqual(list(tables[name].columns), cols, name)

    def test_identifiants_prefixes(self):
        for name, df in self.tables.items():
            for col in [c for c in df.columns if c.endswith("_uid")]:
                values = df[col].dropna()
                with self.subTest(table=name, colonne=col):
                    self.assertTrue(len(values))
                    self.assertTrue(values.str.match(r"^espn:\d+$").all())

    def test_match(self):
        m = self.tables["matches"].iloc[0]
        self.assertEqual((m["match_uid"], m["source"], m["season"], m["season_id"]),
                         ("espn:293052", "espn", "2018-19", 2019))
        self.assertTrue(np.isnan(m["round"]))          # pas de journée chez ESPN
        self.assertIsNone(m["venue"])
        self.assertEqual(m["phase"], "regular")       # provisoire, fixée par assign_phases
        self.assertFalse(m["extra_time"])
        self.assertEqual(m["duration_min"], 80)
        self.assertEqual((m["home_team"], m["home_score"], m["away_team"], m["away_score"]),
                         ("Montpellier Herault", 36, "La Rochelle", 14))

    def test_feuilles_titulaires_par_maillot(self):
        lu = self.tables["lineups"]
        self.assertEqual(lu.groupby("team_uid").size().tolist(), [23, 23])
        self.assertEqual(lu[lu["is_starter"]].groupby("team_uid").size().tolist(), [15, 15])
        self.assertTrue((lu["is_starter"] == (lu["jersey"] <= 15)).all())

    def test_prenom_et_nom(self):
        lu = self.tables["lineups"].set_index("player_name")
        self.assertEqual(tuple(lu.loc["Ruan Pienaar", ["first_name", "last_name"]]),
                         ("Ruan", "Pienaar"))

    def test_stat_absente_nan_jamais_zero(self):
        pm = self.tables["player_match"]
        for col in ("carries_gain_line", "turnovers_won", "kick_metres", "lineouts_won_jumper",
                    "lineout_steals", "conversions_missed", "penalty_goals_missed"):
            with self.subTest(colonne=col):
                self.assertTrue(pm[col].isna().all())
        for col in ("tackles", "carries", "metres", "passes", "lineout_throws_won"):
            with self.subTest(colonne=col):
                self.assertTrue(pm[col].notna().all())
                self.assertTrue((pm[col] == 0).any())
        self.assertTrue(self.tables["team_match"]["turnovers_won"].isna().all())

    def test_lanceur_en_touche(self):
        """lineoutsWon compte le lanceur chez ESPN : lineout_throws_won, pas lineouts_won_jumper."""
        pm = self.tables["player_match"]
        throws = pm.groupby("team_uid")[["lineout_throws", "lineout_throws_won"]].sum()
        tm = self.tables["team_match"].set_index("team_uid")
        self.assertEqual(throws["lineout_throws"].to_dict(), tm["total_lineouts"].to_dict())

    def test_tentatives_au_but(self):
        pm = self.tables["player_match"].merge(self.tables["lineups"], on=["match_uid", "player_uid"])
        kickers = pm[pm["goal_attempts"] > 0].set_index("player_name")["goal_attempts"].to_dict()
        self.assertEqual(kickers, {"Francois Steyn": 2.0, "Ruan Pienaar": 6.0, "Romaric Camou": 3.0,
                                   "Ryan Lamb": 1.0})
        tm = self.tables["team_match"].set_index("team")["goal_attempts"].to_dict()
        self.assertEqual(tm, {"Montpellier Herault": 8.0, "La Rochelle": 4.0})

    def test_drops_dans_le_pourcentage(self):
        """Mélé : 4 pénalités, 3 drops réussis (et un manqué) ; les drops réussis comptent dans
        kickPercentSuccess, retirés des tentatives au but."""
        g = self.grenoble
        pm = g["player_match"].merge(g["lineups"], on=["match_uid", "player_uid"]).set_index("player_name")
        self.assertEqual(tuple(pm.loc["David Mélé", ["penalty_goals_made", "drop_goals_made",
                                                     "goal_attempts"]]), (4.0, 3.0, 5.0))
        tm = g["team_match"].set_index("team")
        self.assertEqual(tuple(tm.loc["Grenoble", ["drop_goals_made", "drop_goals_missed"]]),
                         (3.0, 1.0))

    def test_evenements(self):
        ev = self.grenoble["events"]
        self.assertTrue(set(ev["type"]) <= set(schema.EVENT_TYPES))
        self.assertEqual(ev["type"].value_counts()[["penalty_try", "drop_goal", "drop_missed"]].tolist(),
                         [1, 3, 1])
        timed = ev[ev["type"].isin(["sub_on", "sub_off", "yellow"])]
        self.assertTrue(timed["player_uid"].notna().all())
        self.assertTrue(timed["t80_s"].between(0, 4800).all())

    def test_type_inconnu(self):
        d = load_fixture(MONTPELLIER)
        bad = copy.deepcopy(d["plays"])
        bad["items"][3]["type"]["text"] = "Scrum"
        with self.assertRaisesRegex(ValueError, "type de play inconnu"):
            espn.extract_match(d["summary"], bad, "top14")

    def test_mauvaise_league(self):
        d = load_fixture(MONTPELLIER)
        bad = copy.deepcopy(d["summary"])
        bad["header"]["league"]["slug"] = "180659"
        with self.assertRaisesRegex(ValueError, "league"):
            espn.extract_match(bad, d["plays"], "top14")


class TentativesTest(unittest.TestCase):
    def test_goal_attempts_from_pct(self):
        f = espn.goal_attempts_from_pct
        self.assertEqual(f(5, 0, 0.62), 8)        # 5/8 = 0,625 arrondi à 0,62
        self.assertEqual(f(1, 0, 0.17), 6)
        self.assertEqual(f(3, 1, 0.8), 4)         # drop compris : 4/5, moins le drop
        self.assertEqual(f(0, 1, 0.0), 0)         # drop hors pourcentage (2022-23)
        self.assertEqual(f(0, 0, 0.0), 0)         # n'a pas tenté, ou a tout raté (ajout B)
        self.assertTrue(np.isnan(f(0, 0, 0.5)))
        self.assertTrue(np.isnan(f(-1, 0, 1.0)))  # correction d'ESPN
        self.assertTrue(np.isnan(f(2, 0, np.nan)))


class EssaiDePenaliteTest(unittest.TestCase):
    def test_points_selon_l_epoque(self):
        self.assertEqual([schema.penalty_try_points(s) for s in ("2016-17", "2017-18", "2025-26")],
                         [5, 7, 7])
        self.assertEqual([schema.penalty_try_points(s) for s in ("2017", "2018")], [5, 7])

    def test_essai_de_penalite_a_5_points_en_2016_17(self):
        """Castres : 15 points des joueurs + 1 essai de pénalité à 5 = 20 (transformation au
        buteur)."""
        gaps = incrowd.score_gaps(extract(GRENOBLE)).set_index("team_uid")
        self.assertEqual(tuple(gaps.loc["espn:25916", ["score", "player_points", "penalty_tries",
                                                       "penalty_try_points", "gap"]]),
                         (20, 15.0, 1.0, 5, 0.0))
        self.assertTrue((gaps["gap"] == 0).all())

    def test_saisons_incrowd_a_7_points(self):
        m = pd.DataFrame({"match_uid": ["icw:1"], "season": ["2021-22"], "home_team_uid": ["icw:10"],
                          "away_team_uid": ["icw:11"], "home_score": [7], "away_score": [0]})
        ev = pd.DataFrame({"match_uid": ["icw:1"], "team_uid": ["icw:10"], "type": ["penalty_try"]})
        pm = pd.DataFrame({"match_uid": ["icw:1", "icw:1"], "team_uid": ["icw:10", "icw:11"],
                           "points": [0.0, 0.0]})
        gaps = incrowd.score_gaps({"matches": m, "events": ev, "player_match": pm})
        self.assertEqual(gaps["gap"].tolist(), [0.0, 0.0])


class PhasesTest(unittest.TestCase):
    def test_phase_finale_quand_les_deux_equipes_ont_fini(self):
        rows = []
        day = pd.Timestamp("2020-01-01", tz="UTC")
        # 4 équipes, 2 matchs de phase régulière chacune, puis un barrage et une finale.
        for i, (h, a) in enumerate([("a", "b"), ("c", "d"), ("a", "c"), ("b", "d"), ("a", "d"),
                                    ("b", "c")]):
            rows.append((f"espn:{i}", day + pd.Timedelta(days=i), f"espn:{h}", f"espn:{a}"))
        headers = pd.DataFrame(rows, columns=["match_uid", "date_utc", "home_team_uid",
                                              "away_team_uid"])
        phases = espn.assign_phases(headers, regular_rounds=2)
        self.assertEqual([phases[f"espn:{i}"] for i in range(6)],
                         ["regular", "regular", "regular", "regular", "final", "final"])


class ExtractSeasonTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.excl = self.root / "exclusions.csv"
        self.fixture = load_fixture(MONTPELLIER)

    def test_saison_minutes_reconstruites(self):
        write_season(self.root, 2019, {MONTPELLIER: self.fixture}, [MONTPELLIER])
        write_exclusions(self.excl, [])
        t = espn.extract_season("top14", 2019, self.root, self.excl)
        pm = t["player_match"]
        self.assertEqual(set(pm["minutes_method"]), {"reconstruit"})
        self.assertEqual(pm.groupby("team_uid")["minutes"].sum().to_dict(),
                         {"espn:119318": 1180.0, "espn:25918": 1200.0})   # jaune de Gourdon
        names = t["lineups"].set_index("player_uid")["player_name"]
        minutes = pm.set_index("player_uid")["minutes"]
        self.assertEqual(minutes[names[names == "Jannie du Plessis"].index[0]], 67.0)  # sorti et revenu 2 fois
        self.assertEqual(minutes[names[names == "Kevin Gourdon"].index[0]], 45.0)      # jaune puis sorti
        self.assertTrue(pm.loc[pm["minutes"] > 0, "appeared"].all())
        checks = espn.coverage_checks(t)
        self.assertTrue(checks["c3"].all() and checks["c4"].all())

    def test_exclus_retires_et_inutilisable_signale(self):
        no_roster = copy.deepcopy(self.fixture)
        no_roster["summary"]["rosters"] = []
        no_roster["summary"]["header"]["competitions"][0]["id"] = "293999"
        write_season(self.root, 2019, {MONTPELLIER: self.fixture, "293999": no_roster},
                     [MONTPELLIER, "293999"])
        write_exclusions(self.excl, [])
        with self.assertRaisesRegex(ValueError, "293999 : composition absente"):
            espn.extract_season("top14", 2019, self.root, self.excl)
        write_exclusions(self.excl, [("top14", "2018-19", 293999, "2018-09-01", "x - y",
                                      "C1 composition absente")])
        t = espn.extract_season("top14", 2019, self.root, self.excl)
        self.assertEqual(t["matches"]["match_uid"].tolist(), ["espn:293052"])

    def test_matchs_ajoutes_a_la_liste(self):
        """ESPN_EXTRA_EVENTS : demi-finales et finale 2020-21, absentes de events.json.gz."""
        self.assertEqual(espn.ESPN_EXTRA_EVENTS[("top14", 2021)], (593414, 593415, 593416))
        write_season(self.root, 2021, {}, ["593230"])
        self.assertEqual(espn.season_match_ids("top14", 2021, self.root),
                         [593230, 593414, 593415, 593416])

    def test_saison_inconnue(self):
        with self.assertRaisesRegex(ValueError, "n'est pas une saison ESPN"):
            espn.extract_season("top14", 202501, self.root, self.excl)


class ExclusionsTest(unittest.TestCase):
    def test_liste_versionnee_du_lot_a(self):
        counts = {s: len(espn.read_exclusions("top14", s))
                  for s in ("2016-17", "2017-18", "2018-19", "2020-21")}
        self.assertEqual(counts, {"2016-17": 3, "2017-18": 6, "2018-19": 10, "2020-21": 5})
        self.assertEqual(espn.read_exclusions("top14", "2018-19")[293046], "C1 composition absente")


if __name__ == "__main__":
    unittest.main()
