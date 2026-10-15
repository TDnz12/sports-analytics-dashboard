"""
Radar de comparaison de joueurs — page séparée du dashboard principal (Dashboard.py, qui ne change
pas de comportement), voir la proposition validée. Page Streamlit indépendante (système
multi-page natif basé sur le dossier pages/ à côté de Dashboard.py) : exécutée du début à la fin à
chaque interaction comme n'importe quel script Streamlit, mais partage st.session_state avec
Dashboard.py — c'est ce qui permet au bouton "Voir le profil radar" de la sidebar principale de
pré-sélectionner un joueur ici via st.switch_page().

Duplique volontairement quelques petits éléments de Dashboard.py (bloc CSS de densité, fonction de
chargement mise en cache, dict des libellés de période) plutôt que de les importer depuis
Dashboard.py : un fichier de pages/ est un script Streamlit à part entière, pas un module — l'importer
depuis Dashboard.py ré-exécuterait tout Dashboard.py (set_page_config compris). La duplication reste petite
et sans logique métier (celle-ci vit dans data_sources/, réutilisée telle quelle ici).

Plusieurs sports (lot 6 du rugby) : sélecteurs Sport puis Compétition, comme le Dashboard. Par
défaut, la page reprend le sport et la compétition choisis en dernier, ici ou sur le Dashboard
(clés de session selected_sport et selected_competition, non liées à un widget), sinon la NBA ;
de même pour la saison (selected_season, partagée aussi avec Effectifs). Les réglages propres au sport (axes selon les postes, carte,
colonnes hors radar, notes) sont des champs optionnels de SportConfig ; absents, rendu NBA
historique.
"""

from __future__ import annotations

import html
import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_sources import SPORTS
from data_sources.base import ALL_SEASONS, incomplete_data_warning, shared_season

st.set_page_config(page_title="Radar de comparaison · Sports Analytics", layout="wide")

# Même bloc de densité que Dashboard.py (voir son commentaire d'origine) — dupliqué ici pour que cette
# page ait la même respiration visuelle que le dashboard principal, sans dépendre de Dashboard.py.
st.markdown(
    """
    <style>
    /* Même réduction de la barre d'outils Streamlit tout en haut + de stSidebarHeader (rangée du
       bouton replier la sidebar) que Dashboard.py -- voir son commentaire d'origine pour le
       détail (root cause min-height, trouvée en inspectant le DOM réel, pas devinée) et le
       pourquoi de chaque valeur. */
    header[data-testid="stHeader"] {
        height: 2.25rem !important;
        min-height: 2.25rem !important;
    }
    div[data-testid="stSidebarHeader"] {
        height: 2.25rem !important;
        min-height: 0 !important;
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
    }
    /* Titre déplacé dans stLogoSpacer -- voir le commentaire d'origine dans Dashboard.py.
       st.sidebar.title() plus bas retiré en conséquence. */
    div[data-testid="stLogoSpacer"] {
        width: auto !important;
        display: flex;
        align-items: center;
    }
    div[data-testid="stLogoSpacer"]::before {
        content: "Radar de comparaison";
        font-weight: 700;
        font-size: 1rem;
        white-space: nowrap;
    }
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
    div[data-testid="stSidebarNav"] {
        padding-top: 0.2rem;
    }
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
    /* Espacement resserré, voir le commentaire d'origine dans Dashboard.py. */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stElementContainer"] {
        margin-bottom: 0.1rem !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        margin-top: 0.4rem !important;
        margin-bottom: 0.4rem !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    section[data-testid="stSidebar"] hr {
        margin: 1rem 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Titre retiré d'ici : fusionné dans la rangée du bouton replier la sidebar tout en haut (voir le
# commentaire CSS de stLogoSpacer plus haut).

# Pré-sélection déposée par Dashboard.py (bouton "Voir le profil radar") — pop() pour ne
# pré-sélectionner qu'une fois. radar_preselect_player : valeur de player_key_col (nom en NBA,
# identifiant en rugby) ; radar_preselect_label : nom affiché, pour les messages.
preselected_player = st.session_state.pop("radar_preselect_player", None)
preselected_season = st.session_state.pop("radar_preselect_season", None)
preselected_label = st.session_state.pop("radar_preselect_label", None) or preselected_player
preselected_sport = st.session_state.pop("radar_preselect_sport", None)
preselected_competition = st.session_state.pop("radar_preselect_competition", None)
preselected_period = st.session_state.pop("radar_preselect_period", None)

# Sport et compétition partagés avec le Dashboard par des clés de session NON liées à un widget
# (selected_sport, selected_competition), écrites à chaque run par chaque page : Streamlit efface
# l'état des widgets de la page qu'on quitte (radar_sport ici, main_sport sur le Dashboard), qui ne
# peut donc pas servir à passer d'une page à l'autre. current_page : page du run précédent ; à
# l'arrivée depuis une autre page, le sélecteur est réaligné sur la clé partagée, même si son
# ancien état a survécu. Ordre : présélection du bouton du Dashboard, clé partagée, NBA. Valeur
# écrite dans session_state avant la création du widget (key=, sans index=), même principe que
# "Saison" plus bas.
sport_keys = list(SPORTS.keys())
_entering_page = st.session_state.get("current_page") != "radar"
st.session_state["current_page"] = "radar"


def _reset_season() -> None:
    # Changement de sport ou de compétition : saison remise au défaut du nouveau choix, comme le
    # Dashboard (sinon "2025-26", valide en rugby et en NBA, serait gardée en passant de l'un à
    # l'autre, alors que la NBA s'ouvre sur "2024-25").
    st.session_state.pop("radar_season", None)


def _sync_from_shared(widget_key: str, shared, valid: list, default, forced: bool = False) -> None:
    """Valeur initiale d'un sélecteur partagé entre pages, écrite avant sa création : `shared`
    (présélection ou clé partagée) à l'arrivée sur la page, si `forced` (présélection), ou si la
    valeur du widget n'est plus valide ; sinon `default`. Saison remise au défaut si une valeur
    déjà là est remplacée."""
    current = st.session_state.get(widget_key)
    if current in valid and not ((_entering_page or forced) and shared in valid and shared != current):
        return
    new = shared if shared in valid else default
    if current is not None and current != new:
        _reset_season()
    st.session_state[widget_key] = new


_sync_from_shared(
    "radar_sport", preselected_sport if preselected_sport in SPORTS else st.session_state.get("selected_sport"),
    sport_keys, "nba", forced=preselected_sport in SPORTS,
)
sport_key = st.sidebar.selectbox(
    "Sport", options=sport_keys,
    format_func=lambda k: SPORTS[k].label if SPORTS[k].available else f"{SPORTS[k].label} (bientôt disponible)",
    key="radar_sport", on_change=_reset_season,
)
st.session_state["selected_sport"] = sport_key
sport = SPORTS[sport_key]
if not sport.radar_axes or sport.compute_radar_scores is None:
    st.title("Radar de comparaison")
    st.info("Le radar de comparaison n'est pas encore disponible pour ce sport.")
    st.stop()

# Compétition (rugby) : même ordre de priorité que le sport (selected_competition partagée).
competition = None
if sport.competitions:
    _competitions = {c.key: c for c in sport.competitions}
    _forced = preselected_competition in _competitions
    _sync_from_shared(
        "radar_competition",
        preselected_competition if _forced else st.session_state.get("selected_competition"),
        list(_competitions), next(k for k, c in _competitions.items() if c.available), forced=_forced,
    )
    competition = _competitions[st.sidebar.selectbox(
        "Compétition", options=list(_competitions),
        format_func=lambda k: _competitions[k].label if _competitions[k].available
        else f"{_competitions[k].label} (bientôt disponible)",
        key="radar_competition", on_change=_reset_season,
    )]
    st.session_state["selected_competition"] = competition.key
    if not competition.available:
        st.title(f"Radar de comparaison · {competition.label}")
        st.info(
            f"{competition.label} arrive dans une prochaine version. Compétitions disponibles : "
            + ", ".join(f"**{c.label}**" for c in sport.competitions if c.available) + "."
        )
        st.stop()
competition_key = competition.key if competition else None
seasons = competition.seasons if competition else sport.seasons

# Même dict que STATS_PERIOD_OPTIONS dans Dashboard.py (dupliqué, voir docstring du module et son
# commentaire sur le retrait du mode "regular_playoffs") : reste cohérent avec ce que "les stats"
# veulent dire ailleurs dans l'app -- ordre et défaut (premier élément) à resynchroniser à la main
# si Dashboard.py change encore. Un autre sport fournit ses périodes (sport.stats_periods).
STATS_PERIOD_OPTIONS = sport.stats_periods or {
    "Saison régulière": "regular",
    "Playoffs uniquement": "playoffs",
}


# key= (pas index=) pour que le choix de l'utilisateur survive aux reruns suivants : passer un
# index recalculé à chaque script (dérivé de preselected_season, qui redevient None après le
# pop() ci-dessus) sans clé stable ferait considérer par Streamlit qu'il s'agit d'un widget
# différent à chaque run où cet index change -- perdant silencieusement la sélection de
# l'utilisateur au moindre autre widget touché ensuite (repéré en testant : la saison et le
# joueur A revenaient à leur valeur par défaut dès qu'on changeait la période, par exemple). La
# pré-sélection n'est donc écrite dans session_state qu'UNE fois, si la clé n'existe pas déjà.
# "2024-25" par défaut (pas la saison la plus récente) : même raison temporaire que Dashboard.py
# (dataset Kaggle ratin21 pas encore à jour pour 2025-26, voir son commentaire) -- le radar
# n'affiche pas le salaire directement, mais reste sur la même saison par défaut que le reste de
# l'app pour la cohérence. Sans incidence sur les axes du radar eux-mêmes (aucun n'est dérivé du
# salaire). Défaut repris de sport.default_season (NBA : "2024-25"), sinon la plus récente. Saison
# revérifiée à chaque run : après un changement de sport ou de compétition, elle peut ne plus
# faire partie des options ("2024-25" contre "2026"), ce qui ferait lever une erreur au widget.
# Saison partagée avec le Dashboard et Effectifs (selected_season, voir
# data_sources.base.shared_season) : reprise à l'arrivée sur la page, après la présélection du
# bouton du Dashboard. "Toutes les saisons" (absent ici) reste la saison partagée tant que la
# saison n'est pas changée sur cette page.
_default_season = sport.default_season if sport.default_season in seasons else seasons[0]
_shared_season = shared_season(st.session_state, sport.key, competition_key)


def _share_season(sport_key: str, competition_key: str | None) -> None:
    # Saison changée ici : elle remplace aussi un "Toutes les saisons" venu du Dashboard.
    st.session_state["selected_season"] = (sport_key, competition_key, st.session_state["radar_season"])


if preselected_season in seasons:
    st.session_state["radar_season"] = preselected_season
elif _entering_page and _shared_season in seasons:
    st.session_state["radar_season"] = _shared_season
elif st.session_state.get("radar_season") not in seasons:
    st.session_state["radar_season"] = _default_season
season = st.sidebar.selectbox("Saison", options=seasons, key="radar_season",
                              on_change=_share_season, args=(sport.key, competition_key))
if _shared_season != ALL_SEASONS:
    st.session_state["selected_season"] = (sport.key, competition_key, season)
# Période : key= pour la même raison que la saison (présélection possible depuis le Dashboard en
# rugby), revérifiée de même au changement de sport.
_period_labels = list(STATS_PERIOD_OPTIONS.keys())
_preselected_period_label = next(
    (lbl for lbl, p in STATS_PERIOD_OPTIONS.items() if p == preselected_period), None)
if _preselected_period_label:
    st.session_state["radar_period"] = _preselected_period_label
elif st.session_state.get("radar_period") not in _period_labels:
    st.session_state["radar_period"] = _period_labels[0]
stats_period_label = st.sidebar.selectbox("Statistiques utilisées", options=_period_labels, key="radar_period")
stats_period = STATS_PERIOD_OPTIONS[stats_period_label]
# Période après la saison dans les textes : entre parenthèses, sauf si son libellé en contient déjà
# (rugby : "Saison complète (phases finales incluses)"), alors séparée par un point médian.
period_txt = f"· {stats_period_label}" if "(" in stats_period_label else f"({stats_period_label})"


# La compétition fait partie de la clé de cache (None pour la NBA, dont get_player_stats ne reçoit
# alors aucun argument competition), même principe que Dashboard.py. Texte du chargement propre au
# sport (sport.loading_label), d'où st.cache_data appliqué ici plutôt qu'en décorateur.
def _get_player_stats(sport_key: str, competition_key: str | None, season: str, period: str) -> pd.DataFrame:
    kwargs = {"competition": competition_key} if competition_key else {}
    return SPORTS[sport_key].get_player_stats(season, force_refresh=False, period=period, **kwargs)


load_data = st.cache_data(
    show_spinner=sport.loading_label or "Chargement des données NBA (nba_api + Kaggle)..."
)(_get_player_stats)

try:
    df = load_data(sport.key, competition_key, season, stats_period)
except Exception as exc:
    st.error(f"Impossible de charger les données pour {season} : {exc}")
    st.stop()
if (msg := incomplete_data_warning(df, season)):
    st.warning(msg)

if df.empty:
    st.warning(f"Aucune donnée disponible pour {season}.")
    st.stop()

# period=stats_period : la population de référence du z-score/percentile (voir docstring de
# nba.compute_radar_scores) doit utiliser un seuil "échantillon court" adapté à la période --
# 15 matchs est structurellement intenable en playoffs (même correction que le badge du scatter
# principal, voir Dashboard.py/PLAYOFF_LOW_SAMPLE_THRESHOLD_CAVEAT).
df = sport.compute_radar_scores(
    df, period=stats_period, **({"competition": competition_key} if competition_key else {})
)

# Joueur identifié par key_col (nom en NBA ; identifiant en rugby, pour les homonymes), affiché
# par label_col.
label_col = sport.player_label_col or "player"
key_col = sport.player_key_col or label_col
labels = df.drop_duplicates(key_col).set_index(key_col, drop=False)[label_col]

# Un joueur sans aucun match sur la période (ex: n'a pas fait les playoffs) aurait un radar
# entièrement vide — exclu de la liste plutôt que proposé pour un résultat vide/trompeur. De même
# pour un joueur sans poste (radar_eligible, rugby : "Indéterminé") : ni axes ni référence.
eligible_mask = df["games_played"].fillna(0) > 0
if "radar_eligible" in df.columns:
    eligible_mask &= df["radar_eligible"]
eligible = df[eligible_mask]
if key_col == label_col:
    player_options = sorted(eligible[key_col].dropna().unique().tolist())
else:
    player_options = sorted(eligible[key_col].dropna().unique().tolist(), key=lambda k: labels[k])


# Libellé d'un joueur dans la liste : son nom, et son poste quand le sport a un identifiant
# distinct du nom (rugby : "Nom (Club) · Pilier (banc)").
if key_col != label_col and "position_label" in df.columns:
    _position_labels = df.drop_duplicates(key_col).set_index(key_col)["position_label"]
    option_labels = {k: f"{labels[k]} · {_position_labels[k]}" for k in player_options}
else:
    option_labels = {}


def _option_label(key) -> str:
    return option_labels.get(key, labels.get(key, key) if key_col != label_col else key)


if not player_options:
    st.warning(f"Aucun joueur avec des données exploitables pour {season} {period_txt}.")
    st.stop()

MAX_PLAYERS = 4

# Même raison que pour "Saison" ci-dessus (key= plutôt qu'index= recalculé à chaque run) --
# avec en plus une validité à revérifier à CHAQUE run (pas seulement à la création) : changer de
# saison/période change player_options, et un joueur déjà sélectionné peut ne plus en faire
# partie (absent de la nouvelle saison/période) -- st.multiselect lève une erreur si une valeur
# de key= n'est pas dans options, d'où ce filtrage explicite. Repli sur le premier joueur
# seulement si le filtrage a tout retiré : une sélection vidée à la main par l'utilisateur reste
# vide (message plus bas), sinon le joueur retiré reviendrait aussitôt. Une présélection du
# Dashboard remplace la sélection en cours (changement de sport compris).
if preselected_player in player_options:
    st.session_state["radar_players"] = [preselected_player]
elif "radar_players" not in st.session_state:
    st.session_state["radar_players"] = [player_options[0]]
else:
    kept = [p for p in st.session_state["radar_players"] if p in player_options]
    if kept != st.session_state["radar_players"]:
        st.session_state["radar_players"] = kept or [player_options[0]]
players = st.sidebar.multiselect(
    f"Joueurs (1 à {MAX_PLAYERS})", options=player_options, max_selections=MAX_PLAYERS, key="radar_players",
    format_func=_option_label,
)

if preselected_player and preselected_player not in player_options:
    _no_position = (
        "radar_eligible" in df.columns
        and not df.loc[df[key_col] == preselected_player, "radar_eligible"].any()
        and (df[key_col] == preselected_player).any()
    )
    if _no_position:
        st.info(
            f"**{preselected_label}** n'a pas de poste déterminé (remplaçant jamais titulaire, "
            "maillot 19 à 23) : pas de radar possible, faute de joueurs de référence."
        )
    else:
        st.info(
            f"**{preselected_label}** n'a pas de données exploitables pour {season} "
            f"{period_txt} : sélectionne une autre saison ou un autre joueur."
        )

st.title(" · ".join(["Radar de comparaison"] + ([competition.label] if competition else []) + [season]))

# Toggle Indice / Centile (inspiré de Data'Scout) : les deux lisent les colonnes déjà calculées
# par compute_radar_scores (radar_<key>_score / radar_<key>_percentile), même référence (poste +
# saison/période + MIN_GAMES_FOR_FIT) dans les deux cas -- seule la façon de lire l'écart à cette
# référence change (écart-type mis à l'échelle vs rang direct).
display_mode = st.radio(
    "Mode d'affichage", options=["Indice", "Centile"], index=0, horizontal=True,
    help=(
        "Indice : z-score par poste clippé à ±3 écarts-types, mis à l'échelle 0-100 (50 = "
        "moyenne du poste). Centile : rang percentile réel dans la même population "
        "(poste + saison/période + seuil de matchs joués) -- ex. 90 = ce joueur fait mieux que "
        "90% des joueurs de référence à son poste sur cet axe."
    ),
)
score_suffix = "_score" if display_mode == "Indice" else "_percentile"
score_unit = "/100" if display_mode == "Indice" else "ᵉ centile"

# Une couleur par position dans la sélection (bleu, orange, vert, violet). Remplissage à 10 %
# d'opacité (25 % quand il n'y avait que deux joueurs) : à 3-4 formes superposées, un remplissage
# plus dense masquait les contours des autres joueurs.
PLAYER_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"]
FILL_OPACITY = 0.10


def _fill_color(hex_color: str) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{FILL_OPACITY})"


# Valeurs écrites à côté des points seulement jusqu'à 2 joueurs, décalées haut/bas par joueur : à
# 10 axes, deux joueurs avec des scores proches sur un même axe (repéré en rendu réel : ex. 66 vs
# 69) verraient sinon leurs deux labels se chevaucher exactement au même point. Au-delà de 2
# joueurs, plus aucun décalage ne suffit : les valeurs restent lisibles au survol.
MAX_PLAYERS_WITH_TEXT = 2
# Position radiale des cercles creux "aucune tentative" : près du centre, un cran de plus par
# joueur (4, 10, 16, 22), assez espacés pour ne pas se chevaucher quand plusieurs joueurs n'ont
# aucune tentative sur le même axe.
NO_ATTEMPT_R_START = 4
NO_ATTEMPT_R_STEP = 6
PLAYER_TEXT_POSITIONS = ["top center", "bottom center"]


def _player_row(player_key) -> pd.Series | None:
    row = df[df[key_col] == player_key]
    if row.empty:
        return None
    return row.iloc[0]


# Petites cartes par joueur (esprit Data'Scout) au-dessus du radar, dans la couleur qui lui est
# associée sur le graph -- seule la bordure/l'accent est colorée, le texte reste dans la couleur
# héritée du thème Streamlit (currentColor) pour rester lisible en clair comme en sombre, sans
# pouvoir détecter le thème réel du visiteur côté Python (voir plus bas pour la même contrainte
# sur le fond du radar). Lignes en plus selon le sport (sport.radar_card_lines, rugby : poste,
# titularisations, cartons, échantillon court), aucune en NBA.
def _player_card(column, player_key, color: str) -> None:
    row = _player_row(player_key)
    player_name = row[label_col] if row is not None else player_key
    extra = ""
    if row is not None and sport.radar_card_lines:
        extra = "".join(
            f'<div style="opacity: 0.7; font-size: 0.85rem;">{html.escape(line, quote=False)}</div>'
            for line in sport.radar_card_lines(row)
        )
    with column:
        games = row.get("games_played") if row is not None else None
        if row is not None and pd.notna(games):
            n_games = int(round(games))
            games_txt = f"{n_games} match" if n_games < 2 else f"{n_games} matchs"
        else:
            games_txt = "n.d."
        st.markdown(
            f"""<div style="border-left: 4px solid {color}; padding: 0.3rem 0.9rem;">
            <div style="font-weight: 600; font-size: 1.05rem;">{player_name}</div>
            <div style="opacity: 0.7; font-size: 0.85rem;">{season} {period_txt} · {games_txt}</div>{extra}
            </div>""",
            unsafe_allow_html=True,
        )


if players:
    for column, player_key, color in zip(st.columns(len(players)), players, PLAYER_COLORS):
        _player_card(column, player_key, color)

# Axes selon les postes des joueurs comparés (sport.radar_axes_for, rugby : intersection des axes
# de ces postes), avec leurs notes ; sinon les mêmes axes pour tout le monde (NBA).
selected_positions = [
    row["position_group"] for row in (_player_row(p) for p in players)
    if row is not None and "position_group" in row
]
if sport.radar_axes_for:
    axes, axes_notes = sport.radar_axes_for(selected_positions)
else:
    axes, axes_notes = sport.radar_axes, []

# Marge invisible ajoutée à la fin de chaque cellule d'axe du tableau récap. Streamlit ajuste la
# largeur des colonnes (width="content") en mesurant leur texte, mais dans le navigateur cette
# mesure sous-estime de quelques pixels les valeurs les plus longues ("14.7  ·  63/100" rogné).
# Un espace de chiffre (U+2007, environ 7 px) suivi d'un espace insécable (U+00A0, environ 3 px)
# entre dans la mesure sans rien afficher : chaque colonne s'élargit d'environ 10 px. Des espaces
# insécables plutôt qu'ordinaires, pour qu'un espace de fin ne puisse pas être retiré ou fusionné.
RECAP_CELL_END_MARGIN = "\u2007\u00A0"


def _format_raw(axis: dict, row: pd.Series) -> str:
    """Valeur réelle d'un axe au format de RADAR_AXES["fmt"] (les pourcentages nba_api sont des
    fractions, 0.152 pour 15,2 %), suivie du nombre de tentatives entre parenthèses pour les axes
    de tir ("88.7% (669 tent.)"), ou seulement "0 tent." sans aucune tentative (le pourcentage
    n'a alors pas de sens). "n.d." si manquante. Même texte au survol et dans le tableau.
    Variante rugby : "fmt" est une fonction (virgule décimale), et un axe avec "made_col" affiche
    réussis / tentatives ("84 % (16/19)", ou "aucune tentative")."""
    value = row.get(axis["stat_col"])
    attempts = row.get(axis["attempts_col"]) if "attempts_col" in axis else None
    if attempts is not None and not pd.isna(attempts) and attempts == 0:
        return "aucune tentative" if "made_col" in axis else "0 tent."
    if pd.isna(value):
        return "n.d."
    fmt = axis.get("fmt", "{:.1f}")
    text = fmt(value) if callable(fmt) else fmt.format(value)
    if attempts is None or pd.isna(attempts):
        return text
    if "made_col" in axis:
        return f"{text} ({row.get(axis['made_col']):.0f}/{attempts:.0f})"
    return f"{text} ({attempts:.0f} tent.)"


def _empty_axis_reason(axis: dict, row: pd.Series) -> str:
    """Raison affichée au survol d'un axe vide : aucune tentative, ou volume sous le minimum par
    match (nba.MIN_FG3A_PER_GAME / MIN_FTA_PER_GAME) pour un axe de tir, ou sous le minimum de la
    saison ("min_attempts", rugby : seuil NC)."""
    attempts = row.get(axis["attempts_col"]) if "attempts_col" in axis else None
    if attempts is None or pd.isna(attempts):
        return "aucune donnée"
    if attempts == 0:
        return "aucune tentative"
    if "min_attempts" in axis:
        return (f"volume trop faible : {attempts:.0f} {axis['attempts_label']}, "
                f"minimum {axis['min_attempts']}")
    return f"volume trop faible ({attempts:.0f} tentatives en {row.get('games_played'):.0f} matchs)"


theta_labels = [a["label"] for a in axes]
# Description de chaque axe (clé "help" de RADAR_AXES) ajoutée au survol de ses points, coupée en
# lignes courtes : Plotly ne revient pas à la ligne tout seul dans une infobulle.
axis_help = ["<br>".join(textwrap.wrap(a.get("help", ""), 60)) for a in axes]

fig = go.Figure()
recap_rows = []

show_text = len(players) <= MAX_PLAYERS_WITH_TEXT
for i, player_key in enumerate(players):
    row = _player_row(player_key)
    if row is None:
        st.info(f"**{_option_label(player_key)}** ne correspond à aucune donnée pour {season} {period_txt}.")
        continue
    player_name = row[label_col]
    scores = [row.get(f"radar_{a['key']}{score_suffix}") for a in axes]
    # Axe sans valeur (ex. aucune tentative à 3 points) : point retiré du tracé plutôt que placé au
    # centre, où il se lirait comme un score de 0 ; le polygone relie les deux axes voisins par un
    # segment en tirets, et un cercle creux marque l'axe vide (voir plus bas). L'ordre des axes
    # reste fixé par categoryarray (voir angularaxis plus bas), même si le premier tracé n'a pas
    # tous les axes.
    kept = [k for k, s in enumerate(scores) if not pd.isna(s)]
    kept_closed = kept + kept[:1]
    # Valeur affichée directement à côté de chaque point, pas seulement au survol.
    point_labels = [f"{scores[k]:.0f}" for k in kept]
    # Valeur réelle de chaque axe, au même format que le tableau récap (PIE en %, TOV% estimé...).
    raw_labels = [_format_raw(a, row) for a in axes]
    hover_data = [[raw, help_txt] for raw, help_txt in zip(raw_labels, axis_help)]
    line_color = PLAYER_COLORS[i]
    group = f"joueur{i}"
    common = dict(legendgroup=group, showlegend=False, name=player_name)
    # Un joueur = plusieurs tracés regroupés (legendgroup : un clic sur la légende les masque tous),
    # repérés par `meta` pour les tests. Remplissage seul, sans contour : même polygone que les
    # points présents.
    fig.add_trace(go.Scatterpolar(
        r=[float(scores[k]) for k in kept_closed], theta=[theta_labels[k] for k in kept_closed],
        fill="toself", fillcolor=_fill_color(line_color), mode="lines", line=dict(width=0),
        hoverinfo="skip", meta="remplissage", **common,
    ))
    # Contour : trait plein entre deux axes voisins ; le segment qui enjambe un axe vide est en
    # tirets, pour ne pas se lire comme une vraie valeur sur cet axe. Tirets aussi épais que le
    # trait plein : plus fins, ils disparaissaient quand ils partent du centre (score de 0 sur
    # l'axe voisin, ex. Ben Simmons en Protection du ballon 2024-25).
    solid_r, solid_t, gap_r, gap_t = [], [], [], []
    for a, b in zip(kept_closed, kept_closed[1:]):
        rr, tt = (solid_r, solid_t) if (b - a) % len(axes) == 1 else (gap_r, gap_t)
        rr += [float(scores[a]), float(scores[b]), None]
        tt += [theta_labels[a], theta_labels[b], theta_labels[b]]
    fig.add_trace(go.Scatterpolar(
        r=solid_r, theta=solid_t, mode="lines", line=dict(color=line_color, width=2),
        connectgaps=False, hoverinfo="skip", meta="contour", **common,
    ))
    if gap_r:
        fig.add_trace(go.Scatterpolar(
            r=gap_r, theta=gap_t, mode="lines", line=dict(color=line_color, width=2, dash="dash"),
            connectgaps=False, hoverinfo="skip", meta="tirets", **common,
        ))
    # Points, valeurs écrites à côté et survol.
    fig.add_trace(go.Scatterpolar(
        r=[float(scores[k]) for k in kept], theta=[theta_labels[k] for k in kept],
        mode="markers+text" if show_text else "markers", text=point_labels,
        textposition=PLAYER_TEXT_POSITIONS[i % len(PLAYER_TEXT_POSITIONS)],
        textfont=dict(color=line_color, size=10), customdata=[hover_data[k] for k in kept],
        marker=dict(size=5, color=line_color), meta="points", **common,
        hovertemplate=(
            "<b>%{theta} : %{r:.0f}" + score_unit + "</b><br>Valeur réelle : %{customdata[0]}"
            "<br>%{customdata[1]}<extra>" + player_name + "</extra>"
        ),
    ))
    # Axe vide : petit cercle creux près du centre, sans texte, décalé de NO_ATTEMPT_R_STEP par
    # joueur pour que les cercles ne se chevauchent pas. Le survol en donne la raison.
    missing = [k for k in range(len(axes)) if k not in kept]
    if missing:
        fig.add_trace(go.Scatterpolar(
            r=[NO_ATTEMPT_R_START + NO_ATTEMPT_R_STEP * i] * len(missing),
            theta=[theta_labels[k] for k in missing], mode="markers",
            marker=dict(symbol="circle-open", size=8, color=line_color, line=dict(width=1.5)),
            customdata=[_empty_axis_reason(axes[k], row) for k in missing],
            hovertemplate="<b>%{theta}</b> : %{customdata}<extra>" + player_name + "</extra>",
            meta="sans_tentative", **common,
        ))
    # Entrée de légende seule (aucune donnée tracée) : garde l'icône d'avant, trait + point +
    # remplissage, que les tracés séparés ci-dessus n'ont plus individuellement.
    fig.add_trace(go.Scatterpolar(
        r=[None], theta=[theta_labels[0]], mode="lines+markers", fill="toself",
        fillcolor=_fill_color(line_color), line=dict(color=line_color, width=2),
        marker=dict(size=5, color=line_color), legendgroup=group, showlegend=True,
        name=player_name, hoverinfo="skip", meta="legende",
    ))
    recap_row = {"Joueur": player_name}
    for a, raw, score in zip(axes, raw_labels, scores):
        # Axe de tir vide (zéro tentative ou volume sous le seuil) : valeur réelle suivie de "NC"
        # (non classé) à la place du score, ex. "0.0% (4 tent.)  ·  NC" ou "0 tent.  ·  NC".
        # "—" reste réservé à une donnée réellement absente.
        if raw == "n.d.":
            cell = "n.d."
        elif pd.notna(score):
            cell = f"{raw}  ·  {score:.0f}{score_unit}"
        else:
            cell = f"{raw}  ·  " + ("NC" if "attempts_col" in a else "n.d.")
        recap_row[a["label"]] = cell + RECAP_CELL_END_MARGIN
    # Colonnes hors radar (rugby : axes retirés, essais, discipline, % au pied, cartons).
    if sport.radar_extra_columns:
        recap_row.update({
            col: text + RECAP_CELL_END_MARGIN
            for col, text in sport.radar_extra_columns(row, selected_positions).items()
        })
    recap_rows.append(recap_row)

if not fig.data:
    st.warning("Sélectionne au moins un joueur pour afficher le radar.")
    st.stop()

# Fond du polar : st.plotly_chart (theme="streamlit" par défaut) réécrit automatiquement
# paper_bgcolor/plot_bgcolor pour matcher le thème de l'app (clair/sombre selon le visiteur --
# c'est ce qui rend déjà le scatter plot principal sombre malgré son propre template="plotly_white",
# vérifié dans le bundle JS de Streamlit : PlotlyChart.*.js, fonction d'injection de thème). Mais
# CETTE injection ne couvre PAS layout.polar (contrairement à layout.ternary, qui lui est bien
# pris en charge) -- polar.bgcolor restait donc au blanc du template plotly_white, d'où le radar
# en fond blanc alors que tout le reste de l'app suit le thème. Fix : bgcolor transparent pour
# hériter du paper_bgcolor déjà correctement thémé par Streamlit, plutôt qu'une couleur fixe
# (qui serait fausse pour un visiteur en thème clair -- indétectable depuis ce code Python).
# Grille/texte de l'axe polaire : gris moyen choisi pour rester lisible sur fond clair ET sombre,
# Streamlit ne thémant pas non plus ces couleurs pour les charts polaires.
#
# Échelle radiale fixée de 0 à 100 : le cercle extérieur correspond exactement au score maximum.
# Réglages vérifiés sur un rendu réel (kaleido) à 10 axes, 2 et 4 joueurs, 1100 et 700 px de
# large : quand les valeurs sont écrites à côté des points (1-2 joueurs), le libellé "Scoring"
# chevauchait la valeur "100" du point juste en dessous, d'où un écart entre le cercle extérieur
# et les libellés d'axes (graduations invisibles, seul réglage Plotly qui les repousse), réduit
# au minimum quand les valeurs ne sont visibles qu'au survol ; marges latérales de 150 pour que
# "Protection du ballon" et "Interceptions" ne soient pas coupés à 700 px ; height=680 pour que
# "Efficacité (TS%)", en bas, reste dans le graphique. Légende ancrée en haut de la figure
# (yref="container") et marge du haut calculée pour contenir ses 2 lignes (4 joueurs sur écran
# étroit), l'écart et le libellé "Scoring" : ancrée juste au-dessus du radar, elle chevauchait
# "Scoring" dès qu'elle s'étendait jusqu'au centre. Revérifier visuellement si le nombre d'axes
# change.
POLAR_AXIS_COLOR = "#888888"
AXIS_LABEL_GAP = 12 if show_text else 2
LEGEND_HEIGHT = 50
fig.update_layout(
    polar=dict(
        bgcolor="rgba(0,0,0,0)",
        radialaxis=dict(
            visible=True, range=[0, 100], tickvals=[0, 20, 40, 60, 80, 100], ticksuffix="",
            gridcolor=POLAR_AXIS_COLOR, linecolor=POLAR_AXIS_COLOR, tickfont=dict(color=POLAR_AXIS_COLOR, size=9),
        ),
        angularaxis=dict(
            direction="clockwise", categoryorder="array", categoryarray=theta_labels,
            # Graduations invisibles mais longues : c'est le seul réglage Plotly qui éloigne les
            # libellés d'axes du cercle extérieur, pour laisser la place aux valeurs des points
            # à 100 (voir le commentaire au-dessus de POLAR_AXIS_COLOR).
            ticks="outside", ticklen=AXIS_LABEL_GAP, tickcolor="rgba(0,0,0,0)",
            gridcolor=POLAR_AXIS_COLOR, linecolor=POLAR_AXIS_COLOR, tickfont=dict(color=POLAR_AXIS_COLOR),
        ),
    ),
    paper_bgcolor="rgba(0,0,0,0)",
    height=680,
    legend=dict(orientation="h", yref="container", yanchor="top", y=1, xanchor="left", x=0),
    margin=dict(t=LEGEND_HEIGHT + 30 + AXIS_LABEL_GAP, b=60, l=150, r=150),
)
st.plotly_chart(fig, width="stretch")

# Début propre au sport (sport.radar_reference_caption, rugby : 10 postes et seuil de référence),
# fin commune selon le mode d'affichage.
_percent = "90 %" if sport.french_format else "90%"
st.caption(
    (sport.radar_reference_caption or (
        "Chaque axe est un z-score par poste (Intérieur / Ailier / Extérieur) : la position du "
        "joueur est mesurée par rapport aux autres joueurs de référence au même poste, pas à "
        "l'ensemble de la ligue."
    )) + (
        " Affiché ici mis à l'échelle 0-100 pour la lecture (clip à ±3 écarts-types) : 50 = dans "
        "la moyenne des joueurs à son poste sur cet axe."
        if display_mode == "Indice" else
        " Affiché ici en rang percentile direct (rang / effectif) dans la même population de "
        f"référence : 90 = ce joueur fait mieux que {_percent} des joueurs de référence à son poste."
    )
)

# Notes qui dépendent des joueurs comparés (axes retirés, peu d'axes en commun, effectif de
# référence de chaque poste), puis avertissements fixes du sport.
_notes = list(axes_notes)
if sport.radar_notes_fn:
    _notes += sport.radar_notes_fn(df, selected_positions)
for note in _notes + list(sport.radar_caveats or []):
    st.caption(note)

# Même caveat que PLAYOFF_LOW_SAMPLE_THRESHOLD_CAVEAT dans Dashboard.py (dupliqué, pas dans
# sport.radar_caveats car ce n'est pas propre à un axe -- ça concerne la population de référence
# du z-score/percentile dans son ensemble, voir compute_radar_scores(..., period=)) : visible
# uniquement en playoffs, même principe que les autres caveats conditionnels de l'app.
if stats_period == "playoffs":
    st.caption(
        " Note : population de référence (poste + saison) construite avec un seuil de 4 matchs "
        "minimum en playoffs (contre 15 en saison régulière) : 15 serait structurellement "
        "intenable ici (le maximum réellement jouable en playoffs tourne autour de 22-23 "
        "matchs), voir Dashboard.py pour la mesure d'impact complète."
    )

RECAP_PLAYER_WIDTH = 210
if recap_rows:
    _recap_title = "Valeurs brutes par axe" + (", puis hors radar" if sport.radar_extra_columns else "")
    with st.expander(f"{_recap_title} (valeur réelle  ·  {display_mode.lower()})", expanded=True):
        # Colonnes d'axes à la largeur de leur contenu (en-tête compris), comme un double-clic
        # sur le bord de colonne : il faut à la fois ne pas leur donner de largeur et afficher le
        # tableau en width="content", car en width="stretch" Streamlit élargit toute colonne
        # sans largeur fixe pour remplir la page. "Joueur" garde une largeur fixe et reste
        # épinglée, pour que les noms complets restent lisibles quand le tableau défile.
        st.dataframe(
            pd.DataFrame(recap_rows), width="content", hide_index=True,
            column_config={
                "Joueur": st.column_config.TextColumn(width=RECAP_PLAYER_WIDTH, pinned=True),
                **{a["label"]: st.column_config.TextColumn(help=a.get("help")) for a in axes},
                **{col: st.column_config.TextColumn(help=(sport.radar_extra_help or {}).get(col))
                   for col in pd.DataFrame(recap_rows).columns
                   if col != "Joueur" and col not in {a["label"] for a in axes}},
            },
        )
