"""scripts/rugby_download.py sur un faux client HTTP : aucun accès réseau, aucune vraie pause.

Vérifie la reprise (rien n'est retéléchargé au second lancement), le remplacement d'un fichier
illisible, les nouvelles tentatives sur 503, le coupe-circuit après 3 échecs consécutifs, le
budget --max-requests et la lecture de --seasons.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import csv
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rugby_download", ROOT / "scripts" / "rugby_download.py")
rd = importlib.util.module_from_spec(_spec)
sys.modules["rugby_download"] = rd   # requis par @dataclass avant l'exécution du module
_spec.loader.exec_module(rd)

SEASON = 202401
LIST_URL = (f"{rd.INCROWD_BASE}/matches?provider=rugbyviz&compId=1002&season={SEASON}"
            f"&size={rd.LIST_SIZE}")


def detail_url(match_id):
    return f"{rd.INCROWD_BASE}/matches/{match_id}?provider=rugbyviz&season={SEASON}"


def match_detail(match_id):
    team = {"players": [{"id": 1, "positionId": 1}]}
    return {"data": {"id": match_id, "status": "result", "homeTeam": team, "awayTeam": team},
            "metadata": {}, "status": "success"}


LIST_PAYLOAD = {
    "data": [{"id": 11, "status": "result", "round": 1, "date": "2024-09-07T12:30:00.000Z"},
             {"id": 12, "status": "result", "round": 1, "date": "2024-09-07T15:00:00.000Z"},
             {"id": 13, "status": "postponed", "round": 2, "date": "2024-09-14T15:00:00.000Z"}],
    "metadata": {"totalPages": 1, "totalItems": 3}, "status": "success",
}


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code, self.payload, self.reason = status_code, payload, "fake"

    def json(self):
        return self.payload


class FakeSession:
    """`routes` : url -> liste de réponses servies dans l'ordre (la dernière est répétée)."""

    def __init__(self, routes):
        self.routes = {url: list(resps) for url, resps in routes.items()}
        self.headers = {}
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        queue = self.routes.get(url, [FakeResponse(404)])
        return queue.pop(0) if len(queue) > 1 else queue[0]


def ok_routes():
    return {LIST_URL: [FakeResponse(200, LIST_PAYLOAD)],
            detail_url(11): [FakeResponse(200, match_detail(11))],
            detail_url(12): [FakeResponse(200, match_detail(12))]}


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"RUGBY_JSON_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.sleeps = []

    def run_season(self, session, **kw):
        client = rd.Client(session=session, sleep=self.sleeps.append,
                           failures_path=Path(self.tmp.name) / "failures.csv",
                           max_requests=kw.pop("max_requests", None))
        report = rd.SeasonReport("top14", SEASON)
        rd.download_season(client, report, force=kw.get("force", False), refresh_lists=False)
        return client, report

    def folder(self):
        return Path(self.tmp.name) / "incrowd" / "1002" / str(SEASON)

    def test_telechargement_puis_reprise_sans_requete(self):
        session = FakeSession(ok_routes())
        _, report = self.run_season(session)
        self.assertEqual((report.expected, report.downloaded, report.skipped_status), (2, 2, 1))
        self.assertEqual(sorted(p.name for p in self.folder().iterdir()),
                         ["11.json.gz", "12.json.gz", "list.json.gz"])
        self.assertNotIn(detail_url(13), session.calls)   # match reporté jamais demandé
        # Pause polie avant chaque requête, entre 1,0 et 1,5 s.
        self.assertEqual(len(self.sleeps), 3)
        self.assertTrue(all(1.0 <= s <= 1.5 for s in self.sleeps))

        session2 = FakeSession({})
        client2, report2 = self.run_season(session2)
        self.assertEqual(session2.calls, [])
        self.assertEqual((report2.present, report2.downloaded, report2.missing), (2, 0, 0))

    def test_fichier_illisible_retelecharge(self):
        self.run_season(FakeSession(ok_routes()))
        (self.folder() / "12.json.gz").write_bytes(b"\x1f\x8b tronque")
        session = FakeSession(ok_routes())
        _, report = self.run_season(session)
        self.assertEqual(session.calls, [detail_url(12)])
        self.assertEqual((report.present, report.downloaded), (1, 1))
        self.assertIsNone(rd.detail_problem(rd.read_json_gz(self.folder() / "12.json.gz")))

    def test_detail_sans_composition_compte_invalide(self):
        routes = ok_routes()
        bad = match_detail(12)
        bad["data"]["awayTeam"]["players"] = None
        routes[detail_url(12)] = [FakeResponse(200, bad)]
        _, report = self.run_season(FakeSession(routes))
        self.assertEqual((report.downloaded, report.invalid, report.missing), (1, 1, 1))

    def test_nouvelles_tentatives_sur_503(self):
        routes = ok_routes()
        routes[detail_url(11)] = [FakeResponse(503), FakeResponse(503),
                                  FakeResponse(200, match_detail(11))]
        client, report = self.run_season(FakeSession(routes))
        self.assertEqual(report.downloaded, 2)
        self.assertIn(5, self.sleeps)
        self.assertIn(15, self.sleeps)
        self.assertEqual(client.consecutive_failures, 0)

    def test_404_non_retente_et_compte_comme_echec(self):
        routes = ok_routes()
        routes[detail_url(11)] = [FakeResponse(404)]
        session = FakeSession(routes)
        client, report = self.run_season(session)
        self.assertEqual(session.calls.count(detail_url(11)), 1)
        self.assertEqual((report.failed, report.downloaded), (1, 1))
        self.assertEqual(client.consecutive_failures, 0)   # remis à zéro par le succès suivant

    def test_coupe_circuit_apres_3_echecs_consecutifs(self):
        payload = dict(LIST_PAYLOAD, data=[{"id": i, "status": "result"} for i in range(21, 26)])
        session = FakeSession({LIST_URL: [FakeResponse(200, payload)]})   # détails : 404
        with self.assertRaises(rd.CircuitBreakerOpen):
            self.run_season(session)
        self.assertEqual(len(session.calls), 4)   # liste + 3 détails, puis arrêt
        with (Path(self.tmp.name) / "failures.csv").open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["code"] for r in rows], ["404"] * 3)

    def test_max_requests(self):
        session = FakeSession(ok_routes())
        with self.assertRaises(rd.BudgetExhausted):
            self.run_season(session, max_requests=2)
        self.assertEqual(session.calls, [LIST_URL, detail_url(11)])

    def test_parse_seasons(self):
        self.assertEqual(rd.parse_seasons("top14", None),
                         [202101, 202201, 202301, 202401, 202501])
        self.assertEqual(rd.parse_seasons("prod2", "202201-202301"), [202201, 202301])
        self.assertEqual(rd.parse_seasons("top14", "202501,202101"), [202101, 202501])
        with self.assertRaises(ValueError):
            rd.parse_seasons("prod2", "202101")


if __name__ == "__main__":
    unittest.main()
