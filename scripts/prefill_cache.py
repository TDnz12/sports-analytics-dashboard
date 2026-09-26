"""Pré-remplit le cache disque (data_cache/processed/nba/<saison>.parquet, plus les caches
de la grille Effectifs game_log_<saison> et mercato_<saison>) pour TOUTES les saisons couvertes par le dashboard (nba.SEASONS, 1996-97 -> 2025-26), pour qu'aucun
utilisateur ne se retrouve à attendre ~5-15s de calcul + appels réseau nba_api/Kaggle au
premier chargement de chaque saison.

Usage :
    PYTHONPATH=. python scripts/prefill_cache.py            # saisons pas encore en cache
    PYTHONPATH=. python scripts/prefill_cache.py --force     # recalcule tout, même en cache

Ne fait PAS planter le run entier si une saison échoue (panne réseau ponctuelle,
rate-limit stats.nba.com...) : l'erreur est loguée, la saison est marquée en échec dans
le résumé final, et le script continue avec la suivante. Relancer le script sans --force
retentera uniquement les saisons manquantes (celles qui ont réussi restent en cache).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources import nba  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prefill_cache")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Recalcule et re-télécharge même les saisons déjà en cache valide.",
    )
    args = parser.parse_args()

    seasons = list(nba.SEASONS)
    print(f"Pré-remplissage de {len(seasons)} saisons ({seasons[-1]} -> {seasons[0]}), "
          f"force={args.force}\n")

    results: dict[str, tuple[bool, float, str]] = {}
    t_start = time.time()

    for i, season in enumerate(seasons, 1):
        source = "legacy" if int(season[:4]) < nba.RATIN21_DATASET_START_YEAR else "ratin21"
        print(f"[{i}/{len(seasons)}] {season} (source salaires: {source})...", flush=True)
        t0 = time.time()
        try:
            df = nba.get_player_stats(season, force_refresh=args.force)
            elapsed = time.time() - t0
            processed_path = nba.NBA_PROCESSED_DIR / f"{season}.parquet"
            cached_ok = processed_path.exists()
            n_salary = int(df["salary_musd"].notna().sum())
            status = "OK" if cached_ok else "OK (non mis en cache, voir logs)"
            print(f"    -> {status} en {elapsed:.1f}s, {len(df)} joueurs, {n_salary} avec salaire")
            # Page Effectifs (grille) : game_log_<saison> (brut) + mercato_<saison> (traité), lus depuis le
            # cache s'il est déjà valide -- sans eux la page appelle nba_api en ligne.
            lineup = nba.get_mercato_lineup(season)
            nba.get_team_identity(season)
            cached_ok = cached_ok and (nba.NBA_PROCESSED_DIR / f"mercato_{season}.parquet").exists()
            print(f"    -> Mercato OK, {lineup['team'].nunique()} équipes")
            results[season] = (cached_ok, elapsed, "")
        except Exception as exc:
            elapsed = time.time() - t0
            logger.exception("Échec sur la saison %s", season)
            print(f"    -> ÉCHEC après {elapsed:.1f}s : {type(exc).__name__}: {exc}")
            results[season] = (False, elapsed, f"{type(exc).__name__}: {exc}")

    total_elapsed = time.time() - t_start
    n_ok = sum(1 for ok, _, _ in results.values() if ok)
    n_fail = len(results) - n_ok

    print(f"\n{'=' * 70}\nRÉSUMÉ\n{'=' * 70}")
    print(f"Temps total : {total_elapsed:.0f}s ({total_elapsed / 60:.1f} min)")
    print(f"Réussies (mises en cache) : {n_ok}/{len(seasons)}")
    if n_fail:
        print(f"Échouées ou non mises en cache : {n_fail}/{len(seasons)}")
        for season, (ok, elapsed, err) in results.items():
            if not ok:
                print(f"  - {season} ({elapsed:.1f}s) : {err or 'voir logs ci-dessus'}")
        print("\nRelance le script (sans --force) pour ne retenter que les saisons manquantes.")
    else:
        print("Toutes les saisons sont en cache.")


if __name__ == "__main__":
    main()
