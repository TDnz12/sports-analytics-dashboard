"""Construction hors ligne des caches rugby : JSON bruts -> tables brutes (parquet) -> une table par
joueur et par saison (parquet), puis rapport de contrôle. Aucun accès réseau : les JSON doivent
déjà avoir été téléchargés par scripts/rugby_download.py.

Écrit, pour chaque saison :
    <racine>/raw/rugby/<compétition>/<saison>/{matches,lineups,player_match,events,team_match}.parquet
    <racine>/processed/rugby/<compétition>/<saison>.parquet            (saison complète)
    <racine>/processed/rugby/<compétition>/<saison>_regular.parquet    (phase régulière)
<racine> = data_cache/ par défaut, ou --out-root pour un essai hors du dépôt.

Usage :
    PYTHONPATH=. python scripts/rugby_build.py --comp top14
    PYTHONPATH=. python scripts/rugby_build.py --comp top14 --seasons 202501 --out-root /tmp/essai
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.base import write_cache  # noqa: E402
from data_sources.rugby import schema  # noqa: E402
from data_sources.rugby.aggregate import aggregate_season  # noqa: E402
from data_sources.rugby.incrowd import extract_season  # noqa: E402
from data_sources.rugby.minutes import reconstruct_minutes, team_minutes_check  # noqa: E402
from data_sources.rugby.positions import UNDETERMINED  # noqa: E402

PENALTY_TRY_POINTS = 7


def parse_seasons(competition: str, text: str | None) -> list[int]:
    """"202101-202501", "202501" ou "202101,202301" ; défaut : toutes les saisons du périmètre,
    de la plus ancienne à la plus récente (même syntaxe que rugby_download.py, recopiée pour ne
    pas importer un module qui charge requests)."""
    allowed = sorted(schema.COMPETITION_SPECS[competition].season_ids)
    if not text:
        return allowed
    chosen: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        lo_i, hi_i = int(lo), int(hi or lo)
        for bound in (lo_i, hi_i):
            if bound not in allowed:
                raise ValueError(f"Saison {bound} hors du périmètre de {competition} : {allowed}")
        chosen.update(s for s in allowed if lo_i <= s <= hi_i)
    return sorted(chosen)


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def control_report(tables: dict[str, pd.DataFrame], processed: dict[str, pd.DataFrame],
                   competition: str, summary: dict | None = None) -> list[str]:
    """Lignes du rapport de contrôle d'une saison (plan, 6.3). `summary`, s'il est fourni, reçoit
    les chiffres clés de la saison (une ligne du récapitulatif final)."""
    summary = {} if summary is None else summary
    spec = schema.COMPETITION_SPECS[competition]
    m, lu, pm, ev, tm = (tables[t] for t in schema.RAW_TABLES)
    lines = []
    add = lines.append

    # Matchs et feuilles
    n_final = int((m["phase"] == "final").sum())
    add(f"Matchs : {len(m)} ({len(m) - n_final} de phase régulière, {n_final} de phases finales"
        f"{' : attendu 5' if spec.regular_rounds and n_final != 5 else ''})")
    teams = pd.unique(pd.concat([m["home_team_uid"], m["away_team_uid"]]))
    add(f"Équipes : {len(teams)}")
    extra = m[m["extra_time"]]
    if len(extra):
        for r in extra.itertuples():
            add(f"  Prolongation : {r.match_uid} journée {r.round}, {r.home_team} {r.home_score}-"
                f"{r.away_score} {r.away_team} (durée de référence 100 min)")
    else:
        add("Prolongations : aucune")
    per_match_teams = lu.groupby("match_uid")["team_uid"].nunique()
    starters = lu[lu["is_starter"]].groupby(["match_uid", "team_uid"]).size()
    sheet = lu.groupby(["match_uid", "team_uid"]).size()
    add(f"Feuilles : {int((per_match_teams != 2).sum())} match(s) sans exactement 2 équipes ; "
        f"{int((starters != 15).sum())} équipe(s)-match sans exactement 15 titulaires ; "
        f"taille des feuilles {({int(k): int(v) for k, v in sheet.value_counts().sort_index().items()})}")
    dup = pm.duplicated(["match_uid", "player_uid"]).sum()
    add(f"Clés (match_uid, player_uid) en double dans player_match : {dup}")

    # Cohérence joueurs / équipe
    sums = pm.groupby(["match_uid", "team_uid"])[["points", "tries"]].sum().reset_index()
    chk = tm.merge(sums, on=["match_uid", "team_uid"], suffixes=("_team", "_players"))
    pts_gap = chk["points_team"] - chk["points_players"] - PENALTY_TRY_POINTS * chk["penalty_tries"]
    add(f"Points : somme des joueurs + 7 x essais de pénalité = points de l'équipe pour "
        f"{int((pts_gap == 0).sum())}/{len(chk)} équipes-matchs "
        f"({int(chk['penalty_tries'].sum())} essais de pénalité)")
    for r in chk[pts_gap != 0].head(5).itertuples():
        add(f"  écart {r.match_uid} {r.team} : équipe {r.points_team:.0f}, joueurs {r.points_players:.0f}")
    tries_gap = chk["tries_team"] - chk["tries_players"] - chk["penalty_tries"]
    tries_gap_raw = chk["tries_team"] - chk["tries_players"]
    add(f"Essais : somme des joueurs = essais de l'équipe hors essais de pénalité pour "
        f"{int((tries_gap == 0).sum())}/{len(chk)} ; essais de l'équipe tout compris pour "
        f"{int((tries_gap_raw == 0).sum())}/{len(chk)}")
    score = pd.concat([
        m[["match_uid", "home_team_uid", "home_score"]].set_axis(["match_uid", "team_uid", "score"], axis=1),
        m[["match_uid", "away_team_uid", "away_score"]].set_axis(["match_uid", "team_uid", "score"], axis=1),
    ]).merge(tm[["match_uid", "team_uid", "points"]], on=["match_uid", "team_uid"])
    add(f"Score du match = points de l'équipe : {int((score['score'] == score['points']).sum())}/{len(score)}")
    missed_ev = ev[ev["type"] == "penalty_missed"].groupby(["match_uid", "team_uid"]).size()
    mp = tm.set_index(["match_uid", "team_uid"])["penalty_goals_missed"]
    mp_ok = (mp.sub(missed_ev.reindex(mp.index).fillna(0)) == 0).sum()
    add(f"Pénalités manquées : événements = total équipe pour {int(mp_ok)}/{len(mp)} équipes-matchs "
        f"({int(missed_ev.sum())} événements, {int(mp.sum())} au total équipe)")

    # Minutes
    rebuilt = reconstruct_minutes(lu, ev, m)
    check = team_minutes_check(pm, rebuilt, m)
    reg, ext = check[~check["extra_time"]], check[check["extra_time"]]
    add(f"Minutes par équipe et par match (80 min) : min {_fmt(reg['minutes_sum'].min())}, "
        f"médiane {_fmt(reg['minutes_sum'].median())}, max {_fmt(reg['minutes_sum'].max())} "
        f"(référence 15 x 80 = 1 200)")
    for r in ext.itertuples():
        add(f"  Prolongation {r.match_uid} : {_fmt(r.minutes_sum)} min pour {r.team_uid} "
            f"(référence 15 x 100 = 1 500, attendu {_fmt(r.expected_min)})")
    per_match = pm.groupby("match_uid")["minutes"].sum().reindex(m["match_uid"])
    add(f"Minutes par match (2 équipes, 80 min) : min {_fmt(per_match[~m['extra_time'].values].min())}, "
        f"médiane {_fmt(per_match[~m['extra_time'].values].median())}, "
        f"max {_fmt(per_match[~m['extra_time'].values].max())} (référence 2 400)")
    add(f"Contrôle 15 x durée - exclusions (cartons d'après les événements), tolérance 5 min : "
        f"{int(check['ok'].sum())}/{len(check)} équipes-matchs dans la tolérance ; écart médian "
        f"{check['gap_min'].median():+.1f} min")
    worst = check.reindex(check["gap_min"].abs().sort_values(ascending=False).index).head(5)
    for r in worst.itertuples():
        add(f"  {r.match_uid} {r.team_uid} : somme {_fmt(r.minutes_sum)}, attendu "
            f"{r.expected_min:.0f} (exclusions {r.exclusion_min:.0f} min), écart {r.gap_min:+.0f}")
    cmp = pm[["match_uid", "player_uid", "minutes"]].merge(rebuilt, on=["match_uid", "player_uid"])
    diff = cmp["minutes_rebuilt"] - cmp["minutes"]
    valid = diff.notna()
    add(f"Validation croisée (minutes reconstruites depuis les événements contre minutesPlayedTotal) : "
        f"{(diff[valid].abs() <= 1).mean():.1%} des lignes à 1 minute près (objectif 95 %), "
        f"{(diff[valid] == 0).mean():.1%} exactes, {int((~valid).sum())} ligne(s) incohérente(s), "
        f"{int((diff[valid].abs() > 5).sum())} écart(s) de plus de 5 min")

    # Joueurs et postes
    full = processed["all"]
    played = full[full["games_played"] > 0]
    min_games, min_minutes = schema.SAMPLE_THRESHOLDS[spec.mode]
    add(f"Joueurs : {len(full)} sur au moins une feuille, {len(played)} avec au moins un match joué ; "
        f"phase régulière : {len(processed['regular'])}")
    add(f"Minutes : {_fmt(full['minutes_total'].sum())} au total ; joueurs au-dessus du seuil du "
        f"radar ({min_games} matchs et {min_minutes} min) : {int((~full['low_sample_size']).sum())}")
    counts = played["position_group"].value_counts()
    add("Postes (joueurs ayant joué) : " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    bench = played[played["position_source"] == "banc"]
    add(f"Repli banc (16, 17, 18) : {len(bench)} joueurs, dont {int((~bench['low_sample_size']).sum())} "
        f"au-dessus du seuil")
    und = full[full["position_group"] == UNDETERMINED]
    und_played = und[und["games_played"] > 0]
    und_ok = und[~und["low_sample_size"]]
    add(f"Indéterminé : {len(und)} joueurs ({len(und_played)} avec au moins un match joué), "
        f"dont {len(und_ok)} au-dessus du seuil du radar")
    for r in und_ok.sort_values("minutes_total", ascending=False).itertuples():
        add(f"  {r.player} ({r.team}) : {r.games_played} matchs, {r.minutes_total:.0f} min")
    homonyms = full[full["player_label"] != full["player"]]
    add(f"Homonymes (libellé « Nom (Club) ») : {len(homonyms)}")

    summary.update({
        "matchs": len(m), "finales": n_final, "prolong.": len(extra),
        "écarts points": int((pts_gap != 0).sum()), "écarts pén. manq.": int(len(mp) - mp_ok),
        "hors tol. minutes": int((~check["ok"]).sum()), "joueurs": len(full),
        "au-dessus seuil": int((~full["low_sample_size"]).sum()),
        "Indét. au-dessus": len(und_ok),
    })
    return lines


def build_season(competition: str, season_id: int, out_root: Path | None,
                 json_root: Path | None = None, summary: dict | None = None) -> list[str]:
    label = schema.season_label(competition, season_id)
    tables = extract_season(competition, season_id, json_root)
    for name, df in tables.items():
        write_cache(df, schema.raw_table_path(competition, label, name, root=out_root),
                    schema_version=schema.RUGBY_RAW_TABLES_SCHEMA_VERSION)
    processed = {}
    for period in schema.PERIODS:
        processed[period] = aggregate_season(tables, competition, period)
        write_cache(processed[period],
                    schema.processed_path(competition, label, period, root=out_root),
                    schema_version=schema.RUGBY_PROCESSED_SCHEMA_VERSION)
    spec = schema.COMPETITION_SPECS[competition]
    return ([f"=== {spec.label} {label} ==="]
            + control_report(tables, processed, competition, summary))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    incrowd = [k for k, s in schema.COMPETITION_SPECS.items() if s.source == schema.SOURCE_INCROWD]
    parser.add_argument("--comp", required=True, choices=incrowd)
    parser.add_argument("--seasons", help="ids InCrowd, ex. 202501 ou 202101-202501 (défaut : toutes)")
    parser.add_argument("--out-root", type=Path, help="racine de sortie à la place de data_cache/")
    args = parser.parse_args(argv)
    rows = []
    for season_id in parse_seasons(args.comp, args.seasons):
        summary = {"saison": schema.season_label(args.comp, season_id)}
        print("\n".join(build_season(args.comp, season_id, args.out_root, summary=summary)),
              flush=True)
        print()
        rows.append(summary)
    print(f"=== Récapitulatif {schema.COMPETITION_SPECS[args.comp].label} ===")
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
