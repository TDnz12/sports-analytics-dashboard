"""Téléchargement hors ligne des matchs InCrowd (Top 14, Pro D2) : SEUL code réseau du rugby.

Pour chaque compétition et chaque saison : la liste des matchs (toujours size=400, une seule page),
puis le détail de chaque match au statut "result". Les JSON bruts sont écrits compressés, HORS du
dépôt, dans schema.json_dir() (défaut ~/rugby_raw_json, surchargeable par RUGBY_JSON_DIR) :

    <json_dir>/incrowd/<compId>/<saison>/list.json.gz
    <json_dir>/incrowd/<compId>/<saison>/<match_id>.json.gz
    <json_dir>/incrowd/failures.csv          (journal des échecs, ajouté à chaque lancement)

Usage :
    PYTHONPATH=. python scripts/rugby_download.py incrowd --comp top14
    PYTHONPATH=. python scripts/rugby_download.py incrowd --comp prod2 --seasons 202201-202301
    PYTHONPATH=. python scripts/rugby_download.py incrowd --comp top14 --max-requests 2   # essai

Reprise : un relancement ne télécharge que ce qui manque ou est invalide (JSON illisible, statut
différent de "result", composition absente pour une des deux équipes). Les listes déjà présentes
sont réutilisées (saisons terminées), sauf avec --refresh-lists. --force retélécharge tout.

Politesse : pause de 1,0 s plus un aléa de 0 à 0,5 s avant chaque requête, User-Agent explicite,
timeout 30 s. Erreurs 429, 5xx ou réseau : nouvelles tentatives après 5, 15 puis 45 s. Une
requête qui échoue encore après ses tentatives compte pour un échec ; 3 échecs consécutifs
arrêtent proprement le script (coupe-circuit), avec le résumé.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.rugby.schema import (  # noqa: E402
    COMPETITION_SPECS, SOURCE_INCROWD, json_dir, season_label,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rugby_download")

INCROWD_BASE = "https://rugby-union-feeds.incrowdsports.com/v1"
USER_AGENT = "sports-analytics-dashboard/1.0 (personal use, slow one-off download)"
TIMEOUT_S = 30
PAUSE_S = 1.0
PAUSE_JITTER_S = 0.5
RETRY_DELAYS_S = (5, 15, 45)
MAX_CONSECUTIVE_FAILURES = 3
LIST_SIZE = 400

INCROWD_COMPS = [k for k, s in COMPETITION_SPECS.items() if s.source == SOURCE_INCROWD]


class FetchError(Exception):
    """Requête en échec après ses nouvelles tentatives (ou erreur non retentée, ex. 404)."""

    def __init__(self, url: str, code, message: str):
        super().__init__(f"{url} : {code} {message}")
        self.url, self.code, self.message = url, code, message


class CircuitBreakerOpen(Exception):
    """Trop d'échecs consécutifs : on arrête tout."""


class BudgetExhausted(Exception):
    """--max-requests atteint."""


class Client:
    """Client HTTP poli : pause avant chaque requête, nouvelles tentatives, coupe-circuit, budget.
    `session` et `sleep` sont injectables pour les tests (faux client, pas de vraie attente)."""

    def __init__(self, session=None, sleep=time.sleep, max_requests: int | None = None,
                 failures_path: Path | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.sleep = sleep
        self.max_requests = max_requests
        self.failures_path = failures_path
        self.n_requests = 0          # requêtes HTTP réellement envoyées (tentatives comprises)
        self.n_fetches = 0           # appels à get_json (une ressource = un appel)
        self.consecutive_failures = 0

    def get_json(self, url: str) -> dict:
        if self.max_requests is not None and self.n_fetches >= self.max_requests:
            raise BudgetExhausted
        self.n_fetches += 1
        try:
            payload = self._get_with_retries(url)
        except FetchError as exc:
            self.consecutive_failures += 1
            self._log_failure(exc)
            logger.error("Échec %d/%d consécutif : %s", self.consecutive_failures,
                         MAX_CONSECUTIVE_FAILURES, exc)
            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise CircuitBreakerOpen from exc
            raise
        self.consecutive_failures = 0
        return payload

    def _get_with_retries(self, url: str) -> dict:
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            if attempt:
                delay = RETRY_DELAYS_S[attempt - 1]
                logger.warning("Nouvelle tentative %d/%d dans %d s : %s", attempt,
                               len(RETRY_DELAYS_S), delay, url)
                self.sleep(delay)
            self.sleep(PAUSE_S + random.uniform(0, PAUSE_JITTER_S))
            self.n_requests += 1
            try:
                resp = self.session.get(url, timeout=TIMEOUT_S)
            except requests.RequestException as exc:
                code, message, retry = "réseau", type(exc).__name__, True
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        code, message, retry = 200, "réponse non JSON", True
                else:
                    code, message = resp.status_code, resp.reason or ""
                    retry = resp.status_code == 429 or resp.status_code >= 500
            if not retry:
                break
        raise FetchError(url, code, message)

    def _log_failure(self, exc: FetchError) -> None:
        if self.failures_path is None:
            return
        self.failures_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.failures_path.exists()
        with self.failures_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(["horodatage_utc", "url", "code", "message"])
            writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             exc.url, exc.code, exc.message])


# --- Fichiers ---------------------------------------------------------------
def incrowd_dir(comp_id: int, season: int) -> Path:
    return json_dir() / "incrowd" / str(comp_id) / str(season)


def write_json_gz(path: Path, payload: dict) -> None:
    """Écriture atomique : fichier .tmp puis renommage, jamais de fichier tronqué."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json_gz(path: Path) -> dict | None:
    """Contenu du fichier, ou None s'il est absent ou illisible."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, EOFError, ValueError):
        return None


def detail_problem(payload: dict | None) -> str | None:
    """Raison pour laquelle un détail de match est inutilisable, ou None s'il est valide."""
    if payload is None:
        return "JSON absent ou illisible"
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return "bloc data absent"
    if data.get("status") != "result":
        return f"statut {data.get('status')!r}"
    for side in ("homeTeam", "awayTeam"):
        players = (data.get(side) or {}).get("players")
        if not isinstance(players, list) or not players:
            return f"composition absente ({side})"
    return None


def list_matches(payload: dict | None) -> list[dict] | None:
    """Matchs d'une liste, ou None si la liste est inutilisable (illisible ou paginée)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    meta = payload.get("metadata") or {}
    if meta.get("totalPages", 1) != 1:
        return None
    return payload["data"]


# --- Téléchargement ---------------------------------------------------------
@dataclass
class SeasonReport:
    competition: str
    season: int
    expected: int = 0          # matchs "result" de la liste
    skipped_status: int = 0    # matchs de la liste à un autre statut (reportés, annulés...)
    present: int = 0           # détails déjà valides avant ce lancement
    downloaded: int = 0
    invalid: int = 0           # téléchargés mais inutilisables (gardés sur disque)
    failed: int = 0
    list_status: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return self.expected - self.present - self.downloaded


def download_season(client: Client, report: SeasonReport, force: bool,
                    refresh_lists: bool) -> None:
    """Remplit `report` au fil de l'eau : en cas d'arrêt (coupe-circuit, budget), le résumé
    montre quand même où en était la saison."""
    competition, season = report.competition, report.season
    spec = COMPETITION_SPECS[competition]
    folder = incrowd_dir(spec.native_id, season)
    list_path = folder / "list.json.gz"

    matches = None if (force or refresh_lists) else list_matches(read_json_gz(list_path))
    if matches is not None:
        report.list_status = "en cache"
    else:
        url = (f"{INCROWD_BASE}/matches?provider=rugbyviz&compId={spec.native_id}"
               f"&season={season}&size={LIST_SIZE}")
        logger.info("Liste %s %s : %s", spec.label, season_label(competition, season), url)
        try:
            payload = client.get_json(url)
        except CircuitBreakerOpen:
            report.list_status = "échec"
            raise
        except FetchError:
            report.list_status = "échec"
            return
        matches = list_matches(payload)
        if matches is None:
            report.list_status = "invalide"
            report.notes.append("liste illisible ou sur plusieurs pages (non écrite)")
            return
        write_json_gz(list_path, payload)
        report.list_status = "téléchargée"

    results = [m for m in matches if m.get("status") == "result"]
    report.expected = len(results)
    report.skipped_status = len(matches) - len(results)
    logger.info("%s %s : %d matchs dans la liste, %d au statut result", spec.label,
                season_label(competition, season), len(matches), len(results))

    for i, match in enumerate(results, 1):
        match_id = match["id"]
        path = folder / f"{match_id}.json.gz"
        if not force and detail_problem(read_json_gz(path)) is None:
            report.present += 1
            continue
        url = f"{INCROWD_BASE}/matches/{match_id}?provider=rugbyviz&season={season}"
        logger.info("[%d/%d] Match %s (%s, journée %s)", i, len(results), match_id,
                    (match.get("date") or "")[:10], match.get("round"))
        try:
            payload = client.get_json(url)
        except CircuitBreakerOpen:
            report.failed += 1
            raise
        except FetchError:
            report.failed += 1
            continue
        problem = detail_problem(payload)
        write_json_gz(path, payload)   # écrit même invalide, pour pouvoir l'examiner
        if problem:
            report.invalid += 1
            report.notes.append(f"{match_id} : {problem}")
            logger.warning("Match %s inutilisable : %s", match_id, problem)
        else:
            report.downloaded += 1


def parse_seasons(competition: str, text: str | None) -> list[int]:
    """"202101-202501", "202301" ou "202101,202301" ; défaut : toutes les saisons du périmètre,
    de la plus ancienne à la plus récente."""
    allowed = sorted(COMPETITION_SPECS[competition].season_ids)
    if not text:
        return allowed
    chosen: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        lo_i, hi_i = int(lo), int(hi or lo)
        chosen.update(s for s in allowed if lo_i <= s <= hi_i)
        for bound in (lo_i, hi_i):
            if bound not in allowed:
                raise ValueError(f"Saison {bound} hors du périmètre de {competition} : {allowed}")
    return sorted(chosen)


def print_summary(reports: list[SeasonReport], client: Client, elapsed: float, stop: str) -> None:
    print("\n" + "=" * 78)
    print(f"Résumé ({client.n_requests} requêtes HTTP, {elapsed / 60:.1f} min){stop}")
    print("=" * 78)
    print(f"{'Saison':<20}{'liste':<13}{'attendus':>9}{'présents':>9}{'nouveaux':>9}"
          f"{'invalides':>10}{'échecs':>7}{'manquants':>10}")
    for r in reports:
        label = f"{COMPETITION_SPECS[r.competition].label} {season_label(r.competition, r.season)}"
        print(f"{label:<20}{r.list_status:<13}{r.expected:>9}{r.present:>9}{r.downloaded:>9}"
              f"{r.invalid:>10}{r.failed:>7}{r.missing:>10}")
        if r.skipped_status:
            print(f"    {r.skipped_status} match(s) de la liste à un autre statut que result, ignorés")
        for note in r.notes[:10]:
            print(f"    {note}")
        if len(r.notes) > 10:
            print(f"    ... et {len(r.notes) - 10} autres")
    print(f"\nDossier : {json_dir() / 'incrowd'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("incrowd", help="Listes et détails des matchs InCrowd")
    p.add_argument("--comp", choices=INCROWD_COMPS, nargs="+", required=True)
    p.add_argument("--seasons", help="ex. 202101-202501 (défaut : tout le périmètre)")
    p.add_argument("--force", action="store_true", help="Retélécharge tout, même valide.")
    p.add_argument("--refresh-lists", action="store_true",
                   help="Retélécharge les listes de matchs déjà en cache.")
    p.add_argument("--max-requests", type=int,
                   help="Nombre maximal de ressources téléchargées sur ce lancement.")
    args = parser.parse_args(argv)

    plan = []
    for comp in args.comp:
        try:
            plan += [(comp, s) for s in parse_seasons(comp, args.seasons)]
        except ValueError as exc:
            parser.error(str(exc))

    client = Client(max_requests=args.max_requests,
                    failures_path=json_dir() / "incrowd" / "failures.csv")
    logger.info("Dossier des JSON : %s", json_dir())
    reports: list[SeasonReport] = []
    stop = ""
    t0 = time.time()
    try:
        for comp, season in plan:
            reports.append(SeasonReport(comp, season))
            download_season(client, reports[-1], args.force, args.refresh_lists)
    except CircuitBreakerOpen:
        stop = f" ARRÊT : {MAX_CONSECUTIVE_FAILURES} échecs consécutifs"
    except BudgetExhausted:
        stop = f" ARRÊT : --max-requests {args.max_requests} atteint"
    except KeyboardInterrupt:
        stop = " ARRÊT : interrompu (Ctrl+C)"
    print_summary(reports, client, time.time() - t0, stop)
    return 1 if stop and "max-requests" not in stop else 0


if __name__ == "__main__":
    sys.exit(main())
