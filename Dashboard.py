"""
Dashboard interactif de data analytics sportive : NBA et rugby (Top 14, Pro D2).

Architecture multi-sport : ce fichier ne connaît que l'interface (Streamlit)
et le registre data_sources.SPORTS. Toute la logique spécifique à un sport
(scraping, téléchargement, normalisation, cache) vit dans /data_sources.
Ajouter un sport (MMA, tennis...) = créer data_sources/<sport>.py (ou un paquet
data_sources/<sport>/, comme le rugby) avec la même interface et l'enregistrer
dans data_sources/__init__.py.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_sources import SPORTS
from data_sources.base import (
    ALL_SEASONS, incomplete_data_warning, shared_season, sort_key,
)
from player_picker import player_picker

st.set_page_config(page_title="Sports Analytics Dashboard", layout="wide")

# CSS de densité : réduit les marges/espacements par défaut de Streamlit pour que le graph
# tienne à l'écran sans scroll au chargement. Purement présentationnel (aucune logique
# touchée). Cible les data-testid internes de Streamlit (écrits sous 1.63, toujours valides
# en 1.64.0) : plusieurs sélecteurs redondants (testid + fallback classe) pour rester
# robuste si la version change un peu.
st.markdown(
    """
    <style>
    /* Barre d'outils Streamlit tout en haut (icône menu, bouton Deploy visible seulement pour moi
       en tant que propriétaire). Root cause trouvée en inspectant le DOM réel de l'app (pas
       devinée) : cet élément a un `min-height: 60px` fixé par Streamlit -- une règle `height`
       seule (ce qu'on avait avant) ne peut jamais descendre sous un min-height, d'où l'absence
       totale d'effet des deux tentatives précédentes. Il faut aussi écraser min-height, avec
       !important (Streamlit charge sa feuille de style après la nôtre). Testé directement dans le
       navigateur avant d'écrire cette valeur : la barre se réduit bien, bouton Deploy et menu "..."
       restent entièrement visibles et cliquables. */
    header[data-testid="stHeader"] {
        height: 2.25rem !important;
        min-height: 2.25rem !important;
    }

    /* Deuxième élément non documenté trouvé au même endroit : stSidebarHeader, une rangée de
       60px en haut de la SIDEBAR (distincte de la barre ci-dessus) qui contient seulement le
       bouton « replier la sidebar » -- jamais ciblée jusqu'ici, c'est elle qui expliquait le
       "beaucoup trop d'espace au-dessus de Dashboard" (aucune règle plus haut ne la touchait).
       Testé de la même façon : le bouton reste pleinement cliquable une fois la rangée réduite. */
    div[data-testid="stSidebarHeader"] {
        height: 2.25rem !important;
        min-height: 0 !important;
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
    }

    /* Titre "Sports Analytics" déplacé ICI (retour utilisateur), dans stLogoSpacer -- un
       emplacement vide que Streamlit réserve dans cette même rangée pour un futur st.logo(), donc
       juste à gauche du bouton « replier la sidebar ». width: auto (au lieu de 0 par défaut, vide
       tant qu'aucun logo n'est fourni) + contenu via ::before (pas de balise <img>/texte natif
       disponible ici, juste ce slot vide) : fusionne le titre et cette rangée au lieu de deux
       lignes séparées, l'ancien st.sidebar.title() plus bas est retiré en conséquence (voir plus
       bas dans le script). Testé en direct : tient largement même avec le titre le plus long des
       3 pages ("Radar de comparaison"), pas de chevauchement avec le bouton. */
    div[data-testid="stLogoSpacer"] {
        width: auto !important;
        display: flex;
        align-items: center;
    }
    div[data-testid="stLogoSpacer"]::before {
        content: "Sports Analytics";
        font-weight: 700;
        font-size: 1rem;
        white-space: nowrap;
    }

    /* Remonte tout le contenu principal (le gros titre + le graph juste en dessous). Revenu à
       1.25rem (valeur confirmée sans coupure du titre) plutôt que de continuer à descendre ce
       chiffre : le vrai gain d'espace restant vient des deux règles ci-dessus (barre du haut +
       stSidebarHeader), pas d'un padding encore plus serré ici -- inutile de reprendre le risque
       de couper l'emoji du titre pour un gain marginal. */
    div[data-testid="stAppViewBlockContainer"], .block-container {
        padding-top: 1.25rem !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
        max-width: 100% !important;
    }
    div[data-testid="stAppViewBlockContainer"] h1:first-of-type {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    /* Espace au-dessus des liens de navigation multi-page (Dashboard / Radar de comparaison /
       Effectifs), juste en dessous de stSidebarHeader ci-dessus -- zone distincte du bloc "Sports
       Analytics" et de ses widgets encore en dessous (compactés par les règles suivantes, déjà en
       place). Pas de risque d'emoji/glyphe ici (juste du texte de lien), donc réduit plus
       franchement que le titre. */
    div[data-testid="stSidebarNav"] {
        padding-top: 0.2rem;
    }

    /* Sidebar : espace au-dessus du titre "Sports Analytics" quasi supprimé (le premier essai
       à 1rem sur stSidebarUserContent seul ne suffisait pas — l'espace venait aussi du conteneur
       parent, donc on le réduit aux deux niveaux). */
    section[data-testid="stSidebar"] {
        padding-top: 0 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
        padding-top: 0.25rem !important;
    }
    section[data-testid="stSidebar"] h1:first-of-type {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }

    /* Sidebar : espace vertical entre chaque widget, resserré à la demande de l'utilisateur
       (0.7rem/0.3rem jugé encore trop espacé). Testé en direct dans le navigateur avant de
       livrer : à 0.25rem/0.1rem les champs restent bien lisibles et ne se touchent pas, et les
       7 critères (Sport → Taille des points) tiennent visibles sans scroll. */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stElementContainer"] {
        margin-bottom: 0.1rem !important;
    }

    /* Titres et séparateurs de la sidebar (titre, "Filtres", lignes "---") moins espacés. */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        margin-top: 0.4rem !important;
        margin-bottom: 0.4rem !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    /* Les 2 séparateurs "---" (avant les axes X/Y et avant la recherche joueur) gardent plus
       d'air que les autres champs pour bien marquer les 3 sections de la sidebar, malgré
       l'espacement général resserré ci-dessus (retour utilisateur : ces lignes doivent se
       distinguer, pas juste ajouter un trait fin collé aux champs). */
    section[data-testid="stSidebar"] hr {
        margin: 1rem 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Sidebar : sélection du sport / saison / métriques / filtres
# --------------------------------------------------------------------------
# Titre retiré d'ici : fusionné dans la rangée du bouton replier la sidebar tout en haut (voir le
# commentaire CSS de stLogoSpacer plus haut) pour gagner une ligne entière de hauteur.

sport_keys = list(SPORTS.keys())


def _reset_season() -> None:
    # Changement de sport ou de compétition : les saisons proposées ne sont plus les mêmes
    # ("2024-25" contre "2026"). On oublie la saison mémorisée ; le script la réécrit ensuite
    # explicitement à la saison par défaut avant de créer le sélecteur (voir set_widget_default).
    st.session_state.pop("main_season", None)


def set_widget_default(key: str, value, valid=None) -> None:
    """Écrit la valeur d'un widget à clé dans st.session_state avant sa création, si elle manque
    (ou n'est plus une option valide). Retirer la clé ne suffit pas : Streamlit renvoie alors bien
    la valeur par défaut au script, mais n'ordonne pas au navigateur de mettre le widget à jour
    (même clé, donc même widget), qui garde l'ancienne valeur affichée (bug vu en passant du
    Top 14 "Toutes les saisons" au Pro D2). Une valeur écrite par l'API Session State, elle, est
    poussée au navigateur. Le widget est alors créé sans `value=` / `index=` (sinon Streamlit
    avertit d'un double réglage)."""
    if key not in st.session_state or (valid is not None and st.session_state[key] not in valid):
        st.session_state[key] = value


def _reset_sport_state() -> None:
    # Changement de sport : en plus de la saison, les curseurs gardent sinon la valeur choisie
    # pour l'autre sport (8 min par match en NBA, 0 en rugby).
    _reset_season()
    for key in ("min_minutes", "min_games", "show_low_sample"):
        st.session_state.pop(key, None)


# Sport et compétition partagés avec la page Radar par des clés de session NON liées à un widget
# (selected_sport, selected_competition), écrites à chaque run par chaque page et lues à l'arrivée
# sur la page. Les clés de widgets (main_sport, main_competition) ne suffisent pas : Streamlit
# efface l'état des widgets de la page qu'on quitte, d'où un retour en NBA à chaque changement de
# page. current_page : page du run précédent ; à l'arrivée depuis une autre page, le sélecteur est
# réaligné sur la clé partagée, même si son ancien état a survécu. NBA seulement si rien n'a
# jamais été choisi.
_entering_page = st.session_state.get("current_page") != "dashboard"
st.session_state["current_page"] = "dashboard"


def _sync_from_shared(widget_key: str, shared_key: str, valid: list, default, on_change=None) -> None:
    """Valeur initiale d'un sélecteur partagé entre pages, écrite avant sa création : la clé
    partagée à l'arrivée sur la page (ou si la valeur du widget n'est plus valide), sinon `default`.
    `on_change` (remise à zéro de la saison...) est appelé si une valeur déjà là est remplacée."""
    shared, current = st.session_state.get(shared_key), st.session_state.get(widget_key)
    if current in valid and not (_entering_page and shared in valid and shared != current):
        return
    new = shared if shared in valid else default
    if current is not None and current != new and on_change:
        on_change()
    st.session_state[widget_key] = new


# selectbox (pas radio) : un radio à une option par sport (dont la plupart pas encore
# disponibles, juste là pour annoncer la suite) prenait une ligne de hauteur par sport dans une
# sidebar déjà chargée -- retour utilisateur : ça poussait les sélecteurs d'axes (X/Y), bien plus
# utilisés au quotidien, sous la ligne de flottaison. Un menu déroulant replié fait la même chose sur 1 ligne, rien ne change
# côté fonctionnel (mêmes options, même format_func). Valeur initiale : selected_sport (voir
# _sync_from_shared), écrite dans session_state, d'où l'absence d'index=.
_sync_from_shared("main_sport", "selected_sport", sport_keys, sport_keys[0], _reset_sport_state)
sport_choice_key = st.sidebar.selectbox(
    "Sport",
    options=sport_keys,
    format_func=lambda k: SPORTS[k].label if SPORTS[k].available else f"{SPORTS[k].label} (bientôt disponible)",
    on_change=_reset_sport_state,
    key="main_sport",
)
st.session_state["selected_sport"] = sport_choice_key
sport = SPORTS[sport_choice_key]

if not sport.available:
    st.sidebar.info("Ce sport n'est pas encore disponible.")
    st.title(f"{sport.label}")
    st.info(
        "Ce sport arrive dans une prochaine version. Sports actifs pour l'instant : "
        + ", ".join(f"**{s.label}**" for s in SPORTS.values() if s.available) + "."
    )
    st.stop()

# Sélecteur "Compétition" (rugby : Top 14, Pro D2, Six Nations), seulement pour un sport qui en
# déclare (sport.competitions, None pour la NBA : pas de sélecteur). Les saisons proposées sont
# alors celles de la compétition choisie, et les fonctions du sport reçoivent competition=<clé>.
competition = None
if sport.competitions:
    _competitions = {c.key: c for c in sport.competitions}
    # Défaut : selected_competition (partagée avec le Radar), sinon la première compétition.
    _sync_from_shared("main_competition", "selected_competition", list(_competitions),
                      next(iter(_competitions)), _reset_season)
    competition_key = st.sidebar.selectbox(
        "Compétition",
        options=list(_competitions),
        format_func=lambda k: _competitions[k].label if _competitions[k].available
        else f"{_competitions[k].label} (bientôt disponible)",
        key="main_competition",
        on_change=_reset_season,
    )
    st.session_state["selected_competition"] = competition_key
    competition = _competitions[competition_key]
    if not competition.available:
        st.title(f"{sport.label} · {competition.label}")
        st.info(
            f"{competition.label} arrive dans une prochaine version. Compétitions disponibles : "
            + ", ".join(f"**{c.label}**" for c in sport.competitions if c.available) + "."
        )
        st.stop()
seasons = competition.seasons if competition else sport.seasons
competition_key = competition.key if competition else None

# Vue combinée : charge et concatène TOUTES les saisons (NBA : 1996-97 -> 2025-26, voir
# data_sources/nba.SEASONS) plutôt qu'une seule. Repose sur les deux sources
# de salaires documentées dans data_sources/nba.py (ratin21 pour 2010-11+, dataset CC0
# "legacy" avant, frontière à NBA_SALARY_CAP_BY_SEASON/RATIN21_DATASET_START_YEAR) :
# transparent ici, le DataFrame retourné par get_player_stats a le même schéma quelle que
# soit la source. Un échec ponctuel sur une saison (réseau, dataset absent...) n'empêche pas
# d'afficher les autres, voir failed_seasons plus bas.
ALL_SEASONS_LABEL = f"Toutes les saisons ({seasons[-1]} → {seasons[0]})"
ALL_SEASONS_KEYS = list(seasons)

season_options = [ALL_SEASONS_LABEL] + seasons
# Saison par défaut : sport.default_season (NBA : "2024-25", voir son commentaire dans
# data_sources/__init__.py), sinon la plus récente.
_default_season = sport.default_season if sport.default_season in seasons else seasons[0]
# Saison partagée avec le Radar et Effectifs par selected_season (triplet sport, compétition,
# saison, voir data_sources.base.shared_season), même principe que le sport : reprise à l'arrivée
# sur la page si elle a été choisie dans ce sport et cette compétition, écrite à chaque run
# ("Toutes les saisons" sous la forme ALL_SEASONS).
_shared_season = shared_season(st.session_state, sport.key, competition_key)
_shared_season = ALL_SEASONS_LABEL if _shared_season == ALL_SEASONS else _shared_season
if _entering_page and _shared_season in season_options:
    st.session_state["main_season"] = _shared_season
else:
    set_widget_default("main_season", _default_season, valid=season_options)
season = st.sidebar.selectbox("Saison", options=season_options, key="main_season")
is_all_seasons = season == ALL_SEASONS_LABEL
st.session_state["selected_season"] = (sport.key, competition_key, ALL_SEASONS if is_all_seasons else season)

# Statistiques utilisées (saison régulière / playoffs uniquement) : n'affecte QUE le scatter plot
# principal et le modèle qui le nourrit (voir get_player_stats(..., period=...) dans
# data_sources/nba.py pour le détail des 2 options). Volontairement limité au mode saison unique
# (complexité déjà présente en mode "Toutes les saisons" — bascule $/%, trajectoire, badges...
# voir la proposition validée) : le sélecteur disparaît entièrement plutôt que de rester affiché
# grisé/inutilisable.
#
# Un 3e mode ("Saison + Playoffs (agrégé)", period="regular_playoffs") a existé un temps puis a
# été retiré (décision explicite) : mélanger un échantillon cohérent (saison régulière, 82 matchs
# pour tout le monde) avec un échantillon non représentatif (playoffs, biaisé par qui se qualifie
# et jusqu'où) n'apportait pas assez de valeur pour la complexité que ça ajoutait. Le code qui le
# calculait (_combine_regular_playoffs_stats) a été supprimé de data_sources/nba.py -- si "regular_
# playoffs" apparaît encore quelque part (grep), c'est un oubli de ce nettoyage, pas une option
# valide.
#
# Défaut = "Saison régulière" (repassée en premier/par défaut après le retrait du mode combiné,
# qui l'avait temporairement remplacée). Même dict et même défaut dupliqués dans
# pages/1_Radar_de_comparaison.py (voir sa docstring) -- à resynchroniser à la main si cet ordre
# change à nouveau. Un autre sport fournit ses propres périodes (sport.stats_periods, rugby :
# saison complète / phase régulière), la première étant le défaut.
STATS_PERIOD_OPTIONS = sport.stats_periods or {
    "Saison régulière": "regular",
    "Playoffs uniquement": "playoffs",
}
_default_period = next(iter(STATS_PERIOD_OPTIONS.values()))
if not is_all_seasons:
    stats_period_label = st.sidebar.selectbox(
        "Statistiques utilisées", options=list(STATS_PERIOD_OPTIONS.keys()), index=0,
    )
    stats_period = STATS_PERIOD_OPTIONS[stats_period_label]
else:
    stats_period = _default_period


# La compétition fait partie de la clé de cache (None pour la NBA, dont get_player_stats ne reçoit
# alors aucun argument competition). Texte du chargement propre au sport (sport.loading_label) :
# st.cache_data appliqué ici plutôt qu'en décorateur pour le lui passer ; il ne s'affiche, comme
# avant, que lors d'un vrai calcul, pas quand le résultat est déjà en cache.
def _get_player_stats(sport_key: str, competition_key: str | None, season: str, period: str) -> pd.DataFrame:
    kwargs = {"competition": competition_key} if competition_key else {}
    return SPORTS[sport_key].get_player_stats(season, period=period, **kwargs)


_load_data_cached = st.cache_data(
    show_spinner=sport.loading_label or "Chargement des données NBA (nba_api + Kaggle)..."
)(_get_player_stats)


def load_data(sport_key: str, season: str, period: str) -> pd.DataFrame:
    return _load_data_cached(sport_key, competition_key, season, period)


@st.cache_data(show_spinner="Chargement du classement des équipes...")
def load_team_ranking(sport_key: str, season: str, period: str = "regular") -> pd.DataFrame:
    return SPORTS[sport_key].get_team_ranking(season, period=period)


# Pas de rechargement depuis l'interface : Streamlit Cloud ne joint pas stats.nba.com. Les données
# se mettent à jour en local avec scripts/prefill_cache.py, puis les caches sont versionnés.

if is_all_seasons:
    frames = []
    failed_seasons = []
    partial_warnings = []  # saisons chargées mais incomplètes (data_sources.base.INCOMPLETE_DATA_ATTR)
    for s in ALL_SEASONS_KEYS:
        try:
            # Période par défaut du sport (== stats_period ici de toute façon, voir plus haut) :
            # le mode "Toutes les saisons" n'a pas le sélecteur de période (NBA : saison
            # régulière seule ; rugby : saison complète).
            frames.append(load_data(sport.key, s, _default_period))
            if (msg := incomplete_data_warning(frames[-1], s)):
                partial_warnings.append(msg)
        except Exception as exc:  # nba_api down, pas d'internet, dataset Kaggle absent, etc.
            failed_seasons.append((s, exc))
    if not frames:
        st.error(f"Impossible de charger la moindre saison : {failed_seasons}")
        st.stop()
    df = pd.concat(frames, ignore_index=True)
    if failed_seasons:
        st.warning(
            "Certaines saisons n'ont pas pu être chargées et sont absentes du graph : "
            + ", ".join(f"{s} ({exc})" for s, exc in failed_seasons)
        )
    if partial_warnings:
        st.warning("\n\n".join(partial_warnings))
else:
    try:
        df = load_data(sport.key, season, stats_period)
    except Exception as exc:
        st.error(f"Impossible de charger les données pour {season} : {exc}")
        st.stop()
    if (msg := incomplete_data_warning(df, season)):
        st.warning(msg)

if df.empty:
    st.warning(f"Aucune donnée disponible pour {season}.")
    st.stop()

metrics = sport.metrics
metric_keys = list(metrics.keys())
# Récompenses individuelles (MVP, DPOY...) : optionnelles sur SportConfig, {} en repli pour un
# sport qui ne les expose pas encore (voir data_sources/__init__.py) -- pas de crash, juste aucun
# badge affiché pour ce sport-là.
AWARD_ICONS = sport.award_icons or {}
AWARD_LABELS = sport.award_labels or {}
# Calculée sur df ENTIER (avant tout filtre minutes/matchs/équipe, voir plot_df plus bas), PAS sur
# plot_df déjà filtré : le rapprochement (nba.match_season_awards) est volontairement strict et
# lève si un lauréat connu ne matche aucun joueur du roster de sa saison -- un lauréat filtré par
# le curseur "Minutes par match minimum" (ex. un joueur de banc comme Ike Austin, MIP 1996-97)
# ferait planter l'app si le rapprochement tournait sur la liste déjà réduite. En le calculant ici
# sur le roster complet puis en laissant `plot_df = df.copy()` propager la colonne, un lauréat
# filtré disparaît normalement de l'affichage (comme n'importe quel autre joueur) sans jamais
# déclencher l'exception -- l'exception ne doit se déclencher QUE pour un vrai problème de
# rapprochement de nom, jamais à cause d'un filtre d'affichage.
df["_awards"] = (
    sport.award_badges_fn(df) if sport.award_badges_fn is not None
    else pd.Series([[] for _ in range(len(df))], index=df.index)
)


UNRELIABLE_TXT = "peu fiable sur une saison"


def metric_label(key: str) -> str:
    m = metrics[key]
    return f"{m.label}  ·  {m.category}" + (f" ({UNRELIABLE_TXT})" if m.unreliable else "")


def _default_index(options: list, preferred, fallback: int) -> int:
    return options.index(preferred) if preferred in options else min(fallback, len(options) - 1)


# Nom affiché, recherché et surligné : sport.player_label_col ("Nom (Club)" pour les homonymes
# en rugby), "player" par défaut.
label_col = sport.player_label_col or "player"
# Colonnes catégorielles de "Colorer selon" ({colonne : libellé}) : l'équipe par défaut, plus la
# famille de poste et le poste en rugby.
categorical_colors = {
    c: lbl for c, lbl in (sport.categorical_colors or {"team": "Équipe"}).items() if c in df.columns
}


# Ordre de la sidebar (revu -- retour utilisateur, version précédente avait les axes X/Y sous la
# ligne de flottaison) : d'abord CE QU'ON REGARDE (axes/couleur/taille), juste après saison/
# période -- c'est la première chose qu'on veut voir/changer à l'ouverture de l'app. Puis la
# recherche joueur (utilisée quasi à chaque session, doit rester visible sans clic). Le reste
# (équipe, seuils minutes/matchs, salaires estimés, rafraîchir -- consultés occasionnellement,
# jamais à l'ouverture) est replié dans un expander pour ne pas alourdir le bandeau par défaut.
st.sidebar.markdown("---")
x_key = st.sidebar.selectbox(
    "Statistique en abscisse (X)", options=metric_keys, format_func=metric_label,
    index=_default_index(metric_keys, sport.default_x, 0),
)
y_key = st.sidebar.selectbox(
    "Statistique en ordonnée (Y)", options=metric_keys, format_func=metric_label,
    index=_default_index(metric_keys, sport.default_y, 1),
)

color_options = ["Aucune"] + metric_keys + list(categorical_colors)
# Couleur par défaut : sport.default_color (NBA : PIE, rugby : famille de poste), sinon aucune.
color_key = st.sidebar.selectbox(
    "Colorer selon", options=color_options,
    format_func=lambda k: "Aucune" if k == "Aucune" else categorical_colors.get(k) or metric_label(k),
    index=_default_index(color_options, sport.default_color, 0),
)

size_options = ["Aucune"] + metric_keys
default_size = "minutes_per_game" if "minutes_per_game" in metric_keys else "Aucune"
size_key = st.sidebar.selectbox(
    "Taille des points selon", options=size_options,
    format_func=lambda k: "Aucune" if k == "Aucune" else metric_label(k),
    index=size_options.index(default_size),
)

st.sidebar.markdown("---")
# Tri alphabétique sans accents ni casse (data_sources.base.sort_key).
player_options = ["Aucun"] + sorted(df[label_col].dropna().unique().tolist(), key=sort_key)
# Recherche d'un joueur : une seule case (player_picker, composant maison), recherche dans le
# navigateur sans accents ni casse, croix pour désélectionner. Le joueur choisi est gardé quand la
# saison change s'il y existe, sinon "Aucun".
if st.session_state.get("searched_player") not in player_options:
    st.session_state["searched_player"] = "Aucun"


def _set_searched_player(picked: list) -> None:
    st.session_state["searched_player"] = picked[0] if picked else "Aucun"


# Libellé dans la liste : le nom, et le poste quand le sport a un identifiant distinct du nom
# (rugby : "Nom · Poste", club entre parenthèses pour les seuls homonymes, comme le Radar ; le
# détail est dans l'infobulle). Toutes les saisons : poste de la saison la plus récente.
if sport.player_key_col and "position_group" in df.columns:
    _positions = (df.sort_values("season").drop_duplicates(label_col, keep="last")
                  .set_index(label_col)["position_group"])

    def _player_list_label(name) -> str:
        return f"{name} · {_positions[name]}"
else:
    _player_list_label = str
with st.sidebar:
    player_picker(
        player_options[1:],
        [] if st.session_state["searched_player"] == "Aucun" else [st.session_state["searched_player"]],
        _set_searched_player, key="player_picker", label="Rechercher un joueur", max_selected=1,
        placeholder=sport.search_placeholder, label_of=_player_list_label,
    )
searched_player = st.session_state["searched_player"]


def _handle_radar_click(player_key) -> None:
    # Exécuté par Streamlit avant le switch de page (callback on_click) : dépose le joueur/la
    # saison dans st.session_state, lus puis pop() par la page radar pour ne pré-sélectionner
    # qu'une fois. st.switch_page ici plutôt que dans le corps du script : un
    # switch_page() appelé en dehors d'un callback interromprait immédiatement le script AVANT
    # que le reste de la sidebar (filtres...) n'ait fini de s'afficher. Aussi le sport et la
    # compétition ; la période seulement pour un sport qui déclare les siennes (rugby), la NBA
    # gardant son comportement historique (saison régulière à l'ouverture du radar).
    st.session_state["radar_preselect_player"] = player_key
    st.session_state["radar_preselect_label"] = searched_player
    st.session_state["radar_preselect_season"] = None if is_all_seasons else season
    st.session_state["radar_preselect_sport"] = sport.key
    st.session_state["radar_preselect_competition"] = competition_key
    st.session_state["radar_preselect_period"] = stats_period if sport.stats_periods else None
    st.switch_page("pages/1_Radar_de_comparaison.py")


# Bouton masqué pour un sport sans radar. Le joueur est passé par son identifiant
# (sport.player_key_col, rugby : player_uid, pour les homonymes ; nom en NBA), calculé ici plutôt
# que dans le callback : au clic, df peut avoir été filtré plus bas dans ce script. En mode
# "Toutes les saisons", la ligne la plus récente du joueur.
if searched_player != "Aucun" and sport.compute_radar_scores is not None:
    _key_col = sport.player_key_col or label_col
    _radar_key = df.loc[df[label_col] == searched_player].sort_values("season")[_key_col].iloc[-1]
    st.sidebar.button(
        "Voir le profil radar", on_click=_handle_radar_click, args=(_radar_key,),
        help="Ouvre la vue radar de comparaison de profils avec ce joueur pré-sélectionné.",
    )

# Filtres avancés repliés (équipe, seuils minutes/matchs, salaires estimés) -- voir le
# commentaire d'ordre de la sidebar plus haut. expanded=False : replié par défaut, l'utilisateur
# l'ouvre seulement s'il en a besoin ce jour-là.
# Case "Afficher les échantillons courts" (sport.show_low_sample_default renseigné, rugby :
# décochée par défaut) : masque du graph les joueurs sous le seuil interne, le tableau détaillé
# les garde. NBA (None) : pas de case, ils restent affichés en losange.
show_low_sample = True
if sport.show_low_sample_default is not None:
    set_widget_default("show_low_sample", sport.show_low_sample_default)
    show_low_sample = st.sidebar.checkbox(
        "Afficher les échantillons courts", key="show_low_sample",
        help=f"Joueurs avec {sport.low_sample_label} sur la saison : masqués du graph par défaut, "
             "toujours présents dans le tableau détaillé.",
    )

with st.sidebar.expander("Filtres avancés"):
    teams = sorted(df["team"].dropna().unique().tolist(), key=sort_key)
    team_filter = st.multiselect("Filtrer par équipe (optionnel)", options=teams)

    position_filter = []
    if sport.position_filter_col and sport.position_filter_col in df.columns:
        _present = set(df[sport.position_filter_col].dropna())
        _order = sport.position_order or sorted(_present)
        position_filter = st.multiselect(
            "Filtrer par poste (optionnel)", options=[p for p in _order if p in _present],
        )

    st.markdown("---")
    set_widget_default(
        "min_minutes", sport.minutes_slider_default if sport.minutes_slider_default is not None else 8.0
    )
    min_minutes = st.slider(
        sport.minutes_slider_label or "Minutes par match minimum (filtrer le bruit \"garbage time\")",
        min_value=0.0, max_value=sport.minutes_slider_max or 40.0,
        step=1.0, key="min_minutes", format="%.0f" if sport.french_format else None,
    )
    # Seuil interne mentionné dans le help ci-dessous : 15 matchs en saison régulière
    # (MIN_GAMES_FOR_FIT), mais 4 en playoffs (MIN_GAMES_FOR_FIT_PLAYOFFS, voir son commentaire dans
    # data_sources/nba.py pour pourquoi 15 y est intenable) -- texte dynamique selon stats_period
    # (déjà connu à ce stade du script) plutôt qu'un nombre en dur qui serait faux la moitié du temps.
    # Autre sport : son seuil en clair (sport.low_sample_label).
    if sport.low_sample_label:
        _internal_threshold_txt = sport.low_sample_label
    else:
        _internal_threshold_txt = (
            "4 matchs en playoffs" if stats_period == "playoffs" else "15 matchs en saison régulière"
        ) + ", voir data_sources/nba.py"
    _low_sample_visibility_txt = (
        "les joueurs sous ce seuil sont visibles par défaut (losange creux dans le graph, "
        "échantillon court), à toi de décider si tu veux les masquer."
        if sport.show_low_sample_default is None else
        "les joueurs sous ce seuil se masquent ou s'affichent avec la case « Afficher les "
        "échantillons courts »."
    )
    set_widget_default("min_games", 0)
    min_games = st.slider(
        "Nombre de matchs joués minimum",
        min_value=0, max_value=sport.games_slider_max or 82, step=1, key="min_games",
        help=(
            "Filtre uniquement l'affichage (graph + tableau). Un seuil interne "
            f"({_internal_threshold_txt}) est indépendant de ce curseur : "
            + _low_sample_visibility_txt
        ),
    )

    n_estimated = int(df.get("salary_is_estimated", pd.Series(dtype=bool)).sum())
    include_estimated_salary = True
    if n_estimated:
        st.markdown("---")
        include_estimated_salary = st.checkbox(
            f"Inclure les salaires estimés (année proche) : {n_estimated} joueur(s)",
            value=True,
            help=(
                "Le dataset Kaggle n'a pas de ligne salaire pour l'année exacte de tous les "
                "joueurs. Pour ceux-là, on utilise le salaire de l'année la plus proche "
                "disponible (± 2 ans). Décoche pour ne garder que les salaires exacts."
            ),
        )


# --------------------------------------------------------------------------
# Filtrage
# --------------------------------------------------------------------------
plot_df = df.copy()
if "games_played" in plot_df.columns:
    plot_df = plot_df[plot_df["games_played"].fillna(0) >= min_games]
if team_filter:
    if "club_names" in plot_df.columns:  # rugby : un joueur apparaît dans chacun de ses clubs
        plot_df = plot_df[plot_df["club_names"].map(lambda c: not set(c).isdisjoint(team_filter))]
    else:
        plot_df = plot_df[plot_df["team"].isin(team_filter)]
if position_filter:
    plot_df = plot_df[plot_df[sport.position_filter_col].isin(position_filter)]
# Minimum de minutes appliqué en dernier, pour compter les joueurs qu'il retire seul (avec X et Y
# renseignés) : le message de graph vide ne conseille de le baisser que dans ce cas.
n_minutes_removed = 0
if "minutes_per_game" in plot_df.columns:
    _minutes_ok = plot_df["minutes_per_game"].fillna(0) >= min_minutes
    n_minutes_removed = int((~_minutes_ok & plot_df[[x_key, y_key]].notna().all(axis=1)).sum())
    plot_df = plot_df[_minutes_ok]
if not include_estimated_salary and "salary_is_estimated" in plot_df.columns:
    estimated_mask = plot_df["salary_is_estimated"].fillna(False)
    salary_cols = [c for c in ("salary", "salary_musd", "salary_pct_cap") if c in plot_df.columns]
    plot_df.loc[estimated_mask, salary_cols] = pd.NA


def nc_mask(frame: pd.DataFrame, key: str) -> pd.Series:
    """Lignes "NC" (non classé) d'une métrique à seuil de tentatives (Metric.min_attempts) : un
    pourcentage existe mais repose sur trop peu de tentatives. Toujours faux sinon (NBA)."""
    m = metrics.get(key)
    if m is None or m.min_attempts is None:
        return pd.Series(False, index=frame.index)
    return frame[key].notna() & (frame[m.attempts_col] < m.min_attempts)


# Tableau détaillé (sport.detail_lead_columns renseigné, rugby) : tous les joueurs des filtres,
# échantillons courts et "NC" compris, sans les seules valeurs X / Y réellement absentes.
table_base_df = plot_df.dropna(subset=[x_key, y_key])
# Joueurs des filtres sans valeur en X ou en Y (rugby : % au pied d'un non-buteur, aucune
# tentative) : absents du graph et du tableau, comptés pour la mention du tableau et le message
# de graph vide.
n_missing_xy = len(plot_df) - len(table_base_df)
_missing_labels = " ou ".join(f"« {metrics[k].label} »" for k in dict.fromkeys((x_key, y_key))
                              if plot_df[k].isna().any())


def _players(n: int) -> str:
    return f"{n} joueur{'s' if n > 1 else ''}"


# Échantillons courts masqués du graph (case décochée), comptés pour la mention sous le graph.
n_low_sample_hidden = 0
if not show_low_sample and "low_sample_size" in plot_df.columns:
    _low = plot_df["low_sample_size"].fillna(False).astype(bool)
    n_low_sample_hidden = int(plot_df.loc[_low].dropna(subset=[x_key, y_key]).shape[0])
    plot_df = plot_df[~_low]

# "NC" en X ou en Y : point retiré du graph (pourcentage sur trop peu de tentatives), compté pour
# la mention sous le graph.
_nc_xy = (nc_mask(plot_df, x_key) | nc_mask(plot_df, y_key)) & plot_df[[x_key, y_key]].notna().all(axis=1)
n_nc_hidden = int(_nc_xy.sum())
_nc_txt = ", ".join(
    f"{metrics[k].label} sous {metrics[k].min_attempts} tentatives"
    for k in dict.fromkeys((x_key, y_key)) if metrics[k].min_attempts is not None
)
plot_df = plot_df[~_nc_xy]
plot_df = plot_df.dropna(subset=[x_key, y_key])

x_meta, y_meta = metrics[x_key], metrics[y_key]


# --------------------------------------------------------------------------
# Contenu principal
# --------------------------------------------------------------------------
# "Toutes les saisons" n'a pas de sélecteur de période : celle utilisée (rugby : saison complète)
# est dite dans le titre. NBA (sans sport.stats_periods) : titre inchangé.
_title_period = [next(iter(STATS_PERIOD_OPTIONS))] if is_all_seasons and sport.stats_periods else []
st.title(" · ".join([sport.label] + ([competition.label] if competition else []) + [season]
                    + _title_period))

# Texte de méthodologie/sources — calculé ici mais affiché plus bas dans un expander replié,
# pour que le graph suive le titre sans texte interposé.
data_sources_caption = sport.source_caption or (
    "Stats de jeu : `nba_api` (stats.nba.com, live)  ·  Salaire & PER : dataset Kaggle "
    "ratin21/nba-player-stats-and-salaries-2010-2025 pour 2010-11 et après, complété par le "
    "dataset CC0 iampunitkmryh/nba-players-details-198518 pour 1996-97→2009-10 "
    "(les deux sourcés de Basketball-Reference / HoopsHype, voir `data_sources/nba.py` pour la "
    "frontière exacte)  ·  Salaire aussi disponible normalisé en % du plafond salarial officiel "
    "de la saison (`data_sources/nba.NBA_SALARY_CAP_BY_SEASON`), pour rester comparable entre "
    "saisons malgré la forte hausse du plafond dans le temps  ·  Données mises en cache "
    "localement dans `data_cache/`."
)

# Mention méthodologique du delta de rythme de jeu saison régulière / playoffs (voir le
# diagnostic de faisabilité playoffs) — mesuré, pas théorique : pace ligue quasi neutre dans les
# années 90-2000 (ex. -0.7 en 1996-97), jusqu'à -5.5 possessions/48min en 2023-24. Un volume par
# match plus faible en playoffs (moins de possessions) ne signifie donc pas nécessairement une
# baisse de niveau individuel — s'ajoute une défense plus dure/préparée et des rotations
# resserrées. Visible uniquement en mode playoffs (voir stats_period plus haut).
PLAYOFF_PACE_CAVEAT = (
    " Attention : écart de rythme de jeu saison régulière / playoffs : les playoffs se jouent à un rythme "
    "plus lent (jusqu'à -5.5 possessions/48min en 2023-24, écart quasi neutre dans les années "
    "90-2000 mais nettement plus marqué depuis) : un volume de stats par match plus faible en "
    "playoffs ne traduit donc pas forcément une baisse de niveau individuel, la défense plus "
    "dure et les rotations resserrées jouent aussi. Pas corrigé dans le calcul, à garder en tête "
    "en comparant les deux périodes."
)

# Mention méthodologique du seuil "échantillon court" différent en playoffs (voir
# nba.MIN_GAMES_FOR_FIT_PLAYOFFS/MIN_GAMES_FOR_FIT pour la justification complète et la mesure
# d'impact avant/après correction -- valeurs reprises en dur ci-dessous plutôt qu'importées,
# Dashboard.py ne connaît volontairement que data_sources.SPORTS, pas les modules de sport
# directement, même principe que les autres caveats de ce fichier) — même style que
# PLAYOFF_PACE_CAVEAT ci-dessus, visible uniquement en mode playoffs.
PLAYOFF_LOW_SAMPLE_THRESHOLD_CAVEAT = (
    " Attention : seuil \"échantillon court\" différent en playoffs : un joueur y est marqué à partir de "
    "moins de 4 matchs (contre 15 en saison régulière) : le nombre maximum de matchs réellement "
    "jouable en playoffs (~22-23 dans la pratique, 4 tours best-of-7) est trop faible pour garder "
    "le même seuil : appliqué tel quel, il marquait ~84% de tous les joueurs de playoffs, y "
    "compris un tiers à la moitié du roster de l'équipe championne. 4 matchs = le minimum pour "
    "compléter/sweeper une série."
)

missing_salary = df["salary"].isna().all() if "salary" in df.columns else True
if missing_salary and "salary_musd" in (x_key, y_key, color_key):
    st.warning(
        "Aucun salaire trouvé pour cette saison. Le dataset Kaggle n'est peut-être pas "
        "encore configuré (voir `README.md`, téléchargement manuel possible) ou ne couvre "
        "pas encore cette saison."
    )

# Avertissement visible (st.warning, pas juste le badge "Inclure les salaires estimés" de la
# sidebar) quand la quasi-totalité des salaires de la saison affichée sont un repli
# (salary_is_estimated=True) -- distinct du cas "aucun salaire du tout" ci-dessus : ici il Y A
# des chiffres, mais ils viennent presque tous d'une AUTRE saison. Détecté dynamiquement (seuil
# 90%, pas un season == "2025-26" en dur) plutôt que sur un numéro de saison fixe : se résorbe
# tout seul dès que le dataset Kaggle sera mis à jour pour couvrir la saison manquante, sans
# qu'il faille penser à retirer un test devenu obsolète (proposition validée, piste "source
# complémentaire" écartée -- repéré sur 2025-26 : dataset ratin21 qui s'arrête à 2024-25, 100%
# des 442 salaires de 2025-26 affichés étaient en réalité repris de la saison précédente).
n_priced = int(df["salary_musd"].notna().sum()) if "salary_musd" in df.columns else 0
n_estimated_early = int(df.get("salary_is_estimated", pd.Series(dtype=bool)).sum())
if n_priced and (n_estimated_early / n_priced) >= 0.9:
    st.warning(
        f"Les salaires de {season} ne sont pas encore disponibles dans la source de données "
        "(dataset Kaggle pas encore mis à jour pour cette saison) : les valeurs affichées sont en "
        "réalité reprises en repli de la saison précédente disponible, **pas** les vrais chiffres "
        "de cette saison. Redeviendra correct automatiquement dès que le dataset sera mis à jour "
        "(aucune date connue)."
    )

# Mentions de rythme de jeu/seuil "échantillon court" spécifiques aux playoffs (voir leur
# définition plus haut) : affichées dans l'expander méthodologie ci-dessous, uniquement quand
# stats_period == "playoffs" -- toujours pertinentes indépendamment de n'importe quel modèle
# (comparaison de stats brutes saison régulière/playoffs).
playoff_stats_caveat = (
    (PLAYOFF_PACE_CAVEAT + PLAYOFF_LOW_SAMPLE_THRESHOLD_CAVEAT) if stats_period == "playoffs" else None
)

# Graph vide : message selon la cause réelle (valeurs absentes, NC, échantillons courts masqués,
# minimum de minutes), sinon les filtres.
if plot_df.empty:
    _reasons = []
    if n_missing_xy:
        _reasons.append(f"{_players(n_missing_xy)} sans valeur pour {_missing_labels} "
                        "(aucune tentative ou donnée inconnue)")
    if n_nc_hidden:
        _reasons.append(f"{_players(n_nc_hidden)} NC ({_nc_txt})")
    if n_low_sample_hidden:
        _reasons.append(f"{_players(n_low_sample_hidden)} à échantillon court, masqués (case "
                        "« Afficher les échantillons courts »)")
    if n_minutes_removed:
        _reasons.append(f"{_players(n_minutes_removed)} sous le minimum de minutes par match "
                        "(essaie de le baisser)")
    st.warning("Aucun joueur à afficher : " + " ; ".join(_reasons) + "." if _reasons
               else "Aucun joueur ne correspond aux filtres actuels.")
    st.stop()

# Badge visuel (pas d'exclusion) pour les échantillons de saison trop courts — voir
# nba.MIN_GAMES_FOR_FIT. On garde low_sample_size (bool) pour la logique et on dérive un
# libellé lisible pour la légende du symbole plutôt que d'afficher "True"/"False".
symbol_key = None
LOW_SAMPLE_SYMBOL_LABEL = (
    f"Échantillon court ({sport.low_sample_label})" if sport.low_sample_label
    else "Échantillon court (peu de matchs)"
)
if "low_sample_size" in plot_df.columns:
    plot_df["Échantillon"] = plot_df["low_sample_size"].map(
        {True: LOW_SAMPLE_SYMBOL_LABEL, False: "Échantillon normal"}
    )
    symbol_key = "Échantillon"


def _format_value(value, fmt: str) -> str | None:
    if pd.isna(value):
        return None
    try:
        return format(value, fmt)
    except (ValueError, TypeError):
        return str(value)


def format_metric(row, key: str) -> str | None:
    """Valeur d'une métrique pour l'infobulle et le tableau. Pourcentage à tentatives (Metric.
    made_col, rugby) : "78 % (52/67)", précédé de "NC" sous le seuil (Metric.min_attempts).
    Sinon le format de la métrique (NBA : inchangé). None si la valeur manque."""
    m = metrics[key]
    value = row.get(key)
    if pd.isna(value):
        return None
    if m.made_col is None:
        if sport.french_format and m.fmt.endswith("%"):
            return f"{value * 100:.0f} %"
        text = _format_value(value, m.fmt)
        # Virgule décimale (rugby), comme le tableau détaillé et le radar : "11,4".
        return text.replace(".", ",") if sport.french_format else text
    made, attempts = row.get(m.made_col), row.get(m.attempts_col)
    text = f"{value * 100:.0f} % ({made:.0f}/{attempts:.0f})"
    if m.min_attempts is not None and attempts < m.min_attempts:
        return f"NC, {text}"
    return text


def _build_hover_text(row) -> str:
    """Infobulle 100% en français, libellés naturels, uniquement l'essentiel pour
    interpréter le point : équipe, salaire réel (toujours, peu importe les axes choisis), puis
    les métriques utilisées en X/Y/couleur/taille (sans doublon avec ce qui précède). L'alerte
    petit échantillon n'apparaît que pour les joueurs concernés — rien n'est affiché pour les
    autres."""
    lines = []
    if pd.notna(row.get("team")):
        lines.append(f"Équipe : {row['team']}")
    # Rugby : joueur passé par plusieurs clubs dans la saison ("Bordeaux-Bègles (10), Perpignan (4)").
    if isinstance(row.get("clubs"), str) and row["clubs"]:
        lines.append(f"Clubs : {row['clubs']}")
    # Poste en clair (rugby : "(banc)" pour un remplaçant jamais titulaire, "(poste mixte)" sous
    # 60 % des titularisations au poste principal).
    if pd.notna(row.get("position_label")):
        mixed = " (poste mixte)" if row.get("mixed_position") else ""
        lines.append(f"Poste : {row['position_label']}{mixed}")
    # Utile seulement en mode "Toutes les saisons" (sinon déjà indiqué dans le titre) : un même
    # joueur y apparaît comme plusieurs points distincts, un par saison jouée.
    if is_all_seasons and pd.notna(row.get("season")):
        lines.append(f"Saison : {row['season']}")

    salary_str = _format_value(row.get("salary_musd"), ",.2f")
    if salary_str is not None:
        suffix = " (estimé, année proche)" if row.get("salary_is_estimated") else ""
        lines.append(f"Salaire réel : {salary_str} M$" + suffix)

    # Récompenses individuelles (voir _awards, calculée via sport.award_badges_fn plus bas) —
    # toujours dans le tooltip quel que soit le mode (saison unique ou "Toutes les saisons"),
    # contrairement au badge visuel sur le graph lui-même qui est simplifié en mode dense (voir
    # la trace "award_text_rows" plus bas).
    awards = row.get("_awards")
    if awards:
        lines.append(
            "Récompenses : " + ", ".join(
                f"{AWARD_ICONS.get(a, '')} {AWARD_LABELS.get(a, a)}" for a in awards
            )
        )

    shown_keys = {"salary_musd"}
    for key in (x_key, y_key, color_key, size_key):
        if key in metrics and key not in shown_keys:
            val_str = format_metric(row, key)
            if val_str is not None:
                unreliable = f" ({UNRELIABLE_TXT})" if metrics[key].unreliable else ""
                lines.append(f"{metrics[key].label} : {val_str}{unreliable}")
            shown_keys.add(key)

    games = row.get("games_played")
    # Rugby : titularisations et minutes totales (minutes_total), plus parlantes qu'une moyenne
    # par match pour juger un échantillon.
    starts, minutes_total = row.get("starts"), row.get("minutes_total")
    if pd.notna(minutes_total):
        starts_str = f" ({starts:.0f} titularisations)" if pd.notna(starts) else ""
        games_str = f"{games:.0f}" if pd.notna(games) else "?"
        prefix = "Échantillon court : " if row.get("low_sample_size") else "Matchs joués : "
        lines.append(f"{prefix}{games_str} matchs{starts_str}, {minutes_total:.0f} min")
    elif row.get("low_sample_size"):
        games_str = f"{games:.0f}" if pd.notna(games) else "?"
        minutes = row.get("minutes_per_game")
        minutes_str = f", {minutes:.1f} min/match" if pd.notna(minutes) else ""
        lines.append(f"Échantillon court : {games_str} matchs joués{minutes_str}")
    elif pd.notna(games):
        lines.append(f"Matchs joués : {games:.0f}")

    return "<br>".join(lines)


# _awards déjà présente (calculée sur df entier avant filtrage, voir plus haut) : propagée telle
# quelle depuis df via plot_df = df.copy() + les filtres, pas recalculée ici.
plot_df["_hover"] = plot_df.apply(_build_hover_text, axis=1)

# Bordure dorée COLLÉE au marqueur du joueur primé (même taille que son propre point), pas un
# anneau séparé plus grand : ajustable uniquement via marker.line.color/width du point lui-même,
# donc calculée ici en tant que colonnes (une par point) et transportée via custom_data jusqu'à
# fig.for_each_trace plus bas (px.scatter n'a pas de paramètre pour mapper une colonne sur
# marker.line.color directement).
# En mode "Toutes les saisons" : un or vif semi-transparent (1res versions testées) devenait
# presque invisible contre un remplissage jaune-vert -- justement la teinte la plus fréquente au
# milieu de l'échelle RdYlGn, vérifié par comparaison directe (image de contrôle) sur 3
# remplissages (jaune pâle/jaune-vert/vert) : illisible en semi-transparent, nettement visible en
# "darkgoldenrod" plein. D'où une teinte plus sombre plutôt qu'une transparence réduite — une
# opacité plus faible aurait le même problème de fond quel que soit le niveau choisi.
_award_border_color = "#B8860B" if is_all_seasons else "#FFD700"  # darkgoldenrod vs or vif
_award_border_width = 2.2 if is_all_seasons else 2.5
plot_df["_border_color"] = plot_df["_awards"].map(lambda a: _award_border_color if a else "DarkSlateGrey")
plot_df["_border_width"] = plot_df["_awards"].map(lambda a: _award_border_width if a else 0.5)

# Pourcentages en "10 %" plutôt qu'en "0.1" sur les axes et la barre de couleur
# (sport.french_format, rugby ; la NBA garde ses graduations) : valeurs du graph multipliées par
# 100 et suffixe " %" (le format d3 ".0%" n'écrit pas l'espace). Après la construction des
# infobulles, qui lisent les fractions d'origine.
pct_scaled = set()
if sport.french_format:
    for _k in dict.fromkeys((x_key, y_key, color_key)):
        if _k in metrics and metrics[_k].fmt.endswith("%"):
            plot_df[_k] = plot_df[_k] * 100
            pct_scaled.add(_k)

# Couleurs fixes d'une colonne catégorielle (sport.category_colors, rugby : Avants bleu, Arrières
# rouge, Indéterminé gris), quelles que soient la compétition et la saison, dans cet ordre de
# légende. Sans elles, plotly attribue les couleurs dans l'ordre d'apparition des valeurs, qui
# change d'une saison à l'autre.
_fixed_colors = (sport.category_colors or {}).get(color_key)
fig = px.scatter(
    plot_df,
    x=x_key,
    y=y_key,
    color=None if color_key == "Aucune" else color_key,
    size=None if size_key == "Aucune" else size_key,
    symbol=symbol_key,
    symbol_map={"Échantillon normal": "circle", LOW_SAMPLE_SYMBOL_LABEL: "diamond"} if symbol_key else None,
    size_max=28,
    hover_name=label_col,
    custom_data=["_hover", "_border_color", "_border_width"],
    color_continuous_scale="RdYlGn" if color_key in metrics and metrics[color_key].category == "Efficacité" else "Viridis",
    labels={x_key: x_meta.label, y_key: y_meta.label, **({color_key: metrics[color_key].label} if color_key in metrics else {}),
            **({color_key: categorical_colors[color_key]} if color_key in categorical_colors else {})},
    color_discrete_map=_fixed_colors,
    category_orders={color_key: list(_fixed_colors)} if _fixed_colors else None,
    template="plotly_white",
    height=700,
    # PAS de render_mode forcé : plotly express bascule automatiquement en WebGL (Scattergl) au-delà
    # de ~1000 points (cas courant du mode "Toutes les saisons", plusieurs milliers de lignes) --
    # accélération GPU précieuse à cette échelle (pan/zoom/hover nettement plus fluides). Forcer le
    # SVG globalement pour régler le z-order du surlignage (essayé, puis retiré) dégradait au
    # contraire la fluidité du nuage principal en mode "Toutes les saisons". Le vrai fix, plus bas :
    # faire correspondre le moteur de la trace de surlignage à celui réellement choisi ici pour le
    # nuage (Scattergl si bascule WebGL, Scatter sinon), plutôt que d'imposer le même moteur partout.
)
fig.update_traces(
    hovertemplate="<b>%{hovertext}</b><br>%{customdata[0]}<extra></extra>",
)

# Légende réduite aux couleurs (sport.legend_symbols=False, rugby) : plotly nomme chaque trace
# "couleur, échantillon" ("Avants, Échantillon normal") ; on retire la partie échantillon et on
# ne garde qu'une entrée par couleur. Le losange est expliqué par la mention sous le graph.
if symbol_key and sport.legend_symbols is False:
    _seen_legend = set()
    for _trace in fig.data:
        _parts = [p for p in (_trace.name or "").split(", ")
                  if p not in ("Échantillon normal", LOW_SAMPLE_SYMBOL_LABEL)]
        _name = ", ".join(_parts)
        _trace.name = _trace.legendgroup = _name
        _trace.showlegend = bool(_name) and _name not in _seen_legend
        _seen_legend.add(_name)


def _apply_award_borders(trace) -> None:
    # symbol=symbol_key scinde le nuage principal en plusieurs traces (une par catégorie
    # d'échantillon) -- chacune ne contient qu'un SOUS-ENSEMBLE de plot_df, dans un ordre propre à
    # px.scatter. custom_data[1]/[2] (couleur/largeur de bordure) voyage avec chaque ligne à
    # travers ce découpage, donc les relire ici depuis trace.customdata donne le bon tableau pour
    # CETTE trace précise, sans avoir à reconstituer le découpage nous-mêmes.
    if trace.customdata is None or len(trace.customdata) == 0:
        return
    trace.marker.line.color = [c[1] for c in trace.customdata]
    trace.marker.line.width = [float(c[2]) for c in trace.customdata]


fig.for_each_trace(_apply_award_borders)
if pct_scaled:
    fig.update_xaxes(ticksuffix=" %" if x_key in pct_scaled else None)
    fig.update_yaxes(ticksuffix=" %" if y_key in pct_scaled else None)
    if color_key in pct_scaled:
        fig.update_layout(coloraxis_colorbar_ticksuffix=" %")
if sport.french_format:  # graduations en virgule décimale (rugby) ; NBA : rien n'est passé
    fig.update_layout(separators=", ")
fig.update_layout(
    xaxis_title=x_meta.label,
    yaxis_title=y_meta.label,
    # La légende des symboles (Échantillon) et la barre de couleur (colorbar) se
    # disputaient toutes les deux le coin haut-droit par défaut et se chevauchaient. On les
    # sépare explicitement : légende horizontale au-dessus du graph, colorbar recentrée et
    # raccourcie sur la droite — indépendant de la métrique choisie en couleur.
    legend=dict(
        title_text="",
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
    ),
    coloraxis_colorbar=dict(
        len=0.85,
        yanchor="middle",
        y=0.45,
    ),
    margin=dict(t=90),
)

# Surlignage du joueur recherché : trace séparée ajoutée PAR-DESSUS le nuage existant (dernière
# trace = dessinée au-dessus dans Plotly — vrai pour deux traces de même moteur de rendu). Le
# nuage principal ci-dessus peut être en Scatter (SVG) ou Scattergl (WebGL) selon sa taille (voir
# commentaire plus haut) ; WebGL et SVG sont composités dans des calques séparés par le
# navigateur, donc l'ordre des traces ne suffit à garantir le z-order QUE si le surlignage utilise
# le MÊME moteur que le nuage — d'où la détection ci-dessous plutôt qu'un go.Scatter fixe. Ne
# modifie aucun point du graph, juste un contour + nom ajoutés visuellement. hoverinfo="skip" pour
# ne pas dupliquer/bloquer l'infobulle du point réel. Taille (34) volontairement au-dessus de
# size_max=28 du nuage principal (jamais recouvert par un marqueur du nuage, même le plus gros) ;
# contour épais (6px) et couleur qui tranche sur les deux échelles de couleur utilisées (RdYlGn /
# Viridis) pour rester lisible même sans chevauchement.
highlight_scatter_cls = go.Scattergl if type(fig.data[0]).__name__ == "Scattergl" else go.Scatter

# Badges de récompenses individuelles (MVP, DPOY, ROY, MIP, 6MOY, MVP des Finales) : la bordure
# dorée du point lui-même (voir _award_border_color/_border_width + fig.for_each_trace plus haut)
# marque déjà le lauréat sans trace séparée. Reste ici uniquement l'émoji composite au-dessus du
# point (ex. "👑🎖️" si cumul MVP + MVP des Finales la même saison), qui complète la bordure — la
# couleur seule ne dit pas QUELLE récompense. Affiché SEULEMENT en saison unique : en mode "Toutes
# les saisons" (~180 points primés sur toute la période, souvent proches les uns des autres dans
# l'espace salaire/perf), des étiquettes texte permanentes se chevaucheraient — voir proposition
# validée ; le détail complet reste de toute façon dans le tooltip (_build_hover_text) dans les
# deux modes. Ajouté AVANT le surlignage du joueur recherché ci-dessous (donc dessous, cohérent
# avec le z-order).
award_rows = plot_df[plot_df["_awards"].map(bool)]
if not award_rows.empty and AWARD_ICONS and not is_all_seasons:
    # Le joueur recherché a déjà son propre label texte "top center" (surlignage ci-dessous) —
    # exclu ici pour ne pas superposer deux textes au même endroit ; sa (ses) éventuelle(s)
    # récompense(s) reste(nt) visible(s) via la bordure dorée de son point + le tooltip.
    text_rows = award_rows if searched_player == "Aucun" else award_rows[award_rows[label_col] != searched_player]
    if not text_rows.empty:
        badge_labels = text_rows["_awards"].map(
            lambda codes: "".join(AWARD_ICONS.get(c, "") for c in codes)
        )
        fig.add_trace(
            highlight_scatter_cls(
                x=text_rows[x_key],
                y=text_rows[y_key],
                mode="text",
                text=badge_labels,
                textposition="top center",
                textfont=dict(size=16),
                hoverinfo="skip",
                showlegend=False,
            )
        )

if searched_player != "Aucun":
    highlight_row = plot_df[plot_df[label_col] == searched_player]
    if highlight_row.empty:
        _hidden_low = (not show_low_sample) and bool(
            df.loc[df[label_col] == searched_player, "low_sample_size"].fillna(False).any()
        ) if "low_sample_size" in df.columns else False
        st.info(
            f"**{searched_player}** ne correspond à aucun point affiché avec les filtres "
            "actuels (minutes/matchs joués minimum, équipe...). Élargis les filtres pour le voir."
            + (" Son échantillon est court : coche « Afficher les échantillons courts »."
               if _hidden_low else "")
        )
    else:
        # En mode "Toutes les saisons", un même joueur peut avoir plusieurs points (un par
        # saison) — chacun est entouré, avec la saison ajoutée au label pour les distinguer.
        highlight_labels = (
            [f"{searched_player} ({s})" for s in highlight_row["season"]]
            if is_all_seasons
            else [searched_player] * len(highlight_row)
        )
        fig.add_trace(
            highlight_scatter_cls(
                x=highlight_row[x_key],
                y=highlight_row[y_key],
                mode="markers+text",
                marker=dict(size=34, color="rgba(0,0,0,0)", line=dict(color="#FF1E56", width=6)),
                text=highlight_labels,
                textposition="top center",
                textfont=dict(size=13, color="#FF1E56", family="Arial Black"),
                hoverinfo="skip",
                showlegend=False,
            )
        )

st.plotly_chart(fig, width='stretch')

# Losange : toujours expliqué pour la NBA ; pour un sport à case "Afficher les échantillons
# courts", seulement quand des losanges sont réellement à l'écran.
if symbol_key and (sport.show_low_sample_default is None or plot_df["low_sample_size"].any()):
    _low_sample_desc = (
        f"échantillon de saison court ({sport.low_sample_label})" if sport.low_sample_label
        else "échantillon de saison court (peu de matchs joués)"
    )
    st.caption(
        f"◆ Losange = {_low_sample_desc}, affiché avec le même remplissage coloré que les ronds : "
        "sa moyenne peut être moins représentative d'une saison complète."
    )

# Mentions des joueurs retirés du graph (échantillons courts masqués, "NC") et des stats peu
# fiables choisies. Rien ne s'affiche pour la NBA (ni case, ni seuil NC, ni stat peu fiable).
_graph_notes = []
if n_low_sample_hidden:
    _graph_notes.append(
        f"{n_low_sample_hidden} joueur{'s' if n_low_sample_hidden > 1 else ''} à échantillon court "
        f"masqué{'s' if n_low_sample_hidden > 1 else ''} ({sport.low_sample_label}), présents "
        "dans le tableau détaillé."
    )
if n_nc_hidden:
    _graph_notes.append(
        f"{n_nc_hidden} joueur{'s' if n_nc_hidden > 1 else ''} NC (non classé{'s' if n_nc_hidden > 1 else ''} : "
        f"{_nc_txt}) non affiché{'s' if n_nc_hidden > 1 else ''}."
    )
_unreliable = [metrics[k].label for k in dict.fromkeys((x_key, y_key, color_key, size_key))
               if k in metrics and metrics[k].unreliable]
if _unreliable:
    _graph_notes.append(
        f"{', '.join(_unreliable)} : {UNRELIABLE_TXT} (événements rares, écarts entre joueurs "
        "en bonne partie dus au hasard ; voir la méthodologie)."
    )
for _note in _graph_notes:
    st.caption(_note)

with st.expander("Sources des données et méthodologie", expanded=False):
    st.caption(data_sources_caption)
    if playoff_stats_caveat:
        st.caption(playoff_stats_caveat)

def _detail_table():
    """Tableau détaillé d'un sport qui le décrit (sport.detail_lead_columns, rugby) : tous les
    joueurs des filtres, échantillons courts compris (table_base_df). Tri par
    sport.detail_sort_columns (rugby : nom de famille, prénom, puis saison en mode "Toutes les
    saisons"), échantillons courts mêlés aux autres ; sinon échantillons courts après les autres,
    puis sur Y (les NC en dernier). Colonnes renommées, colonne "Saison"
    en mode "Toutes les saisons", pourcentages en "78 % (52/67)" ou "NC". Renvoie un Styler :
    nombres affichés avec une décimale et une virgule (french_format), le tri au clic restant
    numérique."""
    lead, tail = dict(sport.detail_lead_columns), sport.detail_tail_columns or {}
    if is_all_seasons:  # "Saison" juste après le nom du joueur
        _items = list(lead.items())
        lead = dict(_items[:1] + [("season", "Saison")] + _items[1:])
    metric_cols = list(dict.fromkeys(
        [x_key, y_key] + ([color_key] if color_key in metrics else [])
    ))
    base = table_base_df.copy()
    base["_sort"] = base[y_key].mask(nc_mask(base, y_key))
    base["_low"] = base["low_sample_size"].fillna(False).astype(bool) if "low_sample_size" in base.columns else False
    if sport.detail_sort_columns:
        sort_cols = sport.detail_sort_columns + (["season"] if is_all_seasons else [])
        base = base.sort_values(
            sort_cols, na_position="last",
            # Sans accents ni casse, même règle que les autres listes (data_sources.base.sort_key) :
            # "Écoiffier" avec les E, "le Brun" avec les L.
            key=lambda col: col.map(sort_key) if col.name != "season" else col,
        )
    else:
        base = base.sort_values(["_low", "_sort"], ascending=[True, False], na_position="last")
    out = base[[c for c in lead if c in base.columns]].rename(columns=lead)
    number_formats = {}
    for k in metric_cols:
        m = metrics[k]
        if m.made_col is not None:
            out[m.label] = [
                (lambda t: "NC" if t is None or t.startswith("NC") else t)(format_metric(r, k))
                for _, r in base.iterrows()
            ]
        elif sport.french_format and m.fmt.endswith("%"):
            out[m.label] = [format_metric(r, k) for _, r in base.iterrows()]
        else:
            out[m.label] = base[k]
            number_formats[m.label] = "{:.1f}" if m.fmt.endswith("1f") else "{:.0f}"
    for c, header in tail.items():
        if c in base.columns and c not in metric_cols:
            out[header] = base[c]
            if pd.api.types.is_numeric_dtype(base[c]):
                number_formats[header] = "{:.0f}"
    for c, header in lead.items():
        if c in base.columns and pd.api.types.is_float_dtype(base[c]):
            number_formats[header] = "{:.0f}"
    if "low_sample_size" in base.columns:
        out["Échantillon"] = base["low_sample_size"].map({True: "court", False: "normal"})
    out = out.reset_index(drop=True)
    return out.style.format(
        number_formats, decimal="," if sport.french_format else ".", thousands=None, na_rep="",
    )


with st.expander("Voir les données détaillées"):
    if sport.detail_lead_columns:
        if n_missing_xy:
            st.caption(f"{_players(n_missing_xy)} sans valeur pour {_missing_labels} (aucune "
                       f"tentative ou donnée inconnue) : absent{'s' if n_missing_xy > 1 else ''} "
                       "du graph et du tableau.")
        st.dataframe(_detail_table(), width="stretch", hide_index=True)
    else:
        display_cols = ["player", "team"] + sorted(set([x_key, y_key] + ([color_key] if color_key in metrics else [])))
        if symbol_key:
            display_cols += [c for c in ("games_played", symbol_key) if c not in display_cols]
        st.dataframe(
            plot_df[display_cols].sort_values(y_key, ascending=False).reset_index(drop=True),
            width="stretch",  # voir commentaire ci-dessus (expander méthodologie)
        )

# --------------------------------------------------------------------------
# Bandeau "classement des équipes" — remplace l'ancien classement par valeur ajoutée (retiré
# avec la fonctionnalité salaire attendu/valeur ajoutée, voir METHODOLOGY.md). Basé sur de
# VRAIES stats d'équipe (sport.get_team_ranking, endpoint nba_api LeagueDashTeamStats), pas sur
# une moyenne des joueurs actuellement affichés/filtrés dans le scatter plot ci-dessus — ses deux
# sélecteurs (stat de classement, saison régulière/playoffs) sont donc volontairement
# indépendants de ceux du scatter plot, avec leurs propres widgets.
# --------------------------------------------------------------------------
# Sport sans classement d'équipes (rugby, en attendant l'Elo du plan « Après la V1 ») : section
# masquée plutôt qu'un titre suivi d'un message.
if sport.get_team_ranking is not None and sport.team_ranking_metrics:
    st.markdown("---")
    st.subheader("Classement des équipes")
    ranking_metrics = sport.team_ranking_metrics
    ranking_metric_keys = list(ranking_metrics.keys())

    if is_all_seasons:
        ranking_col1, ranking_col2, ranking_col3 = st.columns([2, 1, 1])
    else:
        ranking_col1, ranking_col2 = st.columns([2, 1])

    with ranking_col1:
        ranking_metric_key = st.selectbox(
            "Classer les équipes par",
            options=ranking_metric_keys,
            format_func=lambda k: f"{ranking_metrics[k].label}  ·  {ranking_metrics[k].category}",
            index=ranking_metric_keys.index("pts_per_game") if "pts_per_game" in ranking_metric_keys else 0,
            key="team_ranking_metric",
        )
    with ranking_col2:
        ranking_period_label = st.selectbox(
            "Saison régulière / Playoffs",
            options=["Saison régulière", "Playoffs uniquement"],
            index=0,
            key="team_ranking_period",
            help=(
                "Indépendant du réglage \"Statistiques utilisées\" du scatter plot ci-dessus : ce "
                "bandeau a son propre mode. Une équipe non qualifiée en playoffs n'apparaît "
                "simplement pas dans ce cas."
            ),
        )
    ranking_period = "playoffs" if ranking_period_label == "Playoffs uniquement" else "regular"

    # Mode "Toutes les saisons" choisi plus haut : `season` ne désigne aucune saison précise, donc
    # ce bandeau reste sur UNE saison à la fois (pas de cumul multi-saisons ici) et propose son
    # propre sélecteur, par défaut la même saison que _default_season plus haut.
    if is_all_seasons:
        with ranking_col3:
            ranking_season = st.selectbox(
                "Saison classée",
                options=sport.seasons,
                index=sport.seasons.index(_default_season) if _default_season in sport.seasons else 0,
                key="team_ranking_season",
            )
    else:
        ranking_season = season

    try:
        team_ranking_df = load_team_ranking(sport.key, ranking_season, ranking_period)
    except Exception as exc:
        team_ranking_df = None
        st.warning(f"Classement des équipes indisponible pour {ranking_season} : {exc}")

    if team_ranking_df is not None:
        ranking_meta = ranking_metrics[ranking_metric_key]
        ranked = team_ranking_df.dropna(subset=[ranking_metric_key]).sort_values(
            ranking_metric_key, ascending=False
        )
        if ranked.empty:
            st.info(f"Aucune équipe n'a de valeur disponible pour « {ranking_meta.label} » sur {ranking_season}.")
        else:
            bar_colors = ["#FFD700" if champ else "#4C78A8" for champ in ranked["champion"]]
            fig_ranking = go.Figure(
                go.Bar(
                    x=ranked["team"],
                    y=ranked[ranking_metric_key],
                    marker_color=bar_colors,
                    text=ranked["champion"].map(lambda c: "Champion" if c else ""),
                    textposition="outside",
                    hovertemplate=f"<b>%{{x}}</b><br>{ranking_meta.label} : %{{y:{ranking_meta.fmt}}}<extra></extra>",
                )
            )
            fig_ranking.update_layout(
                xaxis_title=None,
                yaxis_title=ranking_meta.label,
                template="plotly_white",
                height=420,
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_ranking, width='stretch')
            st.caption(
                f"En doré : équipe championne NBA de la saison {ranking_season} (résultat sportif réel, "
                "affiché quelle que soit la stat choisie ci-dessus)."
            )
