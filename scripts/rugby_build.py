"""Construction hors ligne des caches rugby : JSON bruts -> tables brutes (parquet) -> une table par
joueur et par saison (parquet), puis rapport de contrôle. Aucun accès réseau : les JSON doivent
déjà avoir été téléchargés par scripts/rugby_download.py.

Écrit, pour chaque saison :
    <racine>/raw/rugby/<compétition>/<saison>/{matches,lineups,player_match,events,team_match}.parquet
    <racine>/processed/rugby/<compétition>/<saison>.parquet            (saison complète)
    <racine>/processed/rugby/<compétition>/<saison>_regular.parquet    (phase régulière)
puis, pour chaque fenêtre de 3 saisons qui contient une saison construite (mode 3 saisons du radar),
depuis les tables brutes parquet (sans relire les JSON) :
    <racine>/processed/rugby/<compétition>/<saison>_3saisons[_regular].parquet
<racine> = data_cache/ par défaut, ou --out-root pour un essai hors du dépôt.

Usage :
    PYTHONPATH=. python scripts/rugby_build.py --comp top14
    PYTHONPATH=. python scripts/rugby_build.py --comp top14 --seasons 202501 --out-root /tmp/essai
    PYTHONPATH=. python scripts/rugby_build.py --comp top14 --windows-only   (fenêtres seules)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.base import read_cache, write_cache  # noqa: E402
from data_sources.rugby import schema  # noqa: E402
from data_sources.rugby.aggregate import aggregate_season, aggregate_window  # noqa: E402
from data_sources.rugby.incrowd import (  # noqa: E402
    APPEARANCE_STATS, extract_season, score_gaps, scoring_check,
)
from data_sources.rugby.minutes import (  # noqa: E402
    TEAM_TOLERANCE_MIN, reconstruct_minutes, team_minutes_check,
)
from data_sources.rugby.positions import POSITION_GROUPS, UNDETERMINED  # noqa: E402


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

    # Cohérence joueurs / score officiel (après recomptage depuis les événements)
    key = ["match_uid", "team_uid"]
    recounted = pm[pm["score_source"] == "evenements"].drop_duplicates(key)
    add(f"Score recompté depuis les événements (essais, buts, points des joueurs) : "
        f"{len(recounted)} équipe(s)-match(s)")
    for r in recounted.itertuples():
        add(f"  {r.match_uid} {r.team_uid}")
    gaps = score_gaps(tables)
    pts_gap = gaps["gap"]
    add(f"Points : somme des joueurs + 7 x essais de pénalité = score officiel pour "
        f"{int((pts_gap == 0).sum())}/{len(gaps)} équipes-matchs "
        f"({int(gaps['penalty_tries'].sum())} essais de pénalité)")
    for r in gaps[pts_gap != 0].itertuples():
        add(f"  Écart restant, source gardée (le recomptage ne redonne pas le score) : {r.match_uid} "
            f"{r.team_uid}, score {r.score:.0f}, joueurs {r.player_points:.0f}")
    try_ev = ev[ev["type"] == "try"].groupby(key).size()
    tries_players = pm.groupby(key)["tries"].sum()
    tries_ok = (tries_players - try_ev.reindex(tries_players.index).fillna(0) == 0).sum()
    add(f"Essais : somme des joueurs = événements « essai » (hors essais de pénalité) pour "
        f"{int(tries_ok)}/{len(tries_players)} équipes-matchs")
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
    switched = pm[pm["minutes_method"] != "source"].drop_duplicates(["match_uid", "team_uid"])
    switched_extra = switched["match_uid"].isin(m.loc[m["extra_time"], "match_uid"])
    add(f"Minutes reconstruites à la place de la source : {len(switched)} équipe(s)-match(s) "
        f"({int(switched_extra.sum())} en prolongation, {int((~switched_extra).sum())} parce que la "
        f"source sort de la tolérance et la reconstruction y rentre)")
    for r in switched[~switched_extra.values].itertuples():
        add(f"  {r.match_uid} {r.team_uid}")
    add(f"Contrôle 15 x durée - exclusions (cartons d'après les événements), tolérance "
        f"{TEAM_TOLERANCE_MIN:.0f} min, après ce choix : {int(check['ok'].sum())}/{len(check)} "
        f"équipes-matchs dans la tolérance ; écart médian {check['gap_min'].median():+.1f} min")
    for r in check[~check["ok"]].itertuples():
        rb = rebuilt[(rebuilt["match_uid"] == r.match_uid) & (rebuilt["team_uid"] == r.team_uid)]
        add(f"  Hors tolérance, source gardée (reconstruction aussi hors tolérance ou incomplète) : "
            f"{r.match_uid} {r.team_uid}, somme source {_fmt(r.minutes_sum)}, reconstruite "
            f"{_fmt(rb['minutes_rebuilt'].sum())}, attendu {r.expected_min:.0f}, écart {r.gap_min:+.0f}")
    # Seulement les lignes en minutes source : ailleurs, la reconstruction serait comparée à
    # elle-même.
    cmp = pm.loc[pm["minutes_method"] == "source", ["match_uid", "player_uid", "minutes"]].merge(
        rebuilt, on=["match_uid", "player_uid"])
    diff = cmp["minutes_rebuilt"] - cmp["minutes"]
    valid = diff.notna()
    add(f"Validation croisée (minutes reconstruites depuis les événements contre minutesPlayedTotal, "
        f"{len(cmp)} lignes en minutes source) : "
        f"{(diff[valid].abs() <= 1).mean():.1%} des lignes à 1 minute près (objectif 95 %), "
        f"{(diff[valid] == 0).mean():.1%} exactes, {int((~valid).sum())} ligne(s) incohérente(s), "
        f"{int((diff[valid].abs() > 5).sum())} écart(s) de plus de 5 min")

    # Minutes inconnues, lignes "a joué" sans minute, compteurs de score (décisions B.3 et B.0 de
    # l'audit). Nom du joueur : celui de sa feuille de match.
    names = lu.drop_duplicates(["match_uid", "player_uid"]).set_index(["match_uid", "player_uid"])["player_name"]

    def who(r) -> str:
        return f"{r.match_uid} {r.team_uid} {names.get((r.match_uid, r.player_uid), r.player_uid)}"

    failed = pm[pm["minutes_method"] == "echec"]
    add(f"Minutes inconnues (echec : absentes ou négatives dans la source, ou reconstruction "
        f"incohérente) : {len(failed)} ligne(s)")
    for r in failed.itertuples():
        add(f"  {who(r)}")
    no_min = pm[pm["appeared"] & ~(pm["minutes"] > 0)]
    # Les 12 lignes relevées à l'audit avaient des plaquages ou des courses ; les autres ne
    # prouvent l'entrée en jeu que par une autre stat (passe, coup de pied, pénalité concédée...).
    in_audit = (no_min["tackles"].fillna(0) > 0) | (no_min["carries"].fillna(0) > 0)
    add(f"A joué sans minute (0 ou inconnue) mais avec des stats : {len(no_min)} ligne(s) "
        f"({int(in_audit.sum())} avec plaquages ou courses, relevées à l'audit ; "
        f"{int((~in_audit).sum())} avec une autre stat seulement)")
    for (r, audit) in zip(no_min.itertuples(), in_audit):
        proof = ", ".join(f"{c} {getattr(r, c):.0f}" for c in APPEARANCE_STATS
                          if pd.notna(getattr(r, c)) and getattr(r, c) > 0)
        add(f"  {'audit   ' if audit else 'nouvelle'} {who(r)}, minutes {r.minutes}, {proof}")
    fixed = pm[pm["score_source"] == "evenements_ligne"]
    add(f"Compteurs de score corrigés depuis les événements (points de la source = événements) : "
        f"{len(fixed)} ligne(s)")
    for r in fixed.itertuples():
        add(f"  {who(r)} : essais {r.tries:.0f}, transformations {r.conversions_made:.0f}, "
            f"pénalités {r.penalty_goals_made:.0f}, drops {r.drop_goals_made:.0f}, points {r.points:.0f}")
    disagree = scoring_check(tables)
    disagree = disagree[disagree["verdict"] == "desaccord"]
    add(f"Compteurs en désaccord avec les événements, source gardée : {len(disagree)} ligne(s)")
    for r in disagree.itertuples():
        add(f"  {who(r)} : compteurs {r.points_counters:.0f} pts, événements {r.points_events:.0f} pts, "
            f"source {r.points:.0f} pts")

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
    # Clubs (décision B.2) : club principal = le plus de minutes, comparé au club du dernier match.
    multi = full[full["clubs_detail"].map(lambda d: len(json.loads(d)) > 1)]
    last_club = (lu.merge(m[["match_uid", "date_utc"]], on="match_uid").sort_values("date_utc")
                 .drop_duplicates("player_uid", keep="last").set_index("player_uid")["team_uid"])
    moved = multi[multi["team_uid"] != multi["player_uid"].map(last_club)]
    add(f"Joueurs à plusieurs clubs : {len(multi)} ; club principal (le plus de minutes) différent "
        f"du club du dernier match : {len(moved)}")
    for r in moved.itertuples():
        add(f"  {r.player} : {r.team} ({', '.join(f'{n} {g}' for _, n, g in json.loads(r.clubs_detail))})")
    homonyms = full[full["player_label"] != full["player"]]
    add(f"Homonymes (libellé « Nom (Club) ») : {len(homonyms)}")

    summary.update({
        "matchs": len(m), "finales": n_final, "prolong.": len(extra),
        "score recompté": len(recounted), "écarts points": int((pts_gap != 0).sum()),
        "écarts pén. manq.": int(len(mp) - mp_ok),
        "minutes reconstr.": len(switched), "hors tol. minutes": int((~check["ok"]).sum()),
        "joueurs": len(full),
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


# Totaux comparés, dans le contrôle d'une fenêtre, à la somme des caches saison par saison.
WINDOW_CHECK_COLUMNS = ["games_played", "starts", "matchday_squads", "minutes_total", "tackles",
                        "missed_tackles", "metres", "carries", "penalties_conceded"]


def _reference(df: pd.DataFrame) -> pd.Series:
    """Population de référence du radar (même règle que radar.compute_radar_scores)."""
    return df["position_group"].isin(POSITION_GROUPS) & ~df["low_sample_size"]


def window_report(window: pd.DataFrame, seasons: dict[str, pd.DataFrame]) -> list[str]:
    """Contrôle d'une fenêtre (période donnée) : totaux = somme des caches saison, référence par
    poste contre la saison choisie, joueurs qui gagnent un radar, postes qui changent."""
    lines = []
    add = lines.append
    w = window.set_index("player_uid")
    last = seasons[w["window_end"].iloc[0]].set_index("player_uid")
    summed = sum(d.set_index("player_uid")[WINDOW_CHECK_COLUMNS].reindex(w.index).fillna(0)
                 for d in seasons.values())
    bad = ((summed - w[WINDOW_CHECK_COLUMNS].astype(float).fillna(0)).abs() > 1e-9).sum()
    union = set().union(*(d["player_uid"] for d in seasons.values()))
    add(f"Joueurs : {len(w)} (union des saisons : {len(union)}) ; saisons jouées "
        f"{w['seasons_played'].value_counts().sort_index().to_dict()}")
    add("Totaux = somme des caches saison (" + ", ".join(WINDOW_CHECK_COLUMNS) + ") : "
        + ("aucun écart" if not bad.any() else
           "ÉCARTS " + ", ".join(f"{c} {n}" for c, n in bad.items() if n)))
    ref_w = w[_reference(w)]["position_group"].value_counts()
    ref_1 = last[_reference(last)]["position_group"].value_counts()
    add(f"Référence (5 matchs et 520 min, avec poste) : {int(ref_1.sum())} joueurs sur la saison "
        f"choisie, {int(ref_w.sum())} sur la fenêtre")
    add("  " + ", ".join(f"{g} {int(ref_1.get(g, 0))} -> {int(ref_w.get(g, 0))}"
                         for g in POSITION_GROUPS))
    short = last[last["position_group"].isin(POSITION_GROUPS) & last["low_sample_size"]
                 & (last["games_played"] > 0)].index
    gained = [u for u in short if _reference(w).get(u, False)]
    add(f"Joueurs de la saison choisie en échantillon court : {len(short)}, dont {len(gained)} "
        f"dans la référence sur la fenêtre ; joueurs de référence absents de la saison choisie : "
        f"{int((_reference(w) & ~w.index.isin(last.index)).sum())}")
    changed = w["season_position_group"].notna() & (w["season_position_group"] != w["position_group"])
    add(f"Poste de la fenêtre différent de celui de la saison choisie : {int(changed.sum())} joueurs")
    return lines


def build_windows(competition: str, out_root: Path | None, touched: list[str] | None = None,
                  summary_rows: list | None = None) -> list[str]:
    """Caches des fenêtres de 3 saisons qui contiennent une saison de `touched` (toutes si None),
    depuis les tables brutes et les caches saison déjà écrits sous `out_root`."""
    lines = []
    for season in reversed(schema.season_labels(competition)):
        labels = schema.window_seasons(competition, season)
        if labels is None or (touched is not None and not set(labels) & set(touched)):
            continue
        title = f"=== {schema.COMPETITION_SPECS[competition].label} {labels[0]} à {season} (3 saisons) ==="
        raw = {s: {t: read_cache(schema.raw_table_path(competition, s, t, root=out_root),
                                 schema_version=schema.RUGBY_RAW_TABLES_SCHEMA_VERSION)
                   for t in schema.RAW_TABLES} for s in labels}
        per_season = {(s, p): read_cache(schema.processed_path(competition, s, p, root=out_root),
                                         schema_version=schema.RUGBY_PROCESSED_SCHEMA_VERSION)
                      for s in labels for p in schema.PERIODS}
        missing = sorted({s for s in labels if any(df is None for df in raw[s].values())}
                         | {s for (s, _), df in per_season.items() if df is None})
        if missing:
            lines += [title, f"Non construite : tables ou caches saison absents ou anciens pour "
                             f"{', '.join(missing)} (construire ces saisons d'abord).", ""]
            continue
        lines.append(title)
        for period in schema.PERIODS:
            window = aggregate_window(raw, competition, period)
            write_cache(window, schema.window_path(competition, season, period, root=out_root),
                        schema_version=schema.RUGBY_WINDOW_SCHEMA_VERSION)
            lines.append(f"Période {period} :")
            lines.extend("  " + line for line in window_report(
                window, {s: per_season[(s, period)] for s in labels}))
            if summary_rows is not None and period == "all":
                summary_rows.append({"fenêtre": f"{labels[0]} à {season}", "joueurs": len(window),
                                     "référence": int(_reference(window).sum())})
        lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    incrowd = [k for k, s in schema.COMPETITION_SPECS.items() if s.source == schema.SOURCE_INCROWD]
    parser.add_argument("--comp", required=True, choices=incrowd)
    parser.add_argument("--seasons", help="ids InCrowd, ex. 202501 ou 202101-202501 (défaut : toutes)")
    parser.add_argument("--out-root", type=Path, help="racine de sortie à la place de data_cache/")
    parser.add_argument("--windows-only", action="store_true",
                        help="seulement les fenêtres de 3 saisons, depuis les tables déjà construites")
    args = parser.parse_args(argv)
    if args.windows_only:
        windows = []
        print("\n".join(build_windows(args.comp, args.out_root, summary_rows=windows)), flush=True)
        print(pd.DataFrame(windows).to_string(index=False))
        return 0
    rows = []
    built = []
    for season_id in parse_seasons(args.comp, args.seasons):
        built.append(schema.season_label(args.comp, season_id))
        summary = {"saison": schema.season_label(args.comp, season_id)}
        print("\n".join(build_season(args.comp, season_id, args.out_root, summary=summary)),
              flush=True)
        print()
        rows.append(summary)
    windows = []
    print("\n".join(build_windows(args.comp, args.out_root, built, summary_rows=windows)), flush=True)
    print(f"=== Récapitulatif {schema.COMPETITION_SPECS[args.comp].label} ===")
    print(pd.DataFrame(rows).to_string(index=False))
    if windows:
        print(pd.DataFrame(windows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
