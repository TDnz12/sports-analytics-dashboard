"""Extraction InCrowd (data_sources/rugby/incrowd.py) : JSON de détail de match -> 5 tables brutes.

Un vrai match réduit aux clés utilisées (tests/fixtures/rugby/incrowd_288492.json.gz,
Clermont-Toulouse, Top 14 2025-26, journée 1) et des variantes modifiées en mémoire. Aucun accès
réseau ; seule la lecture de saison passe par un dossier temporaire.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_sources.rugby import incrowd, schema

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rugby" / "incrowd_288492.json.gz"


def load_fixture() -> dict:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
        return json.load(f)


class ExtractMatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = load_fixture()
        cls.tables = incrowd.extract_match(cls.payload, "top14")

    def test_colonnes_du_schema(self):
        expected = {"matches": schema.MATCH_COLUMNS, "lineups": schema.LINEUP_COLUMNS,
                    "player_match": schema.PLAYER_MATCH_COLUMNS, "events": schema.EVENT_COLUMNS,
                    "team_match": schema.TEAM_MATCH_COLUMNS}
        self.assertEqual(set(self.tables), set(schema.RAW_TABLES))
        for name, cols in expected.items():
            self.assertEqual(list(self.tables[name].columns), cols, name)

    def test_identifiants_prefixes(self):
        for name, df in self.tables.items():
            for col in [c for c in df.columns if c.endswith("_uid")]:
                values = df[col].dropna()
                with self.subTest(table=name, colonne=col):
                    self.assertTrue(len(values))
                    self.assertTrue(values.str.match(r"^icw:\d+$").all())

    def test_match(self):
        m = self.tables["matches"].iloc[0]
        self.assertEqual(m["match_uid"], "icw:288492")
        self.assertEqual(m["season"], "2025-26")
        self.assertEqual(m["phase"], "regular")
        self.assertFalse(m["extra_time"])
        self.assertEqual(m["duration_min"], 80)
        self.assertEqual((m["home_team"], m["home_score"], m["away_team"], m["away_score"]),
                         ("Clermont Auvergne", 24, "Toulouse", 34))

    def test_compositions(self):
        lu = self.tables["lineups"]
        self.assertEqual(len(lu), 46)
        self.assertEqual(lu.groupby("team_uid")["is_starter"].sum().tolist(), [15, 15])
        self.assertTrue((lu["is_starter"] == (lu["jersey"] <= 15)).all())

    def test_minutes_source_et_stats_absentes_nan(self):
        pm = self.tables["player_match"]
        self.assertTrue((pm["minutes_method"] == "source").all())
        self.assertTrue((pm["appeared"] == (pm["minutes"] > 0)).all())
        for col in ("try_assists", "lineout_throws", "lineout_throws_won"):
            self.assertTrue(pm[col].isna().all(), col)
        # Somme des points des joueurs = score (pas d'essai de pénalité sur ce match).
        self.assertEqual(pm.groupby("team_uid")["points"].sum().sort_values().tolist(), [24, 34])

    def test_touches_du_sauteur(self):
        pm = self.tables["player_match"].merge(self.tables["lineups"], on=["match_uid", "player_uid"])
        hookers = pm[pm["jersey"] == 2]["lineouts_won_jumper"]
        jumpers = pm[pm["jersey"].isin([4, 5])]["lineouts_won_jumper"]
        self.assertLess(hookers.sum(), jumpers.sum())

    def test_tentatives_au_but(self):
        pm = self.tables["player_match"]
        total = (pm["conversions_made"] + pm["conversions_missed"] + pm["penalty_goals_made"]
                 + pm["penalty_goals_missed"])
        pd.testing.assert_series_equal(pm["goal_attempts"], total, check_names=False)
        tm = self.tables["team_match"].set_index("team_uid")
        by_team = pm.groupby("team_uid")["goal_attempts"].sum()
        pd.testing.assert_series_equal(by_team.sort_index(), tm["goal_attempts"].sort_index(),
                                       check_names=False)

    def test_evenements_normalises(self):
        ev = self.tables["events"]
        self.assertTrue(set(ev["type"]) <= set(schema.EVENT_TYPES))
        self.assertTrue(ev["t80_s"].dropna().between(0, 4800).all())
        # 2e mi-temps : l'horloge InCrowd repart à 40:00 -> t80 >= 2400.
        self.assertTrue((ev.loc[ev["period"] == 2, "t80_s"] >= 2400).all())


class VariantesTest(unittest.TestCase):
    def setUp(self):
        self.payload = copy.deepcopy(load_fixture())
        self.data = self.payload["data"]

    def test_phase_finale_par_journee(self):
        # Phases finales du Top 14 2021-22 en roundTypeId=1 : seule la journée compte.
        self.data["round"], self.data["roundTypeId"] = 27, 1
        self.assertEqual(incrowd.extract_match(self.payload, "top14")["matches"]["phase"].iloc[0], "final")
        self.data["round"], self.data["roundTypeId"] = 26, 2
        self.assertEqual(incrowd.extract_match(self.payload, "top14")["matches"]["phase"].iloc[0], "regular")

    def test_penalite_manquee_lue_dans_les_evenements(self):
        kicker = self.data["homeTeam"]["players"][0]
        self.data["events"].append({"type": "Missed penalty", "minute": 50, "second": 0,
                                    "period": "Second Half", "playerId": kicker["id"],
                                    "teamId": self.data["homeTeam"]["id"]})
        pm = incrowd.extract_match(self.payload, "top14")["player_match"].set_index("player_uid")
        row = pm.loc[f"icw:{kicker['id']}"]
        self.assertEqual(row["penalty_goals_missed"], 1)
        self.assertEqual(row["goal_attempts"], row["conversions_made"] + row["conversions_missed"]
                         + row["penalty_goals_made"] + 1)

    def test_prolongation(self):
        self.data["homeTeam"]["extraFTScore"] = 30
        self.data["events"].append({"type": "Penalty", "minute": 95, "second": 0,
                                    "period": "Second Half Extra Time",
                                    "playerId": self.data["homeTeam"]["players"][0]["id"],
                                    "teamId": self.data["homeTeam"]["id"]})
        tables = incrowd.extract_match(self.payload, "top14")
        m = tables["matches"].iloc[0]
        self.assertTrue(m["extra_time"])
        self.assertEqual(m["duration_min"], 100)
        self.assertEqual(tables["events"]["t80_s"].max(), 95 * 60)

    def test_stat_absente_reste_nan(self):
        self.data["homeTeam"]["players"][0]["stats"]["tackles"] = None
        pm = incrowd.extract_match(self.payload, "top14")["player_match"]
        self.assertEqual(pm["tackles"].isna().sum(), 1)

    def test_type_evenement_inconnu(self):
        self.data["events"].append({"type": "Nouveau type", "minute": 1, "second": 0,
                                    "period": "First Half"})
        with self.assertRaises(ValueError):
            incrowd.extract_match(self.payload, "top14")

    def test_mauvaise_competition(self):
        with self.assertRaises(ValueError):
            incrowd.extract_match(self.payload, "prod2")


class ChoixDesMinutesTest(unittest.TestCase):
    """Source gardée si sa somme par équipe est dans la tolérance (5 min) ; sinon minutes
    reconstruites si la reconstruction y rentre ; les deux hors tolérance : source gardée."""

    def setUp(self):
        self.payload = copy.deepcopy(load_fixture())
        self.data = self.payload["data"]
        self.home = self.data["homeTeam"]

    def _apply(self):
        tables = incrowd.extract_match(self.payload, "top14")
        pm = incrowd.use_rebuilt_minutes_where_better(tables)["player_match"]
        home_uid = f"icw:{self.home['id']}"
        return pm[pm["team_uid"] == home_uid], pm[pm["team_uid"] != home_uid]

    def test_source_juste_gardee(self):
        home, away = self._apply()
        self.assertTrue((home["minutes_method"] == "source").all())
        self.assertTrue((away["minutes_method"] == "source").all())

    def test_source_fausse_reconstruction_juste(self):
        # Minutes source gonflées de 30 min pour un remplaçant (cas Valence-Romans 2025-26).
        sub = next(p for p in self.home["players"] if p["positionId"] == 20)
        before = sub["stats"]["minutesPlayedTotal"]
        sub["stats"]["minutesPlayedTotal"] = before + 30
        home, away = self._apply()
        self.assertTrue((home["minutes_method"] == "reconstruit").all())
        self.assertTrue((away["minutes_method"] == "source").all())   # l'autre équipe ne change pas
        self.assertAlmostEqual(home.set_index("player_uid").loc[f"icw:{sub['id']}", "minutes"],
                               before, delta=1)

    def test_les_deux_hors_tolerance_source_gardee(self):
        # Source gonflée ET reconstruction faussée : on retire la sortie d'un titulaire remplacé
        # tôt, la reconstruction le laisse alors sur le terrain jusqu'à la fin.
        home_id = self.home["id"]
        early = next(e for e in self.data["events"] if e["type"] == "Sub Off"
                     and e.get("teamId") == home_id and e["minute"] < 60)
        self.data["events"].remove(early)
        self.home["players"][0]["stats"]["minutesPlayedTotal"] += 30
        home, _ = self._apply()
        self.assertTrue((home["minutes_method"] == "source").all())


class RecomptageDuScoreTest(unittest.TestCase):
    """Score perdu par la source (cas Pro D2 2023-24) : essais, buts et points recomptés depuis les
    événements, seulement si le recomptage redonne exactement le score officiel."""

    def setUp(self):
        self.payload = copy.deepcopy(load_fixture())
        self.data = self.payload["data"]
        self.home = self.data["homeTeam"]
        self.scorer = next(p for p in self.home["players"] if p["stats"]["tries"])
        self.home_uid = f"icw:{self.home['id']}"

    def _apply(self):
        tables = incrowd.extract_match(self.payload, "top14")
        tables, report = incrowd.rebuild_scoring_from_events(tables)
        return tables["player_match"].set_index("player_uid"), report

    def _lose_one_try(self):
        stats = self.scorer["stats"]
        stats["tries"] -= 1
        stats["points"] -= 5

    def test_sans_ecart_rien_ne_change(self):
        pm, report = self._apply()
        self.assertTrue(report.empty)
        self.assertTrue((pm["score_source"] == "source").all())

    def test_score_recompte(self):
        original = incrowd.extract_match(load_fixture(), "top14")["player_match"].set_index("player_uid")
        self._lose_one_try()
        pm, report = self._apply()
        self.assertEqual(report["applied"].tolist(), [True])
        home = pm[pm["team_uid"] == self.home_uid]
        self.assertTrue((home["score_source"] == "evenements").all())
        self.assertTrue((pm[pm["team_uid"] != self.home_uid]["score_source"] == "source").all())
        self.assertEqual(home["points"].sum(), self.home["score"])
        uid = f"icw:{self.scorer['id']}"
        for col in ("tries", "points", "conversions_made", "penalty_goals_made", "goal_attempts"):
            self.assertEqual(pm.loc[uid, col], original.loc[uid, col], col)
        # Les autres stats ne bougent pas.
        for col in ("tackles", "metres", "carries", "minutes"):
            self.assertTrue((home[col] == original.loc[home.index, col]).all(), col)

    def test_recomptage_faux_source_gardee(self):
        self._lose_one_try()
        # L'événement de l'essai manque aussi : le recomptage ne redonne pas le score.
        event = next(e for e in self.data["events"]
                     if e["type"] == "Try" and e.get("playerId") == self.scorer["id"])
        self.data["events"].remove(event)
        pm, report = self._apply()
        self.assertEqual(report["applied"].tolist(), [False])
        self.assertTrue((pm["score_source"] == "source").all())
        self.assertEqual(pm.loc[f"icw:{self.scorer['id']}", "tries"], self.scorer["stats"]["tries"])


class ExtractSeasonTest(unittest.TestCase):
    def _write(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_saison_et_detail_manquant(self):
        payload = load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            folder = incrowd.season_dir("top14", 202501, Path(tmp))
            listing = {"data": [{"id": 288492, "status": "result"},
                                {"id": 999, "status": "postponed"}]}
            self._write(folder / "list.json.gz", listing)
            self._write(folder / "288492.json.gz", payload)
            tables = incrowd.extract_season("top14", 202501, Path(tmp))
            self.assertEqual(len(tables["matches"]), 1)   # le match reporté est ignoré
            self.assertEqual(len(tables["lineups"]), 46)

            listing["data"].append({"id": 288493, "status": "result"})
            self._write(folder / "list.json.gz", listing)
            with self.assertRaisesRegex(ValueError, "288493"):
                incrowd.extract_season("top14", 202501, Path(tmp))

    def test_prolongation_minutes_reconstruites(self):
        # Prolongation : minutesPlayedTotal est faux à la source (finale 2024-25) -> minutes
        # reconstruites. Un titulaire sans aucun événement joue alors 100 min, pas 80.
        payload = load_fixture()
        data = payload["data"]
        data["homeTeam"]["extraFTScore"] = 30
        with_events = {e.get("playerId") for e in data["events"]}
        starter = next(p for p in data["homeTeam"]["players"]
                       if p["positionId"] <= 15 and p["id"] not in with_events)
        with tempfile.TemporaryDirectory() as tmp:
            folder = incrowd.season_dir("top14", 202501, Path(tmp))
            self._write(folder / "list.json.gz", {"data": [{"id": 288492, "status": "result"}]})
            self._write(folder / "288492.json.gz", payload)
            pm = incrowd.extract_season("top14", 202501, Path(tmp))["player_match"]
        self.assertTrue(pm["minutes_method"].isin(["reconstruit", "echec"]).all())
        self.assertEqual(pm.set_index("player_uid").loc[f"icw:{starter['id']}", "minutes"], 100)
        self.assertTrue((pm.loc[pm["minutes"].notna(), "appeared"]
                         == (pm.loc[pm["minutes"].notna(), "minutes"] > 0)).all())

    def test_sans_prolongation_minutes_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = incrowd.season_dir("top14", 202501, Path(tmp))
            self._write(folder / "list.json.gz", {"data": [{"id": 288492, "status": "result"}]})
            self._write(folder / "288492.json.gz", load_fixture())
            pm = incrowd.extract_season("top14", 202501, Path(tmp))["player_match"]
        self.assertTrue((pm["minutes_method"] == "source").all())

    def test_liste_absente(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                incrowd.extract_season("top14", 202501, Path(tmp))


if __name__ == "__main__":
    unittest.main()
