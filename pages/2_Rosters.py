"""
Rosters — grille des 30 équipes NBA (logos cliquables), puis effectif de l'équipe choisie pour
la saison sélectionnée, une carte par joueur (photo + 2-3 stats clés). Page séparée du dashboard
principal (Dashboard.py, qui ne change pas de comportement), même convention que
pages/1_Radar_de_comparaison.py : script Streamlit à part entière (système multi-page natif
basé sur le dossier pages/), qui partage st.session_state avec les autres pages sans les
importer (voir la docstring de pages/1_Radar_de_comparaison.py pour le pourquoi).

v1 volontairement simple (proposition validée) : pas de hover-card, les stats sont affichées
EN DUR sous la photo plutôt qu'au survol -- on juge si l'interactivité vaut l'investissement une
fois cette version en place. Deux limites connues, acceptées pour cette v1 (pas de fallback
sophistiqué à construire maintenant) :
  - Photos manquantes sur le CDN NBA pour une partie des joueurs, surtout saisons anciennes
    (avant ~2000) -- affiché tel quel, sans image de remplacement (le navigateur montre une icône
    d'image cassée, pas une erreur Python : les logos/photos sont des balises <img> pointant
    directement vers le CDN, voir _img_html plus bas -- aucun appel réseau côté serveur).
  - Grille construite sur les 30 franchises ACTUELLES (voir nba.get_teams_static) : une saison
    ancienne où une franchise jouait sous un autre nom/ville (Seattle, Vancouver, New Jersey...)
    peut donc afficher un roster vide pour cette franchise-là cette année-là -- message explicite
    plutôt qu'une grille silencieusement incomplète.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_sources import SPORTS

st.set_page_config(page_title="Rosters — Sports Analytics", page_icon="👥", layout="wide")

# Même bloc de densité que Dashboard.py / pages/1_Radar_de_comparaison.py (dupliqué, voir leur
# commentaire d'origine) -- même respiration visuelle sur les trois pages.
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
        content: "👥 Rosters";
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

    /* Cadre de taille FIXE identique pour chaque logo/photo (largeur ET hauteur, pas de % ni de
       "stretch") + object-fit: contain : les fichiers logo du CDN NBA ont des ratios et des
       marges internes transparentes très différents d'une équipe à l'autre (ex. le logo des
       Bulls a beaucoup de vide autour du taureau, celui des Warriors remplit tout son cadre) --
       un simple st.image() à largeur "stretch" donnait donc un rendu visuellement inégal d'un
       logo à l'autre. object-fit: contain met chaque logo/photo à l'échelle DANS ce cadre sans
       le déformer ni le rogner, quelle que soit sa marge d'origine. Voir aussi le commentaire
       plus bas (pourquoi <img> en HTML brut plutôt que st.image ici) pour la seconde raison
       d'être de ces classes : une taille de cadre fixe et connue à l'avance, pas dépendante d'un
       calcul de mise en page du navigateur. */
    .roster-logo-box, .roster-photo-box {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        background: transparent;
    }
    .roster-logo-box { height: 110px; }
    /* Réduite de 200px à 140px (retour utilisateur : cartes joueur trop hautes) -- suffisant
       pour un portrait 1040x760 mis à l'échelle par object-fit: contain sans le rogner. */
    .roster-photo-box { height: 140px; }
    .roster-logo-box img, .roster-photo-box img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }

    /* Cases de la grille d'équipes de hauteur inégale (repéré en test) : le bouton sous le logo
       contient le nom complet de la franchise, qui tient sur 1 ligne pour certaines ("Miami
       Heat") et se retrouve sur 2 pour d'autres ("Oklahoma City Thunder"), ce qui allonge le
       bouton -- et donc tout le st.container(border=True) qui l'entoure -- d'une équipe à
       l'autre. min-height calé sur le pire cas (nom sur 2 lignes) rend tous les boutons, donc
       toutes les cases, à la même hauteur, que le nom tienne sur 1 ou 2 lignes.
       white-space: normal annule le nowrap par défaut de Streamlit (sinon le nom déborderait
       plutôt que de passer à la ligne). */
    div[data-testid="stButton"] button {
        min-height: 2.75rem;
        white-space: normal;
        line-height: 1.2;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Remet le scroll en haut de page à chaque rerun de cette page (changement d'équipe ou retour à
# la grille) : Streamlit ne réinitialise pas la position de scroll du navigateur après un rerun,
# donc revenir à la grille (plus courte que la page roster qu'on quitte) depuis un roster scrollé
# laissait le haut de la grille "coupé" -- on voyait le milieu de la nouvelle page, pas son début
# (repéré en test). st.iframe (iframe) est nécessaire ici : un <script> inséré via
# st.markdown(unsafe_allow_html=True) ne s'exécute pas dans Streamlit (le HTML est injecté en
# innerHTML, que les navigateurs n'exécutent jamais pour les balises <script>).
st.iframe(
    """
    <style>html, body { margin: 0; overflow: hidden; }</style>
    <script>
        const targets = window.parent.document.querySelectorAll(
            'section.main, [data-testid="stAppViewContainer"], [data-testid="stMain"]'
        );
        targets.forEach((el) => el.scrollTo({top: 0, behavior: 'instant'}));
        window.parent.scrollTo({top: 0, behavior: 'instant'});
    </script>
    """,
    height=1,
)

# Titre retiré d'ici : fusionné dans la rangée du bouton replier la sidebar tout en haut (voir le
# commentaire CSS de stLogoSpacer plus haut, dans le bloc de densité).

# MVP : NBA uniquement, même raison que pages/1_Radar_de_comparaison.py (pas de sélecteur de
# sport tant qu'un second sport n'a pas sa propre implémentation).
sport = SPORTS["nba"]
if sport.get_teams_static is None or sport.get_player_stats is None:
    st.title("👥 Rosters")
    st.info("Les rosters ne sont pas encore disponibles pour ce sport.")
    st.stop()

LOGO_URL_TEMPLATE = "https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"
HEADSHOT_URL_TEMPLATE = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"

teams_static = sorted(sport.get_teams_static(), key=lambda t: t["full_name"])


def _img_html(url: str, alt: str, box_class: str) -> str:
    # <img> en HTML brut (st.markdown) plutôt que st.image(..., width="stretch") : ce dernier
    # laisse le NAVIGATEUR calculer la largeur réelle après mise en page du conteneur parent --
    # un calcul qui, pour ~30 images montées d'un coup après un rerun complet (ex. retour depuis
    # la vue roster vers la grille), peut ne pas être terminé avant que Streamlit ne remplace le
    # DOM, laissant certaines images sans dimension résolue et donc jamais chargées (bug repéré
    # en test : seuls 1-2 logos sur 30 réapparaissaient après un aller-retour vers un roster,
    # reproduit à l'identique sur une saison récente ET une saison ancienne -- donc lié au rerun
    # lui-même, pas aux données de la saison, confirmé en comptant les éléments réellement émis
    # côté serveur avant/après, stable à 30 dans les deux cas -- le problème est bien côté
    # navigateur). Le cadre CSS à taille FIXE (.roster-logo-box/.roster-photo-box, voir plus haut)
    # + loading="eager"/decoding="async" évitent ce calcul différé : le navigateur connaît la
    # taille de la zone AVANT même de savoir si l'image a chargé, et démarre le chargement tout
    # de suite plutôt que d'attendre une passe de mise en page.
    return f'<div class="{box_class}"><img src="{url}" alt="{alt}" loading="eager" decoding="async"></div>'

# Saison : par défaut, s'aligne sur la saison actuellement affichée dans la sidebar principale de
# Dashboard.py (st.session_state["main_season"], partagé -- voir son commentaire) si elle est
# valide ici (une vraie saison, pas le mode combiné "Toutes les saisons" qui n'a pas d'équivalent
# sur cette page, voir la docstring du module). key= (pas index= recalculé) pour que le choix de
# l'utilisateur survive aux reruns suivants, même principe que radar_season dans la page radar.
_default_season = "2024-25" if "2024-25" in sport.seasons else sport.seasons[0]
if "rosters_season" not in st.session_state:
    _main_season = st.session_state.get("main_season")
    st.session_state["rosters_season"] = _main_season if _main_season in sport.seasons else _default_season
season = st.sidebar.selectbox("Saison", options=sport.seasons, key="rosters_season")


@st.cache_data(show_spinner="Chargement des données NBA (nba_api + Kaggle)...")
def load_data(sport_key: str, season: str) -> pd.DataFrame:
    return SPORTS[sport_key].get_player_stats(season, force_refresh=False, period="regular")


try:
    df = load_data(sport.key, season)
except Exception as exc:
    st.error(f"Impossible de charger les données pour {season} : {exc}")
    st.stop()

if df.empty:
    st.warning(f"Aucune donnée disponible pour {season}.")
    st.stop()


def _select_team(abbreviation: str) -> None:
    st.session_state["rosters_selected_team"] = abbreviation


def _back_to_grid() -> None:
    st.session_state["rosters_selected_team"] = None


selected_abbrev = st.session_state.get("rosters_selected_team")

if not selected_abbrev:
    st.title("👥 Rosters")
    st.caption(f"Choisis une équipe pour voir son effectif {season}.")

    N_COLS = 6
    cols = st.columns(N_COLS)
    for i, t in enumerate(teams_static):
        with cols[i % N_COLS]:
            with st.container(border=True):
                st.markdown(
                    _img_html(LOGO_URL_TEMPLATE.format(team_id=t["id"]), t["abbreviation"], "roster-logo-box"),
                    unsafe_allow_html=True,
                )
                st.button(
                    t["full_name"], key=f"team_btn_{t['abbreviation']}",
                    on_click=_select_team, args=(t["abbreviation"],),
                    width="stretch",
                )

else:
    team_meta = next((t for t in teams_static if t["abbreviation"] == selected_abbrev), None)
    team_label = team_meta["full_name"] if team_meta else selected_abbrev

    # Espace au-dessus du bouton : sans lui, ce bouton (premier élément affiché sur cette vue)
    # se retrouve collé contre la barre d'outils flottante de Streamlit (coupé visuellement en
    # haut de page, repéré en test) -- le padding-top réduit du bloc de densité plus haut ne
    # suffit pas à lui seul quand un bouton (pas un titre) est le tout premier élément.
    st.markdown("<div style='height: 0.75rem;'></div>", unsafe_allow_html=True)
    st.button("← Retour à la grille des équipes", on_click=_back_to_grid)
    st.title(f"👥 {team_label} — {season}")

    if team_meta:
        st.image(LOGO_URL_TEMPLATE.format(team_id=team_meta["id"]), width=100)

    roster_df = df[df["team"] == selected_abbrev].sort_values("player").reset_index(drop=True)

    if roster_df.empty:
        st.warning(
            f"Aucun joueur trouvé pour {team_label} en {season}. Si c'est une saison ancienne, "
            "cette franchise jouait peut-être sous un autre nom/ville à l'époque (voir la "
            "docstring de cette page pour le détail) -- limite connue de cette v1."
        )
    else:
        N_PLAYER_COLS = 5
        player_cols = st.columns(N_PLAYER_COLS)
        for i, row in roster_df.iterrows():
            with player_cols[i % N_PLAYER_COLS]:
                with st.container(border=True):
                    player_id = row.get("player_id")
                    player_name = row.get("player", "—")
                    if pd.notna(player_id):
                        # Même technique (<img> HTML + cadre fixe) que la grille de logos plus
                        # haut, par cohérence et par précaution : même pattern st.image(width=
                        # "stretch") suspecté pour le bug de logos qui disparaissent (voir
                        # _img_html) -- pas de bug signalé ici spécifiquement, mais autant éviter
                        # de laisser le même risque en place sur des cartes qui se re-rendent
                        # tout aussi souvent (changement de saison/équipe).
                        st.markdown(
                            _img_html(
                                HEADSHOT_URL_TEMPLATE.format(player_id=int(player_id)),
                                player_name, "roster-photo-box",
                            ),
                            unsafe_allow_html=True,
                        )
                    st.markdown(f"**{player_name}**")
                    pts, reb, ast, pie = (
                        row.get("points_per_game"), row.get("rebounds_per_game"),
                        row.get("assists_per_game"), row.get("pie"),
                    )
                    if pd.notna(pts) and pd.notna(reb) and pd.notna(ast) and pd.notna(pie):
                        st.caption(f"{pts:.1f} pts · {reb:.1f} reb · {ast:.1f} pas · PIE {pie:.3f}")
                    else:
                        st.caption("Stats indisponibles")

    st.caption(
        "ℹ️ Photos : CDN public NBA — une partie des joueurs (surtout saisons antérieures aux "
        "années 2000) n'y ont pas de photo disponible, affichée comme une image cassée pour "
        "l'instant (pas de fallback en v1)."
    )
