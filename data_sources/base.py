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
    # Champs optionnels (rugby), vides pour la NBA : comportement inchangé.
    # made_col / attempts_col : réussis et tentatives d'un pourcentage, pour le détail
    # "78 % (52/67)" dans l'infobulle et le tableau. min_attempts : sous ce volume sur la saison,
    # "NC" (non classé) dans le tableau et point retiré du graph quand la métrique est en X ou Y.
    made_col: str | None = None
    attempts_col: str | None = None
    min_attempts: int | None = None
    # True : "peu fiable sur une saison" (mention dans le sélecteur, l'infobulle et sous le graph).
    unreliable: bool = False


@dataclass(frozen=True)
class CompetitionConfig:
    """Une compétition d'un sport qui en a plusieurs (rugby : Top 14, Pro D2, Six Nations), voir
    SportConfig.competitions dans data_sources/__init__.py. Définie ici plutôt que dans
    __init__.py pour que les modules de sport puissent l'importer sans import circulaire."""

    key: str             # identifiant interne, ex "top14"
    label: str           # libellé affiché dans l'UI, ex "Top 14"
    mode: str            # "club" ou "international"
    available: bool      # False -> affichée "bientôt disponible"
    seasons: list | None = None  # libellés de saison, la plus récente en premier


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


def sort_key(name: str) -> tuple:
    """Clé de tri alphabétique des listes affichées (équipes, joueurs) : sans accents ni casse,
    « Béziers » avant « Brive », « Šarić » avec les S, « Aaron » avant « AJ ». Ponctuation et
    suffixes gardés, contrairement à normalize_name (réservée à la recherche et à
    l'identification) : « A.J. Lawson » reste avant « Aaron Gordon ». Le nom d'origine départage
    deux clés égales, pour un ordre stable."""
    return unidecode(name).casefold(), name


def search_key(text) -> str:
    """Texte comparé par les champs de recherche : sans accents ni casse, même normalisation que
    sort_key (« Gaël » -> « gael », « Dončić » -> « doncic »)."""
    return unidecode(str(text)).casefold()


def filter_options(options: list, query: str, label=str, keep=()) -> list:
    """Options dont le libellé contient chaque mot de `query`, accents et casse ignorés (« gael f »
    trouve « Gaël Fickou »). Requête vide : toutes les options. Les options de `keep` (déjà
    sélectionnées) restent toujours, à leur place : le widget ne les perd pas. Le filtre intégré
    des listes Streamlit (1.64) ne fait que des minuscules, d'où ce filtrage côté Python."""
    words = search_key(query or "").split()
    if not words:
        return list(options)
    return [o for o in options if o in keep or all(w in search_key(label(o)) for w in words)]


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


# Posé dans DataFrame.attrs par un get_player_stats dont une partie des données n'a pas pu être
# chargée (liste de libellés). Les pages l'affichent en bandeau : sur Streamlit Cloud, ces
# manques n'ont sinon aucune trace visible (seulement les logs).
INCOMPLETE_DATA_ATTR = "incomplete_data"
_INCOMPLETE_DATA_EFFECTS = {
    "totaux de tirs": "3PT% et LF% ajustés indisponibles",
    "fiabilité": "fiabilité indisponible",
    "équipe du dernier match": "équipe affichée = équipe d'inscription, pas forcément la dernière",
}


def incomplete_data_warning(df: pd.DataFrame, season: str, relevant=None) -> str | None:
    """Texte du bandeau "données partielles" pour une saison, ou None si rien ne manque.
    `relevant` : libellés des manques qui concernent la page (Effectifs : seulement "équipe du
    dernier match", elle n'affiche ni tirs ni fiabilité) ; None = tous."""
    missing = [m for m in df.attrs.get(INCOMPLETE_DATA_ATTR) or [] if relevant is None or m in relevant]
    if not missing:
        return None
    effects = " ; ".join(_INCOMPLETE_DATA_EFFECTS.get(m, m) for m in missing)
    return f"Données partielles pour {season} : {effects}. Les autres stats ne sont pas concernées."


# Saison partagée entre les pages (st.session_state["selected_season"]) : triplet (sport,
# compétition ou None, saison), reprise seulement dans le sport et la compétition où elle a été
# choisie. ALL_SEASONS : mode "Toutes les saisons" du Dashboard, que le Radar et Effectifs n'ont
# pas ; ils le laissent intact tant qu'on n'y change pas la saison.
ALL_SEASONS = "toutes"


def shared_season(session_state, sport_key: str, competition_key: str | None) -> str | None:
    """Saison partagée si elle a été choisie dans ce sport et cette compétition, sinon None."""
    shared = session_state.get("selected_season")
    if shared and tuple(shared[:2]) == (sport_key, competition_key):
        return shared[2]
    return None
