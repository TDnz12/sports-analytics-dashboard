"""
Éléments communs à tous les modules /data_sources/<sport>.py :
- schéma de colonnes normalisé partagé entre sports
- dataclass Metric utilisée pour peupler les sélecteurs X/Y du dashboard
- petits utilitaires (normalisation de noms pour les jointures, cache parquet)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd

try:
    from unidecode import unidecode
except ImportError:  # dépendance optionnelle mais recommandée (accents FR/ES/serbes...)
    def unidecode(s: str) -> str:
        return s


# Racine du cache local, partagée par tous les sports.
CACHE_ROOT = Path(__file__).resolve().parent.parent / "data_cache"
RAW_ROOT = CACHE_ROOT / "raw"
PROCESSED_ROOT = CACHE_ROOT / "processed"

# Colonnes garanties présentes (éventuellement à NaN) dans le DataFrame
# retourné par get_player_stats(season) de n'importe quel sport. Un sport
# peut ajouter des colonnes supplémentaires spécifiques (ex: PER pour NBA),
# mais le dashboard ne doit compter que sur ce socle + le catalogue METRICS
# du sport pour savoir quoi afficher.
COMMON_COLUMNS = [
    "sport",       # ex "nba"
    "season",      # ex "2023-24"
    "player",      # nom affiché
    "team",        # abréviation ou nom d'équipe
]


@dataclass(frozen=True)
class Metric:
    """Une métrique sélectionnable dans les listes déroulantes X / Y du dashboard."""

    key: str            # nom de colonne dans le DataFrame
    label: str           # libellé affiché dans l'UI
    fmt: str = ",.1f"    # format d'affichage (style Python format-spec)
    category: str = "Volume"  # regroupement dans l'UI: Volume / Efficacité / Salaire


def normalize_name(name: str) -> str:
    """Clé de jointure robuste pour matcher un même joueur entre deux sources
    (accents, casse, points, suffixes Jr./Sr./III...)."""
    if not isinstance(name, str):
        return ""
    n = unidecode(name).lower()
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n)
    n = re.sub(r"[^a-z\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


SCHEMA_VERSION_COL = "_schema_version"


def read_cache(path: Path, schema_version: int | None = None) -> pd.DataFrame | None:
    """Lit un cache parquet, ou None si absent. Si `schema_version` est fourni,
    le cache est aussi invalidé (traité comme absent) quand la version stockée
    ne correspond pas — ça évite qu'un changement de code (ex: nouvelle colonne
    calculée) laisse silencieusement un vieux cache incomplet en place jusqu'au
    prochain passage de scripts/prefill_cache.py. Un cache écrit avant l'introduction du
    versionnement (pas de colonne `_schema_version`) est aussi traité comme
    invalide dès qu'un `schema_version` est demandé."""
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if schema_version is not None:
        cached_version = df[SCHEMA_VERSION_COL].iloc[0] if SCHEMA_VERSION_COL in df.columns and len(df) else None
        if cached_version != schema_version:
            return None
    # _schema_version est un détail d'implémentation interne au cache, pas une donnée — sans ce
    # drop, elle fuit dans le DataFrame retourné à l'appelant. Repéré en testant : deux résultats
    # tous deux chargés depuis un cache (ex: nba_api stats + fiabilité) portent alors chacun leur
    # propre colonne `_schema_version`, et les fusionner (`.merge()`) plante avec une collision de
    # noms de colonnes — invisible tant qu'au moins un des deux venait d'un calcul frais.
    if SCHEMA_VERSION_COL in df.columns:
        df = df.drop(columns=SCHEMA_VERSION_COL)
    return df


def write_cache(df: pd.DataFrame, path: Path, schema_version: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema_version is not None:
        df = df.copy()
        df[SCHEMA_VERSION_COL] = schema_version
    df.to_parquet(path, index=False)
