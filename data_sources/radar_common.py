"""
Moteur commun du radar de comparaison (pages/1_Radar_de_comparaison.py), partagé par les sports :
- z-score et rang percentile par groupe de poste (_zscore_by_position, _percentile_by_position)
- pourcentage ajusté par padding vers la moyenne du poste (padded_pct)
- calcul des colonnes radar_<key>_z / _score / _percentile de chaque axe (score_axes)

Aucune règle propre à un sport ici : les axes, les seuils de matchs, le padding P et le volume
minimum restent dans le module du sport (voir nba.compute_radar_scores).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_by_position(stat_source: pd.DataFrame, apply_to: pd.DataFrame, impact_col: str, stat_mask: pd.Series) -> pd.Series:
    """Z-score de `impact_col` PAR GROUPE DE POSTE — moyenne/écart-type calculés sur
    `stat_source[stat_mask]`, appliqués aux valeurs de `apply_to[impact_col]`/
    `apply_to["position_group"]` — `apply_to` peut être le MÊME DataFrame que `stat_source` ou un
    AUTRE (voir score_axes, seul appelant actuel : normalise un axe du radar de
    comparaison par rapport aux joueurs du même poste, plutôt qu'en absolu)."""
    group_stats = stat_source.loc[stat_mask].groupby("position_group")[impact_col].agg(["mean", "std"])
    group_mean = apply_to["position_group"].map(group_stats["mean"])
    group_std = apply_to["position_group"].map(group_stats["std"])
    z = (apply_to[impact_col] - group_mean) / group_std
    return z.replace([np.inf, -np.inf], np.nan)


def _percentile_by_position(
    stat_source: pd.DataFrame, apply_to: pd.DataFrame, impact_col: str, stat_mask: pd.Series
) -> pd.Series:
    """Rang percentile de `impact_col` PAR GROUPE DE POSTE — même principe et mêmes paramètres
    que _zscore_by_position (même `stat_source`/`apply_to`/`stat_mask`), en rang plutôt qu'en
    écart-type : rang du joueur parmi les joueurs de RÉFÉRENCE (même poste, lignes de
    `stat_source` où `stat_mask` est vrai), en pourcentage de leur effectif, les ex aequo
    partageant leur rang moyen (décision C3 de l'audit rugby : sinon les 27 deuxièmes lignes à 0
    touche volée sur 70, Pro D2 2025-26, étaient tous au 39e centile, au lieu du 20e). Sans égalité,
    ou pour une valeur absente de la référence, rang = nombre de valeurs de référence inférieures
    ou égales, comme avant. Calcul volontairement simple (np.searchsorted) plutôt qu'une fonction
    de bibliothèque externe (évite une dépendance à scipy)."""
    ref = stat_source.loc[stat_mask]
    result = pd.Series(np.nan, index=apply_to.index, dtype=float)
    for group, ref_group in ref.groupby("position_group"):
        values = np.sort(ref_group[impact_col].dropna().to_numpy())
        n = len(values)
        if n == 0:
            continue
        in_group = apply_to["position_group"] == group
        col_vals = apply_to.loc[in_group, impact_col]
        valid = col_vals.notna()
        idx = col_vals[valid].index
        x = col_vals[valid].to_numpy()
        left = np.searchsorted(values, x, side="left")    # valeurs de référence strictement inférieures
        right = np.searchsorted(values, x, side="right")  # inférieures ou égales
        # Rang moyen des ex aequo : t valeurs égales au-dessus de b valeurs ont les rangs b+1 à b+t,
        # de moyenne b + (t + 1) / 2 = right - (t - 1) / 2. Sans égalité (t = 1) ou pour une valeur
        # absente de la référence (t = 0), le rang reste right.
        ranks = right - np.maximum(right - left - 1, 0) / 2
        result.loc[idx] = ranks / n * 100
    return result


def padded_pct(df: pd.DataFrame, made_col: str, att_col: str, padding: float,
               group_col: str = "position_group") -> pd.Series:
    """Pourcentage ajusté par padding : (réussis + P x moyenne du groupe) / (tentatives + P). La
    moyenne du groupe est le total des réussis / total des tentatives des lignes de `df` du même
    groupe (toutes, sans seuil). Aucun masque ici : le volume minimum sous lequel l'axe reste vide
    est une règle du sport, appliquée par l'appelant."""
    totals = df.groupby(group_col)[[made_col, att_col]].sum()
    group_pct = df[group_col].map(totals[made_col] / totals[att_col])
    return (df[made_col] + padding * group_pct) / (df[att_col] + padding)


def empty_axis(result: pd.DataFrame, key: str) -> None:
    """Colonnes radar_<key>_z / _score / _percentile à NaN (axe sans donnée ou sans poste)."""
    result[f"radar_{key}_z"] = np.nan
    result[f"radar_{key}_score"] = np.nan
    result[f"radar_{key}_percentile"] = np.nan


def score_axes(result: pd.DataFrame, axes: list[dict], stat_mask: pd.Series) -> pd.DataFrame:
    """Pour chaque axe de `axes` (format de nba.RADAR_AXES), ajoute à `result` (modifié sur place)
    `radar_<key>_z` (_zscore_by_position), `radar_<key>_score` (z clippé à ±3 écarts-types puis
    ramené sur [0, 100]) et `radar_<key>_percentile` (_percentile_by_position), la référence étant
    les lignes de `result` où `stat_mask` est vrai. La colonne notée est `score_col` si l'axe en a
    une, sinon `stat_col` ; absente de `result`, l'axe reste à NaN. Un axe `invert=True` est noté
    sur l'opposé de sa colonne (colonne temporaire, retirée du résultat) : la colonne d'origine
    garde la vraie valeur pour l'affichage. Renvoie `result` sans les colonnes temporaires."""
    temp_cols = []
    for axis in axes:
        col = axis.get("score_col", axis["stat_col"])
        if col not in result.columns:
            empty_axis(result, axis["key"])
            continue
        z_col = col
        if axis.get("invert"):
            z_col = f"_radar_{axis['key']}_inverted"
            result[z_col] = -result[col]
            temp_cols.append(z_col)
        z = _zscore_by_position(result, result, z_col, stat_mask)
        result[f"radar_{axis['key']}_z"] = z
        result[f"radar_{axis['key']}_score"] = (z.clip(-3, 3) + 3) / 6 * 100
        # Centile vide quand le score l'est (référence dégénérée : écart-type nul ou un seul joueur),
        # comme l'axe affiché en mode Indice (décision C2 de l'audit rugby).
        result[f"radar_{axis['key']}_percentile"] = _percentile_by_position(
            result, result, z_col, stat_mask).where(z.notna())
    return result.drop(columns=temp_cols)
