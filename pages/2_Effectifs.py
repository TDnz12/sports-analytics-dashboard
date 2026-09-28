"""
Effectifs — fusion des anciennes pages Rosters et Mercato. Deux vues, choisies par l'adresse :
  - grille (pas de paramètre) : la grille Mercato, composition à 6 joueurs (5 majeur + 6e homme)
    de chaque équipe pour la saison sélectionnée, modifiable (✕, ⇄, +, glisser-déposer) ;
  - effectif réel d'une équipe (?saison=2024-25&equipe=BOS) : tous les joueurs de l'équipe
    d'après get_player_stats, une carte par joueur (photo + pts/reb/pas/PIE). Jamais les
    modifications de la grille, qui n'existent que dans le navigateur.

Passage de l'une à l'autre : le nom d'équipe de chaque carte est un vrai lien <a href="?saison=..
&equipe=..">. Clic simple : le JS du composant bloque le rechargement complet (qui ferait perdre la
session, donc la synchronisation avec main_season) et prévient Python par setTriggerValue ;
Python place saison/equipe dans st.query_params, ce que Streamlit pousse dans l'historique du
navigateur (pushState) -- le bouton Précédent ramène donc à la grille, et l'adresse d'un effectif
est partageable. Clic du milieu / Cmd / Ctrl : lien suivi normalement (nouvel onglet).

Page séparée du dashboard principal (Dashboard.py, qui ne change pas de comportement), même
convention que pages/1_Radar_de_comparaison.py : script Streamlit à part entière (système
multi-page natif basé sur le dossier pages/), qui partage st.session_state avec les autres pages
sans les importer.

La composition d'ORIGINE (éligibilité, tri, étiquettes M/A/AI/AF/P) vit dans
nba.get_mercato_lineup, voir sa docstring pour le détail.

Grille interactive en HTML + JavaScript (composant st.components.v2, SANS iframe, monté
directement dans la page -- disponible depuis Streamlit 1.51) : Python prépare les données de la
saison UNE fois (prepare_season, en cache) et les envoie au composant ; tous les clics (retirer ✕,
ajouter via une recherche par saisie de texte en cliquant sur une tuile vide, intervertir ⇄ avec
le voisin de droite, glisser-déposer d'une tuile, reset par équipe, reset global) sont gérés côté
navigateur, sans jamais repasser par Python -- seul le clic sur un nom d'équipe (ouverture de
l'effectif réel, voir plus haut) le fait. Pourquoi : la version précédente, 100 % widgets Streamlit (~400 éléments,
fragments par carte, fenêtre de recherche unique), répondait en ~10 ms côté Python mais le
navigateur mettait ~2 s à redessiner la page à chaque clic -- mesuré, voir l'historique git.

Règles (implémentées dans MERCATO_GRID_JS, partie "fonctions d'état pures") : étiquettes
M/A/AI/AF/P/6e attachées au SLOT, jamais au joueur ; vrai mercato (un joueur ajouté quitte son
ancienne carte, toast) ; pas de ⚠️ pour un joueur ajouté ; glisser-déposer (Pointer Events, souris
et doigt, appui long de 300 ms au doigt pour laisser la page défiler) : vers une tuile vide = le
joueur s'y déplace, sur un autre joueur = les deux échangent leur place (toast seulement entre deux
cartes), hors tuile = rien ; un joueur qui change de carte perd son ⚠️, comme un ajout, et le
retrouve dès qu'il revient dans sa carte d'origine (quelle que soit sa place) ; le reset d'une
équipe reprend ses joueurs d'origine transférés ailleurs (toast), et renvoie un joueur venu
d'ailleurs à sa place d'origine dans son autre carte si elle est vide (toast ; sinon il sort) ; marqueur "modifiée" sur toute carte différente de
l'origine. État sauvegardé par saison dans le localStorage du navigateur (survit au changement de
saison ET au rechargement de la page), avec repli en mémoire si localStorage est indisponible ;
un état sauvegardé n'est réutilisé que si la composition d'origine n'a pas changé depuis
(empreinte). Purement visuel et propre à cette page : les DataFrames du cache (get_mercato_lineup,
get_player_stats) ne sont jamais modifiés, rien n'est partagé avec les autres pages.

2 cartes par ligne (pas 3, voir la v2 précédente) : à 6 tuiles par carte (contre 4 sur
rostermania), il faut de la largeur pour que les photos restent grandes. Paliers selon la
largeur du composant (container queries, seuils mesurés pour garder des tuiles d'au moins ~60 px) :
au-dessus de 880 px, 2 cartes par ligne ; de 641 à 880 px, 1 carte par ligne avec 6 tuiles en
ligne ; 640 px et moins, 1 carte par ligne et 2 rangées de 3 tuiles (M A AI / AF P 6e), sans
l'espace avant le 6e, le ⇄ AI <-> AF ayant alors sa propre ligne libellée entre les deux rangées
(pas vérifié sur un vrai téléphone -- à confirmer visuellement). Sous les tuiles : ✕ centré sous
chaque tuile, ⇄ centré sur l'espace entre les deux tuiles qu'il intervertit.

Duplique volontairement le bloc CSS de densité de Dashboard.py plutôt que de l'importer -- un
fichier de pages/ est un script à part entière, pas un module (voir la docstring de
pages/1_Radar_de_comparaison.py pour le pourquoi). Le JS et le CSS du composant sont inclus ici en
chaînes pour la même raison (un composant v2 ne peut référencer des fichiers que s'il est installé
comme paquet). Tests du JS : tests/js/ (fonctions d'état avec node, rendu et clics avec jsdom).

Photos (grille et vue effectif réel) : CDN public NBA. À partir de 2015-16, portrait de la
saison, classé sur le CDN par équipe et par saison (aucun avant : vérifié en septembre 2026) et
pris sous l'équipe du PREMIER match du joueur (nba.get_first_game_teams) : un joueur transféré
apparaît avec le maillot de sa première équipe, ce qui montre le transfert. S'il manque (signature
en cours de saison...), le navigateur bascule sur le portrait actuel. Avant 2015-16 : portrait
actuel seul. Le CDN renvoie une silhouette grise pour un joueur sans portrait actuel. Les
équipes sont celles de la saison (codes de get_mercato_lineup, identité par saison), pas les 30
franchises actuelles : Seattle 2004-05 affiche bien les SuperSonics et leur effectif.

Nom d'équipe par saison : nba.get_team_identity (franchises ayant déménagé/changé de nom depuis
1996-97, ex: Seattle SuperSonics -> Oklahoma City Thunder, même team_id, nom différent). Logo
d'ÉPOQUE par saison : table data_sources/nba_logos.csv + fichiers static/logos/nba/, générés une
fois par scripts/update_nba_logos.py et servis par Streamlit (server.enableStaticServing, voir
.streamlit/config.toml) -- le site ne dépend d'aucune source extérieure pour les logos. Logos :
propriété de la NBA et de ses équipes, utilisés à titre non commercial (mention en bas de page).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from data_sources import SPORTS

st.set_page_config(page_title="Effectifs — Sports Analytics", page_icon="👥", layout="wide")

# Même bloc de densité que Dashboard.py / pages/1_Radar_de_comparaison.py (copié tel quel, voir
# leur commentaire d'origine pour le détail de chaque règle) -- seul le texte du titre
# (stLogoSpacer::before) change, ci-dessous. .roster-photo-box : photos de la vue effectif réel
# (la grille, elle, vit dans un composant aux styles isolés, voir MERCATO_GRID_CSS plus bas).
st.markdown(
    """
    <style>
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
    div[data-testid="stLogoSpacer"] {
        width: auto !important;
        display: flex;
        align-items: center;
    }
    div[data-testid="stLogoSpacer"]::before {
        content: "👥 Effectifs";
        font-weight: 700;
        font-size: 1rem;
        white-space: nowrap;
    }
    div[data-testid="stAppViewBlockContainer"], .block-container {
        padding-top: 1.25rem !important;
        /* Marges latérales réduites SUR CETTE PAGE UNIQUEMENT (ce bloc <style> est propre à
           Effectifs, pas partagé avec Dashboard.py/Radar) -- pour laisser le plus de
           largeur possible aux tuiles (2 cartes x 6 tuiles/carte, voir demande). */
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
    /* Photos de la vue effectif réel : cadre de taille FIXE (largeur ET hauteur) +
       object-fit: contain -- chaque portrait mis à l'échelle sans déformation ni rognage, et une
       taille connue du navigateur avant même le chargement de l'image (voir _img_html). */
    .roster-photo-box {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        background: transparent;
        height: 140px;
    }
    .roster-photo-box img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
    /* Logo de la vue effectif réel sur un disque clair (même principe que .mg-logo dans la
       grille) : les logos sombres (Spurs, Jazz...) restent lisibles sur le thème sombre. */
    .team-logo-disc {
        width: 100px;
        height: 100px;
        border-radius: 50%;
        background: #f4f4f4;
        border: 1px solid rgba(128, 128, 128, 0.3);
        padding: 12px;
        box-sizing: border-box;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 0.75rem;
    }
    .team-logo-disc img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Remet le scroll en haut de page à chaque rerun (ouverture d'un effectif, retour à la grille par
# le bouton ou par Précédent) : Streamlit ne réinitialise pas la position de scroll du navigateur
# après un rerun, donc revenir à la grille depuis un effectif scrollé montrait le milieu de la
# grille, pas son début (repéré en test sur l'ancienne page Rosters). Un clic sur un nom d'équipe
# remonte déjà la page côté JS (voir scrollPageToTop dans MERCATO_GRID_JS) ; ce script couvre le
# retour. st.iframe (iframe) est nécessaire ici : un <script> inséré via
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

# MVP : NBA uniquement, même raison que pages/1_Radar_de_comparaison.py.
sport = SPORTS["nba"]
if sport.get_mercato_lineup is None or sport.get_player_stats is None:
    st.title("👥 Effectifs")
    st.info("Effectifs pas encore disponibles pour ce sport.")
    st.stop()

# Gabarit photo de la grille : côté JS, voir HEADSHOT_URL dans MERCATO_GRID_JS.
HEADSHOT_URL_TEMPLATE = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
# Portraits par équipe et par saison : le CDN n'en a qu'à partir de 2015-16 (403 pour toutes les
# saisons antérieures testées). Côté JS, voir headshotSources dans MERCATO_GRID_JS.
FIRST_SEASON_HEADSHOT_YEAR = 2015
SEASON_HEADSHOT_URL_TEMPLATE = "https://cdn.nba.com/headshots/nba/{team_id}/{year}/1040x760/{player_id}.png"
PHOTO_NOTICE = (
    "Photos : portrait de la saison à partir de 2015-16 quand il existe, sinon portrait le plus "
    "récent du joueur."
)

# Logos d'époque : table saison -> fichier (scripts/update_nba_logos.py) et adresse de service des
# fichiers de static/ (relative : fonctionne aussi dans le composant de la grille, sans iframe, et
# sur Community Cloud).
LOGO_TABLE = Path(__file__).resolve().parent.parent / "data_sources" / "nba_logos.csv"
LOGO_URL_TEMPLATE = "app/static/logos/nba/{file}"
LOGO_NOTICE = "Logos : propriété de la NBA et de ses équipes, utilisés à titre non commercial."


@st.cache_data(show_spinner=False)
def load_logo_table() -> dict[tuple[str, str], str]:
    """{(saison, code équipe): nom du fichier dans static/logos/nba/}."""
    df = pd.read_csv(LOGO_TABLE, dtype=str)
    return {(r.season, r.team): r.file for r in df.itertuples()}


def team_logo_url(team_code: str, season: str) -> str | None:
    """Logo de `team_code` tel qu'il était pendant `season` (ex: dinosaure des Raptors en
    2003-04, SuperSonics en 2004-05), ou None si la table n'en a pas -- l'appelant affiche
    alors un emblème neutre. La table couvre toutes les (saison, équipe) de 1996-97 à 2025-26
    (vérifié par tests/test_nba_logos.py) : None ne devrait arriver que pour une saison ajoutée
    sans relancer scripts/update_nba_logos.py. Grille ET vue effectif réel l'utilisent."""
    file = load_logo_table().get((season, team_code))
    return LOGO_URL_TEMPLATE.format(file=file) if file else None


def season_photo_team_ids(sport_key: str, season: str) -> dict[int, int]:
    """{player_id: team_id de l'équipe de son premier match} pour les saisons à portrait
    d'époque (2015-16 et suivantes, voir nba.get_first_game_teams), {} avant : les deux vues
    n'utilisent alors que le portrait actuel. Pas mis en cache ici : les appelants le sont
    (prepare_season, load_photo_team_ids)."""
    sp = SPORTS[sport_key]
    if int(season[:4]) < FIRST_SEASON_HEADSHOT_YEAR or sp.get_first_game_teams is None:
        return {}
    df = sp.get_first_game_teams(season, force_refresh=False)
    return {int(pid): int(tid) for pid, tid in zip(df["player_id"], df["team_id"])}


# Saison : une saison valide dans l'adresse (?saison=, lien d'effectif partagé ou bouton
# Précédent) l'emporte ; sinon, par défaut, alignée sur la saison actuellement affichée dans la
# sidebar principale de Dashboard.py (st.session_state["main_season"], partagé -- voir son
# commentaire) si elle est valide ici (une vraie saison, pas le mode combiné "Toutes les saisons"
# qui n'a pas d'équivalent sur cette page). key= (pas index= recalculé) pour que le choix de
# l'utilisateur SUR CETTE PAGE survive aux reruns suivants, même principe que radar_season.
# Toujours la saison régulière (get_mercato_lineup ne gère que ça, voir sa docstring).
_default_season = "2024-25" if "2024-25" in sport.seasons else sport.seasons[0]
_url_season = st.query_params.get("saison")
if _url_season in sport.seasons:
    st.session_state["effectifs_season"] = _url_season
elif "effectifs_season" not in st.session_state:
    _main_season = st.session_state.get("main_season")
    st.session_state["effectifs_season"] = _main_season if _main_season in sport.seasons else _default_season


def _sync_season_in_url() -> None:
    # Changement de saison alors que l'adresse porte ?saison= (vue effectif réel, ou lien
    # partagé) : l'adresse suit (même équipe, nouvelle saison), pour qu'elle reste partageable et
    # que le prochain rerun ne rétablisse pas l'ancienne saison depuis ?saison=.
    if "saison" in st.query_params or "equipe" in st.query_params:
        st.query_params["saison"] = st.session_state["effectifs_season"]


season = st.sidebar.selectbox(
    "Saison", options=sport.seasons, key="effectifs_season", on_change=_sync_season_in_url
)


# --- Vue effectif réel (?equipe=CODE) ----------------------------------------------------------

# Repli des photos de la vue effectif réel sur le portrait actuel. Pas d'attribut onerror :
# st.markdown l'ignore (HTML rendu par React) et st.html le retire (DOMPurify), même avec
# unsafe_allow_javascript. Un seul script écoute donc les erreurs de chargement d'image sur tout
# le document (phase de capture : l'événement error ne remonte pas) et remplace la source d'une
# <img data-fallback> par son repli, une seule fois. Il traite aussi les images déjà en échec
# quand il s'exécute (ordre de montage des éléments non garanti).
PHOTO_FALLBACK_SCRIPT = """<script>
(() => {
  const swap = (img) => {
    const fallback = img.dataset.fallback;
    if (!fallback) return;
    delete img.dataset.fallback;
    img.src = fallback;
  };
  if (!window.__effectifsPhotoFallback) {
    window.__effectifsPhotoFallback = true;
    document.addEventListener("error", (e) => {
      if (e.target instanceof HTMLImageElement) swap(e.target);
    }, true);
  }
  document.querySelectorAll("img[data-fallback]").forEach((img) => {
    if (img.complete && img.naturalWidth === 0) swap(img);
  });
})();
</script>"""


def _img_html(url: str, alt: str, box_class: str, fallback: str | None = None) -> str:
    # <img> en HTML brut (st.markdown) plutôt que st.image(..., width="stretch") : ce dernier
    # laisse le NAVIGATEUR calculer la largeur réelle après mise en page du conteneur parent --
    # un calcul qui, pour de nombreuses images montées d'un coup après un rerun complet, peut ne
    # pas être terminé avant que Streamlit ne remplace le DOM, laissant certaines images sans
    # dimension résolue et donc jamais chargées (bug repéré en test sur l'ancienne page Rosters :
    # seuls 1-2 logos sur 30 réapparaissaient après un aller-retour). Le cadre CSS à taille FIXE
    # (.roster-photo-box, voir plus haut) + loading="eager"/decoding="async" évitent ce calcul
    # différé : le navigateur connaît la taille de la zone AVANT même de savoir si l'image a
    # chargé, et démarre le chargement tout de suite plutôt que d'attendre une passe de mise en
    # page. fallback : voir PHOTO_FALLBACK_SCRIPT.
    fallback_attr = f' data-fallback="{fallback}"' if fallback else ""
    return (
        f'<div class="{box_class}"><img src="{url}"{fallback_attr} alt="{alt}" '
        f'loading="eager" decoding="async"></div>'
    )


@st.cache_data(show_spinner="Chargement des données NBA (nba_api + Kaggle)...")
def load_players(sport_key: str, season: str) -> pd.DataFrame:
    return SPORTS[sport_key].get_player_stats(season, force_refresh=False, period="regular")


@st.cache_data(show_spinner="Chargement des équipes de la saison...")
def load_identity(sport_key: str, season: str) -> dict:
    """{code équipe: (team_id, nom de la franchise CETTE saison-là)}, voir nba.get_team_identity."""
    sp = SPORTS[sport_key]
    if sp.get_team_identity is None:
        return {}
    df = sp.get_team_identity(season, force_refresh=False)
    return {r["team"]: (r["team_id"], r["team_name"]) for _, r in df.iterrows()}


@st.cache_data(show_spinner=False)
def load_photo_team_ids(sport_key: str, season: str) -> dict[int, int]:
    return season_photo_team_ids(sport_key, season)


def _back_to_grid() -> None:
    st.query_params.clear()


team_code = st.query_params.get("equipe")
if team_code:
    # Espace au-dessus du bouton : sans lui, ce bouton (premier élément affiché sur cette vue)
    # se retrouve collé contre la barre d'outils flottante de Streamlit (coupé visuellement en
    # haut de page, repéré en test sur l'ancienne page Rosters).
    st.markdown("<div style='height: 0.75rem;'></div>", unsafe_allow_html=True)
    st.button("← Retour à la grille", on_click=_back_to_grid)

    try:
        players_df = load_players(sport.key, season)
    except Exception as exc:
        st.title("👥 Effectifs")
        st.error(f"Impossible de charger les joueurs de {season} : {exc}")
        st.stop()
    # Identité indisponible (ex. serveur NBA injoignable sans cache) : pas bloquant, le code
    # d'équipe sert alors de nom (le logo, lui, vient de la table locale, voir team_logo_url).
    try:
        identity = load_identity(sport.key, season)
    except Exception:
        identity = {}
    # Indisponible : pas bloquant, portrait actuel pour tout le monde.
    try:
        photo_team_ids = load_photo_team_ids(sport.key, season)
    except Exception:
        photo_team_ids = {}

    roster_df = players_df[players_df["team"] == team_code].sort_values("player").reset_index(drop=True)
    if roster_df.empty and team_code not in identity:
        st.title("👥 Effectifs")
        st.warning(f"Aucune équipe « {team_code} » pour la saison {season}.")
        st.stop()

    team_name = identity[team_code][1] if team_code in identity else team_code
    st.title(f"👥 {team_name} — Effectif réel {season}")
    st.caption(
        f"Tous les joueurs de l'équipe d'après les statistiques officielles de la saison régulière "
        f"{season}. Les modifications faites dans la grille (✕, ⇄, +) n'apparaissent pas ici."
    )
    logo = team_logo_url(team_code, season)
    if logo:
        # Disque clair derrière le logo (logos sombres lisibles sur fond sombre, ex. Spurs, Jazz),
        # en HTML plutôt que st.image, qui ne sait pas dessiner ce fond.
        st.markdown(
            f'<div class="team-logo-disc"><img src="{logo}" alt="{team_code}"></div>',
            unsafe_allow_html=True,
        )

    if roster_df.empty:
        st.warning(f"Aucun joueur trouvé pour {team_name} en {season}.")
    else:
        N_PLAYER_COLS = 5
        player_cols = st.columns(N_PLAYER_COLS)
        for i, row in roster_df.iterrows():
            with player_cols[i % N_PLAYER_COLS]:
                with st.container(border=True):
                    player_id = row.get("player_id")
                    player_name = row.get("player", "—")
                    if pd.notna(player_id):
                        latest = HEADSHOT_URL_TEMPLATE.format(player_id=int(player_id))
                        photo_team_id = photo_team_ids.get(int(player_id))
                        if photo_team_id is None:
                            photo = _img_html(latest, player_name, "roster-photo-box")
                        else:
                            photo = _img_html(
                                SEASON_HEADSHOT_URL_TEMPLATE.format(
                                    team_id=photo_team_id, year=int(season[:4]),
                                    player_id=int(player_id),
                                ),
                                player_name, "roster-photo-box", fallback=latest,
                            )
                        st.markdown(photo, unsafe_allow_html=True)
                    st.markdown(f"**{player_name}**")
                    pts, reb, ast, pie = (
                        row.get("points_per_game"), row.get("rebounds_per_game"),
                        row.get("assists_per_game"), row.get("pie"),
                    )
                    if pd.notna(pts) and pd.notna(reb) and pd.notna(ast) and pd.notna(pie):
                        st.caption(f"{pts:.1f} pts · {reb:.1f} reb · {ast:.1f} pas · PIE {pie:.3f}")
                    else:
                        st.caption("Stats indisponibles")

    if photo_team_ids:
        st.html(PHOTO_FALLBACK_SCRIPT, unsafe_allow_javascript=True)
    st.caption(PHOTO_NOTICE)
    st.caption(LOGO_NOTICE)
    st.stop()


# --- Vue grille (pas de ?equipe=) ---------------------------------------------------------------


@st.cache_data(show_spinner="Chargement des compositions...")
def prepare_season(sport_key: str, season: str) -> dict:
    """Tout ce qui ne dépend QUE de la saison, calculé une seule fois par saison (puis servi par
    st.cache_data, qui en renvoie une copie : rien ici ne peut altérer les DataFrames du cache
    de data_sources, ni ceux des autres pages). `grid_data` = données JSON envoyées telles
    quelles au composant (voir MERCATO_GRID_JS) :
      - season ;
      - teams : [{code, name, logo (URL ou None -> emblème neutre), slots: [player_id|None] x 6}],
        triées par nom affiché ;
      - players : [[player_id, nom, équipe], ...] de TOUS les joueurs de la saison (recherche),
        triés par nom ;
      - missing : player_id dont le poste est inconnu dans la composition d'origine (⚠️) ;
      - photo_team_ids : {player_id: team_id du premier match}, voir season_photo_team_ids ({}
        avant 2015-16 ou si le game log est indisponible, non bloquant).
    Lève l'exception de get_mercato_lineup si la composition est introuvable (jamais mise en
    cache par Streamlit, voir l'appelant) ; un échec de get_player_stats, lui, n'est pas
    bloquant (players_error, la recherche se limite alors aux joueurs déjà présents dans les
    cartes)."""
    sp = SPORTS[sport_key]
    df = sp.get_mercato_lineup(season, force_refresh=False)
    if df.empty:
        return {"empty": True}

    identity_df = (
        sp.get_team_identity(season, force_refresh=False) if sp.get_team_identity
        else pd.DataFrame(columns=["team", "team_id", "team_name"])
    )
    identity = {r["team"]: (r["team_id"], r["team_name"]) for _, r in identity_df.iterrows()}

    players_error = None
    try:
        players_df = sp.get_player_stats(season, force_refresh=False, period="regular")[
            ["player_id", "player", "team"]
        ]
    except Exception as exc:
        players_error = str(exc)
        players_df = pd.DataFrame(columns=["player_id", "player", "team"])

    # {player_id: (nom, équipe)} : get_player_stats d'abord, complété par la composition
    # d'origine pour un éventuel joueur absent de get_player_stats (repli, pas observé en
    # pratique).
    player_info: dict[int, tuple[str, str]] = {}
    for _, r in df.iterrows():
        player_info[int(r["player_id"])] = (
            r["player"] if pd.notna(r["player"]) else str(r["player_id"]), r["team"]
        )
    for _, r in players_df.dropna(subset=["player_id", "player"]).iterrows():
        player_info[int(r["player_id"])] = (r["player"], r["team"] if pd.notna(r["team"]) else "?")

    initial_lineups: dict[str, list] = {team: [None] * 6 for team in df["team"].unique()}
    for _, r in df.iterrows():
        initial_lineups[r["team"]][int(r["slot"]) - 1] = int(r["player_id"])

    team_names = {t: (identity[t][1] if t in identity else t) for t in initial_lineups}
    teams = [
        {"code": t, "name": team_names[t], "logo": team_logo_url(t, season),
         "slots": initial_lineups[t]}
        for t in sorted(initial_lineups, key=lambda t: team_names[t])
    ]
    players = [[pid, name, team] for pid, (name, team) in sorted(player_info.items(), key=lambda kv: kv[1][0])]
    missing = sorted({int(pid) for pid in df.loc[df["position_missing"], "player_id"]})
    try:
        photo_team_ids = season_photo_team_ids(sport_key, season)
    except Exception:
        photo_team_ids = {}
    return {
        "empty": False,
        "players_error": players_error,
        "grid_data": {"season": season, "teams": teams, "players": players, "missing": missing,
                      "photo_team_ids": photo_team_ids},
    }


# Échec retenu par saison pour la session : st.cache_data ne met pas les exceptions en cache,
# sans ça chaque rerun referait attendre le délai réseau complet (voir NBA_API_TIMEOUT_SECONDS).
_failed = st.session_state.setdefault("mercato_failed_seasons", {})
prep_error = _failed.get(season)
if prep_error is None:
    try:
        prep = prepare_season(sport.key, season)
    except Exception as exc:
        prep_error = _failed[season] = str(exc)
if prep_error is not None:
    st.error(
        f"Compositions indisponibles pour {season} : le serveur de la NBA n'a pas répondu "
        "(il bloque souvent les hébergements en ligne). Choisis une autre saison."
    )
    with st.expander("Détail technique"):
        st.code(prep_error)
    st.stop()

if prep["empty"]:
    st.warning(f"Aucune donnée disponible pour {season}.")
    st.stop()

if prep["players_error"]:
    st.warning(f"Liste complète des joueurs indisponible pour {season} : {prep['players_error']}")


# --- Composant de la grille (HTML + JS, sans iframe) -----------------------------------------
# JS en deux parties : fonctions d'état PURES exportées (testables hors navigateur) puis rendu
# DOM. Streamlit appelle l'export par défaut au montage puis à chaque changement de `data`
# (changement de saison), avec le même élément parent : la grille est réutilisée.
MERCATO_GRID_CSS = r"""
/* Styles de la grille Mercato, isolés dans le shadow DOM du composant. Valeurs reprises de
   l'ancienne version Streamlit (tuiles, badge, nom en surimpression, tuile vide en pointillés).
   Police et couleur du texte héritées de la page ; fonds de fenêtre/toast via les variables de
   thème --st-* que Streamlit pose sur le composant (valeurs de repli sinon). Couleurs fixes
   (bordures grises semi-transparentes, fond de tuile sombre) lisibles en thème clair ET sombre. */
.mg-root {
  container: mg / inline-size;
  font-family: inherit;
  color: inherit;
}
.mg-root *, .mg-root *::before, .mg-root *::after { box-sizing: border-box; }
.mg-root button, .mg-root input { font: inherit; color: inherit; }

.mg-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.mg-note { font-size: 0.75rem; opacity: 0.6; }

/* 2 cartes par ligne (1 sur écran étroit, voir @container plus bas). */
.mg-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  align-items: start;
}
/* Même aspect qu'un st.container(border=True). */
.mg-card {
  border: 1px solid rgba(128, 128, 128, 0.3);
  border-radius: 0.5rem;
  padding: calc(1rem - 1px);
  min-width: 0;
}
.mg-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.mg-ident { display: flex; align-items: center; gap: 0.5rem; }
/* Logo sur un disque clair : les logos sombres (Spurs, Jazz...) restent lisibles sur le thème
   sombre. Même taille totale qu'avant (32 px), l'en-tête ne grandit pas. */
.mg-logo {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f4f4f4;
  border: 1px solid rgba(128, 128, 128, 0.3);
  padding: 3px;
}
.mg-logo img { width: 100%; height: 100%; object-fit: contain; }
.mg-emblem {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(128, 128, 128, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 700;
  flex-shrink: 0;
}
/* Nom d'équipe = lien <a> vers l'effectif réel, présenté comme un bouton (visible comme
   cliquable même sans survol, sur téléphone). Bordure, rayon et hauteur de "Tout réinitialiser"
   (.mg-reset-all) pour la cohérence, avec un léger fond en plus. min-height 1.8rem < logo 32px :
   l'en-tête garde sa hauteur tant que le nom tient sur une ligne. Jamais de coupure au milieu
   d'un mot (ni ellipse, ni césure) : le nom passe à la ligne entre deux mots si la place manque
   vraiment (le lien ne rétrécit pas sous la largeur de son mot le plus long). */
.mg-team-link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 1.8rem;
  padding: 0.1rem 0.6rem;
  border: 1px solid rgba(128, 128, 128, 0.4);
  border-radius: 0.3rem;
  background: rgba(128, 128, 128, 0.08);
  color: inherit;
  text-decoration: none;
  line-height: 1.2;
  cursor: pointer;
}
.mg-team-link:hover, .mg-team-link:focus-visible {
  background: rgba(128, 128, 128, 0.18);
  border-color: rgba(128, 128, 128, 0.75);
}
.mg-team-name { font-weight: 700; font-size: 1rem; }
.mg-team-arrow { font-size: 0.8rem; opacity: 0.55; flex-shrink: 0; }
/* Marqueur discret "modifiée" : composition différente de l'origine. */
.mg-modified {
  font-size: 0.62rem;
  font-weight: 600;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
  border: 1px solid rgba(232, 163, 61, 0.7);
  color: #e8a33d;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Slots 1-5, colonne d'espacement étroite (même proportion 0.15 qu'avant), 6e homme.
   Rangée 1 : tuiles. Rangée 2 : boutons, placés dans la MÊME grille que les tuiles :
     - ✕ dans la colonne de sa tuile, centré -> centré sous la tuile ;
     - ⇄ étalé sur les colonnes des deux tuiles qu'il intervertit, centré -> centré sur l'espace
       entre elles (colonnes de même largeur) ; P <-> 6e s'étale sur P + espacement + 6e, donc
       centré au milieu de l'espacement (colonnes symétriques 1fr / 0.15fr / 1fr). */
.mg-slots {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr)) minmax(0, 0.15fr) minmax(0, 1fr);
  column-gap: 0.25rem;
}
.mg-slot { display: flex; flex-direction: column; min-width: 0; grid-row: 1; }
.mg-spacer { grid-row: 1; grid-column: 6; }
.mg-slot[data-slot="0"], .mg-x[data-slot="0"] { grid-column: 1; }
.mg-slot[data-slot="1"], .mg-x[data-slot="1"] { grid-column: 2; }
.mg-slot[data-slot="2"], .mg-x[data-slot="2"] { grid-column: 3; }
.mg-slot[data-slot="3"], .mg-x[data-slot="3"] { grid-column: 4; }
.mg-slot[data-slot="4"], .mg-x[data-slot="4"] { grid-column: 5; }
.mg-slot[data-slot="5"], .mg-x[data-slot="5"] { grid-column: 7; }
.mg-swap[data-slot="0"] { grid-column: 1 / span 2; }
.mg-swap[data-slot="1"] { grid-column: 2 / span 2; }
.mg-swap[data-slot="2"] { grid-column: 3 / span 2; }
.mg-swap[data-slot="3"] { grid-column: 4 / span 2; }
.mg-swap[data-slot="4"] { grid-column: 5 / span 3; }
/* justify-self: center -> chaque bouton garde sa propre largeur (pas celle de sa zone) : les
   zones des ⇄ se recouvrent dans la grille mais pas les boutons, qui ne se gênent pas au clic. */
.mg-x, .mg-swap {
  grid-row: 2;
  justify-self: center;
  margin-top: 0.2rem;
  min-width: 1.3rem;
  padding: 0 0.2rem !important;
}
.mg-swap { opacity: 0.5; }
.mg-swap-label { display: none; }

.mg-tile {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 0.6rem;
  overflow: hidden;
  background: #1c1c1c;
  margin: 0.5rem 0 0;
  padding: 0;
  border: none;
}
.mg-tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* Cadré en haut : visage/épaules visibles, pas rognés ni cachés sous le nom. */
  object-position: center top;
  display: block;
}
.mg-tile-empty {
  background: transparent;
  border: 2px dashed rgba(128, 128, 128, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.mg-tile-empty:hover { border-color: rgba(128, 128, 128, 0.9); }
.mg-plus {
  font-size: 1.8rem;
  font-weight: 300;
  color: rgba(128, 128, 128, 0.8);
  line-height: 1;
}
.mg-badge {
  position: absolute;
  top: 0.25rem;
  left: 0.25rem;
  background: #1f77b4;
  color: #fff;
  font-weight: 700;
  font-size: 0.65rem;
  line-height: 1.4;
  padding: 0.08rem 0.32rem;
  border-radius: 0.3rem;
  z-index: 2;
}
.mg-warning {
  position: absolute;
  top: 0.15rem;
  right: 0.3rem;
  font-size: 0.85rem;
  z-index: 2;
  cursor: help;
}
.mg-name {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 1rem 0.2rem 0.25rem;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.88) 15%, rgba(0, 0, 0, 0) 100%);
  color: #fff;
  font-weight: 800;
  font-size: 0.56rem;
  text-align: center;
  text-transform: uppercase;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Glisser-déposer (voir "Glisser-déposer" dans MERCATO_GRID_JS). Pas de touch-action: none : la
   page doit pouvoir défiler au doigt en passant sur les tuiles. Pas de sélection de texte, de menu
   iOS (enregistrer l'image...) ni de glisser natif de la photo pendant l'appui long. */
.mg-tile:not(.mg-tile-empty) {
  cursor: grab;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
}
.mg-tile img { -webkit-user-drag: none; }
.mg-tile.mg-dragging { opacity: 0.35; }
.mg-drop-target .mg-tile {
  outline: 3px solid var(--st-primary-color, #ff4b4b);
  outline-offset: 2px;
}
/* Fantôme : copie de la tuile qui suit le pointeur, ignorée par elementFromPoint. */
.mg-ghost {
  position: fixed;
  left: 0;
  top: 0;
  margin: 0;
  z-index: 1000150;
  pointer-events: none;
  opacity: 0.9;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.4);
  will-change: transform;
}
.mg-is-dragging, .mg-is-dragging * { cursor: grabbing !important; user-select: none; -webkit-user-select: none; }

/* Petits boutons (✕ retirer, ⇄ intervertir, ↺ reset, fermer). */
.mg-btn {
  background: transparent;
  border: none;
  border-radius: 0.3rem;
  padding: 0 0.35rem;
  height: 1.4rem;
  font-size: 0.72rem;
  line-height: 1;
  cursor: pointer;
  opacity: 0.75;
}
.mg-btn:hover { opacity: 1; background: rgba(128, 128, 128, 0.15); }
.mg-btn:disabled { opacity: 0.25; cursor: default; background: transparent; }
.mg-reset-team { font-size: 0.9rem; flex-shrink: 0; }
.mg-reset-all {
  border: 1px solid rgba(128, 128, 128, 0.4);
  height: 1.8rem;
  padding: 0 0.6rem;
  font-size: 0.8rem;
}
.mg-reset-all[data-confirm="1"] { border-color: #d9534f; color: #d9534f; opacity: 1; }

/* Fenêtre de recherche. */
.mg-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 12vh 1rem 1rem;
  z-index: 1000100;
}
.mg-panel {
  width: min(26rem, 100%);
  background: var(--st-background-color, #fff);
  color: var(--st-text-color, #31333f);
  border-radius: 0.6rem;
  padding: 1rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}
.mg-panel-head { display: flex; justify-content: space-between; align-items: center; }
.mg-panel-caption { font-size: 0.8rem; opacity: 0.65; margin: 0.25rem 0 0.6rem; }
.mg-input {
  width: 100%;
  padding: 0.45rem 0.6rem;
  border-radius: 0.4rem;
  border: 1px solid rgba(128, 128, 128, 0.45);
  background: var(--st-secondary-background-color, transparent);
  outline: none;
}
.mg-input:focus { border-color: var(--st-primary-color, #ff4b4b); }
.mg-results {
  margin-top: 0.5rem;
  max-height: 50vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.mg-result {
  text-align: left;
  background: transparent;
  border: none;
  padding: 0.35rem 0.5rem;
  border-radius: 0.3rem;
  cursor: pointer;
  font-size: 0.88rem;
}
.mg-result:hover, .mg-result.is-active { background: rgba(128, 128, 128, 0.18); }
.mg-hint { font-size: 0.8rem; opacity: 0.6; padding: 0.35rem 0.5rem; }

/* Toasts. */
.mg-toasts {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.5rem;
  z-index: 1000200;
  pointer-events: none;
}
.mg-toast {
  background: var(--st-secondary-background-color, #f0f2f6);
  color: var(--st-text-color, #31333f);
  padding: 0.6rem 0.9rem;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
  max-width: min(22rem, calc(100vw - 2rem));
  transition: opacity 0.3s;
}
.mg-toast-out { opacity: 0; }

/* Paliers de largeur (largeur du COMPOSANT, pas de l'écran : tient compte de la barre latérale),
   fixés par mesure pour que les tuiles ne descendent jamais sous ~60 px :
     - au-dessus de 880 px : 2 cartes par ligne, 6 tuiles en ligne ;
     - de 641 à 880 px : 1 carte par ligne, 6 tuiles en ligne ;
     - 640 px et moins : 1 carte par ligne, 2 rangées de 3 (bloc suivant). */
@container mg (max-width: 880px) {
  .mg-grid { grid-template-columns: minmax(0, 1fr); }
}

/* Écran étroit : 1 carte par ligne, 2 rangées de 3 tuiles (M A AI / AF P 6e), sans l'espace avant le 6e.
   Rangées de la grille des slots : 1 tuiles M A AI, 2 leurs boutons, 3 le ⇄ AI <-> AF, 4 tuiles
   AF P 6e, 5 leurs boutons. AI et AF n'étant plus côte à côte, leur ⇄ a sa propre ligne entre les
   deux rangées, centrée, avec les libellés "AI ⇄ AF" affichés pour lever toute ambiguïté. */
@container mg (max-width: 640px) {
  .mg-grid { grid-template-columns: minmax(0, 1fr); }
  .mg-slots { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .mg-spacer { display: none; }
  .mg-slot[data-slot="0"], .mg-slot[data-slot="1"], .mg-slot[data-slot="2"] { grid-row: 1; }
  .mg-slot[data-slot="3"], .mg-slot[data-slot="4"], .mg-slot[data-slot="5"] { grid-row: 4; }
  .mg-x[data-slot="0"], .mg-x[data-slot="1"], .mg-x[data-slot="2"] { grid-row: 2; }
  .mg-x[data-slot="3"], .mg-x[data-slot="4"], .mg-x[data-slot="5"] { grid-row: 5; }
  .mg-slot[data-slot="0"], .mg-x[data-slot="0"], .mg-slot[data-slot="3"], .mg-x[data-slot="3"] { grid-column: 1; }
  .mg-slot[data-slot="1"], .mg-x[data-slot="1"], .mg-slot[data-slot="4"], .mg-x[data-slot="4"] { grid-column: 2; }
  .mg-slot[data-slot="2"], .mg-x[data-slot="2"], .mg-slot[data-slot="5"], .mg-x[data-slot="5"] { grid-column: 3; }
  .mg-swap[data-slot="0"] { grid-row: 2; grid-column: 1 / span 2; }
  .mg-swap[data-slot="1"] { grid-row: 2; grid-column: 2 / span 2; }
  .mg-swap[data-slot="2"] { grid-row: 3; grid-column: 1 / -1; margin-top: 0; }
  .mg-swap[data-slot="3"] { grid-row: 5; grid-column: 1 / span 2; }
  .mg-swap[data-slot="4"] { grid-row: 5; grid-column: 2 / span 2; }
  .mg-swap[data-slot="2"] .mg-swap-label { display: inline; }
}
"""

MERCATO_GRID_JS = r"""
// Grille Mercato (composant st.components.v2, sans iframe). Deux parties :
//   1. fonctions d'état PURES (aucun accès au DOM), exportées et testées avec node ;
//   2. rendu DOM + gestion des clics (export default, appelé par Streamlit au montage puis à
//      chaque changement de données, c'est-à-dire à chaque changement de saison).
// Glisser-déposer : moveOrSwap (état) et la partie "Glisser-déposer" de createGrid (gestes).
// Aucun clic ne repasse par Python (sauf le clic sur un nom d'équipe, qui ouvre l'effectif réel
// via setTriggerValue) : l'état vit ici, sauvegardé dans localStorage par saison.
// Tests : tests/js/ (voir l'en-tête de chaque fichier pour la commande).

// ---------------------------------------------------------------------------------------------
// 1. Fonctions d'état pures
// ---------------------------------------------------------------------------------------------

export const SLOT_LABELS = ["M", "A", "AI", "AF", "P", "6e"];
export const STORAGE_PREFIX = "mercato_v1_";
const HEADSHOT_URL = (id) => `https://cdn.nba.com/headshots/nba/latest/1040x760/${id}.png`;
const SEASON_HEADSHOT_URL = (teamId, year, id) => `https://cdn.nba.com/headshots/nba/${teamId}/${year}/1040x760/${id}.png`;
const NAME_SUFFIXES = new Set(["jr", "sr", "ii", "iii", "iv", "v"]);

// Minuscules sans accents : "Jokić" -> "jokic" (recherche insensible aux accents).
export function normalize(text) {
  return String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function lastName(fullName) {
  const parts = String(fullName).trim().split(/\s+/);
  while (parts.length > 1 && NAME_SUFFIXES.has(parts[parts.length - 1].toLowerCase().replace(/\.$/, ""))) {
    parts.pop();
  }
  return parts[parts.length - 1] || String(fullName);
}

// Nom de famille en MAJUSCULES pour chaque slot (null pour un slot vide) ; deux joueurs de la
// MÊME carte avec le même nom de famille -> initiale du prénom ("J. WILLIAMS" / "M. WILLIAMS").
export function displayLastNames(names) {
  const lasts = names.map((n) => (n == null ? null : lastName(n)));
  const counts = new Map();
  for (const ln of lasts) {
    if (ln != null) counts.set(ln.toLowerCase(), (counts.get(ln.toLowerCase()) || 0) + 1);
  }
  return names.map((full, i) => {
    const ln = lasts[i];
    if (ln == null) return null;
    if (counts.get(ln.toLowerCase()) > 1 && full.trim()) return `${full.trim()[0]}. ${ln}`.toUpperCase();
    return ln.toUpperCase();
  });
}

// Photo d'un joueur : portrait de la saison sous l'équipe de son PREMIER match (photo_team_ids,
// 2015-16 et suivantes, voir season_photo_team_ids côté Python), quelle que soit la carte où il
// se trouve (composition d'origine, ajout par la recherche, déplacement), avec le portrait actuel
// en repli ; portrait actuel seul sinon.
export function headshotSources(data, pid) {
  const latest = HEADSHOT_URL(pid);
  const teamId = data.photo_team_ids[pid];
  if (teamId == null) return { src: latest, fallback: null };
  return { src: SEASON_HEADSHOT_URL(teamId, parseInt(data.season, 10), pid), fallback: latest };
}

// Empreinte de la composition d'ORIGINE : un état sauvegardé n'est réutilisé que si elle est
// identique (sinon les données ont changé depuis, l'état sauvegardé est ignoré).
// Adresse de la vue effectif réel d'une équipe (relative : même page, voir la docstring Python).
export function teamHref(season, code) {
  return `?saison=${encodeURIComponent(season)}&equipe=${encodeURIComponent(code)}`;
}

export function fingerprint(data) {
  return data.season + "|" + data.teams.map((t) => t.code + ":" + t.slots.map((s) => (s == null ? "-" : s)).join(",")).join(";");
}

// État = { slots: {équipe: [player_id | null] x 6}, added: [player_id...] }. `added` = joueurs
// placés via la recherche : jamais de ⚠️ pour eux (le ⚠️ ne concerne que la composition d'origine).
export function initialState(data) {
  const slots = {};
  for (const t of data.teams) slots[t.code] = t.slots.map((s) => (s == null ? null : s));
  return { slots, added: [] };
}

function cloneState(state) {
  const slots = {};
  for (const [code, arr] of Object.entries(state.slots)) slots[code] = arr.slice();
  return { slots, added: state.added.slice() };
}

export function findPlayer(state, pid) {
  for (const [code, arr] of Object.entries(state.slots)) {
    const idx = arr.indexOf(pid);
    if (idx !== -1) return { team: code, idx };
  }
  return null;
}

export function removePlayer(state, team, idx) {
  const s = cloneState(state);
  s.slots[team][idx] = null;
  return s;
}

// Place d'un joueur dans la composition d'ORIGINE ({team, idx}), ou null s'il n'y est pas.
export function originSlot(data, pid) {
  for (const t of data.teams) {
    const idx = t.slots.indexOf(pid);
    if (idx !== -1) return { team: t.code, idx };
  }
  return null;
}

// `added` après l'arrivée du joueur pid dans la carte `team` : retiré s'il revient dans sa carte
// d'origine (quelle que soit sa place : il retrouve son ⚠️ éventuel), ajouté sinon.
function placeInAdded(s, data, pid, team) {
  const origin = originSlot(data, pid);
  const home = origin != null && origin.team === team;
  const i = s.added.indexOf(pid);
  if (home && i !== -1) s.added.splice(i, 1);
  else if (!home && i === -1) s.added.push(pid);
}

// Vrai mercato : un joueur déjà présent dans une AUTRE carte la quitte (son slot devient vide).
// Renvoie { state, kind: "same" | "free" | "transfer", from }. "same" = déjà dans cette carte :
// état inchangé.
export function addPlayer(state, data, team, idx, pid) {
  const current = findPlayer(state, pid);
  if (current && current.team === team) return { state, kind: "same", from: team };
  const s = cloneState(state);
  if (current) s.slots[current.team][current.idx] = null;
  s.slots[team][idx] = pid;
  placeInAdded(s, data, pid, team);
  return { state: s, kind: current ? "transfer" : "free", from: current ? current.team : null };
}

// Intervertit le slot idx avec son voisin de droite (0..4 ; 4 = P <-> 6e). Les étiquettes
// restent aux slots, le ⚠️ suit le joueur.
export function swapRight(state, team, idx) {
  if (!(idx >= 0 && idx < SLOT_LABELS.length - 1)) return state;
  const s = cloneState(state);
  const arr = s.slots[team];
  [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
  return s;
}

// Glisser-déposer du joueur du slot `from` sur le slot `to` ({team, idx}). Renvoie
// { state, kind, pid, other } :
//   - "none"     : slot de départ vide ou lâché sur sa propre place -> état inchangé (même objet) ;
//   - "move"     : vers une tuile vide de la même carte (l'ancienne place devient vide) ;
//   - "swap"     : sur un autre joueur de la même carte (les deux échangent leur place) ;
//   - "transfer" : vers une tuile vide d'une autre carte ;
//   - "trade"    : sur un joueur d'une autre carte (chacun prend la place de l'autre).
// Étiquettes fixes au slot. Un joueur qui change de carte entre dans `added` (plus de ⚠️), comme
// un transfert par la recherche, sauf s'il revient dans sa carte d'origine (retiré de `added`, voir
// placeInAdded) ; dans une même carte, `added` ne change pas (comme avec ⇄).
export function moveOrSwap(state, data, from, to) {
  const pid = state.slots[from.team][from.idx];
  const other = state.slots[to.team][to.idx];
  if (pid == null || (from.team === to.team && from.idx === to.idx)) {
    return { state, kind: "none", pid, other: null };
  }
  const s = cloneState(state);
  s.slots[to.team][to.idx] = pid;
  s.slots[from.team][from.idx] = other;
  const sameCard = from.team === to.team;
  if (!sameCard) {
    placeInAdded(s, data, pid, to.team);
    if (other != null) placeInAdded(s, data, other, from.team);
  }
  const kind = sameCard ? (other == null ? "move" : "swap") : (other == null ? "transfer" : "trade");
  return { state: s, kind, pid, other };
}

// Vitesse du défilement automatique pendant un glisser (pixels par image) : 0 hors des bandes de
// `edge` px en haut et en bas de l'écran, puis croissante jusqu'à `max` au bord (négative en haut).
export function autoScrollStep(y, viewportHeight, edge = 60, max = 18) {
  if (y < edge) return -Math.ceil(max * Math.min(1, (edge - y) / edge));
  if (y > viewportHeight - edge) return Math.ceil(max * Math.min(1, (y - (viewportHeight - edge)) / edge));
  return 0;
}

// Remet l'équipe dans sa composition d'origine. Un joueur d'origine transféré entre-temps dans
// une autre carte en est REPRIS (son slot là-bas devient vide) : renvoyé dans `returned` pour
// le toast. Les joueurs d'origine retrouvent leur ⚠️ éventuel (retirés de `added`). Un joueur
// venu d'ailleurs qui sort de la carte retourne à sa place d'origine dans une AUTRE carte si elle
// est vide (`restored`, toast, ⚠️ rétabli) ; sinon il sort de la grille.
export function resetTeam(state, data, team) {
  const orig = data.teams.find((t) => t.code === team).slots.map((s) => (s == null ? null : s));
  const s = cloneState(state);
  const returned = [];
  for (const pid of orig) {
    if (pid == null) continue;
    const current = findPlayer(s, pid);
    if (current && current.team !== team) {
      s.slots[current.team][current.idx] = null;
      returned.push({ pid, from: current.team });
    }
  }
  const evicted = s.slots[team].filter((pid) => pid != null && !orig.includes(pid));
  s.slots[team] = orig;
  s.added = s.added.filter((pid) => !orig.includes(pid));
  const restored = [];
  for (const pid of evicted) {
    const home = originSlot(data, pid);
    if (home && home.team !== team && s.slots[home.team][home.idx] == null) {
      s.slots[home.team][home.idx] = pid;
      placeInAdded(s, data, pid, home.team);
      restored.push({ pid, to: home.team });
    }
  }
  return { state: s, returned, restored };
}

export function isTeamModified(state, data, team) {
  const orig = data.teams.find((t) => t.code === team).slots;
  const cur = state.slots[team];
  return orig.some((pid, i) => (pid == null ? null : pid) !== cur[i]);
}

export function showWarning(state, missingIds, pid) {
  return missingIds.has(pid) && !state.added.includes(pid);
}

// Index de recherche sur tous les joueurs de la saison ([id, nom, équipe]).
export function buildSearchIndex(players) {
  return players.map(([id, name, team]) => ({
    id, name, team,
    hay: normalize(`${name} ${team}`),
    nName: normalize(name),
    nLast: normalize(lastName(name)),
  }));
}

// Tous les mots saisis doivent apparaître (nom ou code équipe) ; les noms/noms de famille qui
// COMMENCENT par la saisie passent devant, puis ordre alphabétique.
export function searchPlayers(index, query, limit = 15) {
  const q = normalize(query).trim();
  if (!q) return [];
  const tokens = q.split(/\s+/);
  const hits = index.filter((p) => tokens.every((tok) => p.hay.includes(tok)));
  const score = (p) => (p.nName.startsWith(q) || p.nLast.startsWith(q) ? 0 : 1);
  hits.sort((a, b) => score(a) - score(b) || a.name.localeCompare(b.name, "fr"));
  return hits.slice(0, limit);
}

export function addMessage(kind, playerName, targetName, fromName) {
  if (kind === "same") return `${playerName} est déjà dans l'effectif des ${targetName}.`;
  if (kind === "transfer") return `${playerName} rejoint les ${targetName} (quitte les ${fromName})`;
  return `${playerName} rejoint les ${targetName}`;
}

export function returnMessage(playerName, teamName, fromName) {
  return `${playerName} revient aux ${teamName} (quitte les ${fromName})`;
}

export function restoreMessage(playerName, teamName) {
  return `${playerName} retourne chez les ${teamName}`;
}

export function tradeMessage(nameA, nameB, codeA, codeB) {
  return `Échange : ${lastName(nameA)} ↔ ${lastName(nameB)} (${codeA} ↔ ${codeB})`;
}

// Stockage : localStorage si disponible, sinon repli en mémoire (tient jusqu'au rechargement).
// Chaque accès est protégé : navigation privée / stockage bloqué ne doivent jamais casser la page.
const memoryStore = new Map();

export function makeStorage(localStorageLike) {
  return {
    get(key) {
      try {
        if (localStorageLike) {
          const v = localStorageLike.getItem(key);
          if (v != null) return v;
        }
      } catch (e) { /* repli mémoire */ }
      return memoryStore.has(key) ? memoryStore.get(key) : null;
    },
    set(key, value) {
      memoryStore.set(key, value);
      try {
        if (localStorageLike) localStorageLike.setItem(key, value);
      } catch (e) { /* repli mémoire */ }
    },
  };
}

export function loadState(storage, data) {
  const raw = storage.get(STORAGE_PREFIX + data.season);
  if (raw) {
    try {
      const saved = JSON.parse(raw);
      const codes = data.teams.map((t) => t.code);
      const valid = saved && saved.fp === fingerprint(data) && saved.slots && Array.isArray(saved.added)
        && codes.every((c) => Array.isArray(saved.slots[c]) && saved.slots[c].length === SLOT_LABELS.length);
      if (valid) {
        const slots = {};
        for (const c of codes) slots[c] = saved.slots[c].map((s) => (s == null ? null : s));
        return { slots, added: saved.added.slice() };
      }
    } catch (e) { /* état illisible : on repart de l'origine */ }
  }
  return initialState(data);
}

export function saveState(storage, data, state) {
  storage.set(STORAGE_PREFIX + data.season, JSON.stringify({ fp: fingerprint(data), slots: state.slots, added: state.added }));
}

// ---------------------------------------------------------------------------------------------
// 2. Rendu DOM et interactions
// ---------------------------------------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text; // textContent, jamais innerHTML : noms non interprétés
  return node;
}

function actionButton(label, className, action, attrs = {}) {
  const b = el("button", className, label);
  b.type = "button";
  b.dataset.action = action;
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "title") b.title = v;
    else b.dataset[k] = String(v);
  }
  return b;
}

function safeLocalStorage() {
  try {
    const ls = window.localStorage;
    const probe = "__mercato_probe__";
    ls.setItem(probe, probe);
    ls.removeItem(probe);
    return ls;
  } catch (e) {
    return null;
  }
}

// Remonte la page en haut (la vue effectif réel doit s'ouvrir en haut, pas au niveau de la carte
// cliquée). Composant sans iframe : `document` est directement celui de la page Streamlit.
function scrollPageToTop() {
  const targets = document.querySelectorAll('section.main, [data-testid="stAppViewContainer"], [data-testid="stMain"]');
  targets.forEach((n) => { if (typeof n.scrollTo === "function") n.scrollTo({ top: 0, behavior: "instant" }); });
  if (typeof window.scrollTo === "function") window.scrollTo({ top: 0, behavior: "instant" });
}

function createGrid(host) {
  const root = el("div", "mg-root");
  const toolbar = el("div", "mg-toolbar");
  const resetAllBtn = actionButton("↺ Tout réinitialiser", "mg-btn mg-reset-all", "reset-all");
  toolbar.append(el("span", "mg-note", "Modifications enregistrées dans ce navigateur."), resetAllBtn);
  const grid = el("div", "mg-grid");
  const toasts = el("div", "mg-toasts");
  root.append(toolbar, grid, toasts);
  host.appendChild(root);

  const storage = makeStorage(safeLocalStorage());
  let data = null;
  let state = null;
  let playersById = new Map();
  let teamsByCode = new Map();
  let missingIds = new Set();
  let index = [];
  const cardNodes = new Map();
  let search = null;
  let confirmTimer = null;

  const playerName = (pid) => (playersById.get(pid) || { name: String(pid) }).name;
  const teamName = (code) => (teamsByCode.get(code) || { name: code }).name;

  function setData(newData) {
    data = newData;
    playersById = new Map(data.players.map(([id, name, team]) => [id, { id, name, team }]));
    teamsByCode = new Map(data.teams.map((t) => [t.code, t]));
    missingIds = new Set(data.missing);
    index = buildSearchIndex(data.players);
    state = loadState(storage, data);
    endDrag();
    closeSearch();
    cancelConfirm();
    renderAll();
  }

  function commit(newState, teamsToRender) {
    state = newState;
    saveState(storage, data, state);
    for (const code of new Set(teamsToRender)) renderCard(code);
  }

  function renderAll() {
    cardNodes.clear();
    grid.replaceChildren(...data.teams.map((t) => {
      const card = buildCard(t);
      cardNodes.set(t.code, card);
      return card;
    }));
  }

  function renderCard(code) {
    const old = cardNodes.get(code);
    const fresh = buildCard(teamsByCode.get(code));
    cardNodes.set(code, fresh);
    if (old) old.replaceWith(fresh);
  }

  function buildCard(team) {
    const card = el("div", "mg-card");
    const header = el("div", "mg-card-header");
    const ident = el("div", "mg-ident");
    if (team.logo) {
      const box = el("div", "mg-logo");
      const img = el("img");
      img.src = team.logo;
      img.alt = team.code;
      img.loading = "lazy";
      img.decoding = "async";
      box.append(img);
      ident.append(box);
    } else {
      ident.append(el("div", "mg-emblem", team.code));
    }
    const link = el("a", "mg-team-link");
    const arrow = el("span", "mg-team-arrow", "→");
    arrow.setAttribute("aria-hidden", "true");
    link.append(el("span", "mg-team-name", team.name), arrow);
    link.href = teamHref(data.season, team.code);
    link.title = `Voir l'effectif réel ${data.season} des ${team.name}`;
    link.dataset.action = "open-team";
    link.dataset.team = team.code;
    ident.append(link);
    const modified = isTeamModified(state, data, team.code);
    if (modified) {
      const mark = el("span", "mg-modified", "modifiée");
      mark.title = "Composition différente de l'origine";
      ident.append(mark);
    }
    const reset = actionButton("↺", "mg-btn mg-reset-team", "reset-team", { team: team.code, title: `Réinitialiser les ${team.name}` });
    reset.disabled = !modified;
    header.append(ident, reset);

    const row = el("div", "mg-slots");
    const slots = state.slots[team.code];
    const labels = displayLastNames(slots.map((pid) => (pid == null ? null : playerName(pid))));
    slots.forEach((pid, j) => {
      if (j === SLOT_LABELS.length - 1) row.append(el("div", "mg-spacer"));
      row.append(buildSlot(team, pid, j, labels[j]));
    });
    // Boutons sous les tuiles, placés directement dans la grille des slots (le CSS les range
    // par data-slot, voir .mg-x / .mg-swap) : ✕ centré sous sa tuile, ⇄ centré sur l'espace
    // entre les deux tuiles qu'il intervertit.
    slots.forEach((pid, j) => {
      if (pid != null) {
        row.append(actionButton("✕", "mg-btn mg-x", "remove", { team: team.code, slot: j, title: `Retirer ${playerName(pid)}` }));
      }
      if (j < SLOT_LABELS.length - 1) row.append(buildSwapButton(team, j));
    });
    card.append(header, row);
    return card;
  }

  // Libellés "AI" / "AF" autour du ⇄ : masqués par défaut, affichés seulement là où les deux
  // tuiles ne sont pas côte à côte (AI <-> AF sur écran étroit, voir le CSS).
  function buildSwapButton(team, j) {
    const b = actionButton("", "mg-btn mg-swap", "swap", { team: team.code, slot: j, title: `Intervertir ${SLOT_LABELS[j]} et ${SLOT_LABELS[j + 1]}` });
    b.append(el("span", "mg-swap-label", `${SLOT_LABELS[j]} `), "⇄", el("span", "mg-swap-label", ` ${SLOT_LABELS[j + 1]}`));
    return b;
  }

  function buildSlot(team, pid, j, displayName) {
    const cell = el("div", "mg-slot");
    cell.dataset.slot = String(j);
    cell.dataset.team = team.code; // cible du glisser-déposer (voir slotAt)
    if (pid == null) {
      const tile = actionButton("", "mg-tile mg-tile-empty", "add", { team: team.code, slot: j, title: "Ajouter un joueur" });
      tile.append(el("span", "mg-badge", SLOT_LABELS[j]), el("span", "mg-plus", "+"));
      cell.append(tile);
    } else {
      const full = playerName(pid);
      const tile = el("div", "mg-tile");
      tile.title = full;
      const img = el("img");
      const photo = headshotSources(data, pid);
      img.src = photo.src;
      // Portrait de la saison absent (signature en cours de saison...) : portrait actuel.
      if (photo.fallback) img.addEventListener("error", () => { img.src = photo.fallback; }, { once: true });
      img.alt = full;
      img.loading = "lazy";
      img.decoding = "async";
      img.draggable = false; // pas de glisser natif de l'image (il doublerait le nôtre)
      tile.append(img, el("span", "mg-badge", SLOT_LABELS[j]));
      if (showWarning(state, missingIds, pid)) {
        const warn = el("span", "mg-warning", "⚠️");
        warn.title = "Poste inconnu dans les données : étiquette approximative";
        tile.append(warn);
      }
      tile.append(el("div", "mg-name", displayName));
      cell.append(tile);
    }
    return cell;
  }

  function toast(message) {
    const t = el("div", "mg-toast", message);
    toasts.append(t);
    setTimeout(() => {
      t.classList.add("mg-toast-out");
      setTimeout(() => t.remove(), 300);
    }, 3500);
  }

  // --- Recherche (fenêtre unique, ouverte par un clic sur une tuile vide) ---
  function openSearch(team, slot) {
    closeSearch();
    const overlay = el("div", "mg-overlay");
    overlay.dataset.action = "close-search";
    const panel = el("div", "mg-panel");
    panel.dataset.action = "noop"; // un clic dans la fenêtre ne la ferme pas
    panel.setAttribute("role", "dialog");
    const head = el("div", "mg-panel-head");
    head.append(el("strong", null, "Ajouter un joueur"), actionButton("✕", "mg-btn", "close-search", { title: "Fermer" }));
    const input = el("input", "mg-input");
    input.type = "search";
    input.placeholder = "Rechercher un joueur...";
    input.autocomplete = "off";
    input.spellcheck = false;
    const list = el("div", "mg-results");
    panel.append(head, el("div", "mg-panel-caption", `${teamName(team)} — slot ${SLOT_LABELS[slot]}`), input, list);
    overlay.append(panel);
    root.append(overlay);
    search = { overlay, input, list, team, slot, results: [], active: 0 };
    input.addEventListener("input", updateResults);
    input.addEventListener("keydown", onSearchKey);
    updateResults();
    input.focus();
  }

  function updateResults() {
    if (!search) return;
    const q = search.input.value;
    search.results = searchPlayers(index, q);
    search.active = 0;
    renderResults(q);
  }

  function renderResults(q) {
    const { list, results, active } = search;
    if (!q.trim()) {
      list.replaceChildren(el("div", "mg-hint", "Tapez un nom (ex : jokic)"));
      return;
    }
    if (!results.length) {
      list.replaceChildren(el("div", "mg-hint", "Aucun joueur trouvé"));
      return;
    }
    list.replaceChildren(...results.map((p, i) => {
      const b = actionButton(`${p.name} (${p.team})`, "mg-result" + (i === active ? " is-active" : ""), "pick", { pid: p.id });
      return b;
    }));
  }

  function onSearchKey(ev) {
    if (!search) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      closeSearch();
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      const p = search.results[search.active];
      if (p) pick(p.id);
    } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const n = search.results.length;
      if (!n) return;
      search.active = (search.active + (ev.key === "ArrowDown" ? 1 : n - 1)) % n;
      renderResults(search.input.value);
      const activeNode = search.list.children[search.active];
      if (activeNode && activeNode.scrollIntoView) activeNode.scrollIntoView({ block: "nearest" });
    }
  }

  function closeSearch() {
    if (search) {
      search.overlay.remove();
      search = null;
    }
  }

  function pick(pid) {
    if (!search) return;
    const { team, slot } = search;
    closeSearch(); // fermeture automatique dès qu'un joueur est choisi
    const r = addPlayer(state, data, team, slot, pid);
    if (r.kind === "same") {
      toast(addMessage("same", playerName(pid), teamName(team)));
      return;
    }
    commit(r.state, r.from ? [team, r.from] : [team]);
    toast(addMessage(r.kind, playerName(pid), teamName(team), r.from ? teamName(r.from) : null));
  }

  // --- Resets ---
  function doResetTeam(team) {
    const r = resetTeam(state, data, team);
    commit(r.state, [team, ...r.returned.map((x) => x.from), ...r.restored.map((x) => x.to)]);
    for (const x of r.returned) toast(returnMessage(playerName(x.pid), teamName(team), teamName(x.from)));
    for (const x of r.restored) toast(restoreMessage(playerName(x.pid), teamName(x.to)));
    if (!r.returned.length && !r.restored.length) toast(`${teamName(team)} : composition d'origine rétablie`);
  }

  function cancelConfirm() {
    clearTimeout(confirmTimer);
    delete resetAllBtn.dataset.confirm;
    resetAllBtn.textContent = "↺ Tout réinitialiser";
  }

  function doResetAll() {
    if (resetAllBtn.dataset.confirm !== "1") {
      // Confirmation par second clic (pas de confirm() : bloquant, et parfois désactivé).
      resetAllBtn.dataset.confirm = "1";
      resetAllBtn.textContent = "Confirmer la réinitialisation ?";
      confirmTimer = setTimeout(cancelConfirm, 4000);
      return;
    }
    cancelConfirm();
    state = initialState(data);
    saveState(storage, data, state);
    renderAll();
    toast("Toutes les compositions ont été réinitialisées");
  }

  // Un seul écouteur pour toute la grille (délégation) : data-action sur l'élément cliqué.
  function onClick(ev) {
    const target = ev.target.closest ? ev.target.closest("[data-action]") : null;
    if (!target || !root.contains(target)) return;
    const { action, team } = target.dataset;
    const slot = Number(target.dataset.slot);
    switch (action) {
      case "remove": commit(removePlayer(state, team, slot), [team]); break;
      case "swap": commit(swapRight(state, team, slot), [team]); break;
      case "add": openSearch(team, slot); break;
      case "pick": pick(Number(target.dataset.pid)); break;
      case "close-search": closeSearch(); break;
      case "reset-team": doResetTeam(team); break;
      case "reset-all": doResetAll(); break;
      case "open-team": openTeam(ev, team); break;
      default: break;
    }
  }
  root.addEventListener("click", onClick);

  // --- Glisser-déposer d'une tuile remplie (Pointer Events : souris ET doigt) ---
  // Souris : démarre après DRAG_THRESHOLD px de mouvement (en dessous, c'est un clic). Doigt ou
  // stylet : démarre après un appui long de LONG_PRESS_MS sans bouger ; un mouvement avant (au-delà
  // de LONG_PRESS_SLOP) abandonne, pour laisser la page défiler. Pas de touch-action: none sur les
  // tuiles (elles couvrent presque tout l'écran d'un téléphone) : le défilement n'est bloqué
  // qu'une fois le glisser lancé, par preventDefault sur touchmove (écouteur non passif).
  const DRAG_THRESHOLD = 5;
  const LONG_PRESS_MS = 300;
  const LONG_PRESS_SLOP = 8;
  let drag = null;
  let suppressClick = false;

  function onPointerDown(ev) {
    if (drag || search || ev.button !== 0 || ev.isPrimary === false) return;
    const tile = ev.target.closest ? ev.target.closest(".mg-tile") : null;
    if (!tile || tile.classList.contains("mg-tile-empty") || tile.classList.contains("mg-ghost")) return;
    const cell = tile.closest(".mg-slot");
    if (!cell || !root.contains(cell)) return;
    drag = {
      pointerId: ev.pointerId,
      touch: ev.pointerType !== "mouse",
      from: { team: cell.dataset.team, idx: Number(cell.dataset.slot) },
      tile, startX: ev.clientX, startY: ev.clientY, x: ev.clientX, y: ev.clientY,
      active: false, timer: null, ghost: null, targetCell: null, to: null, scroller: null, raf: 0,
    };
    if (drag.touch) drag.timer = setTimeout(startDrag, LONG_PRESS_MS);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", endDrag);
    window.addEventListener("keydown", onDragKey);
  }

  function onPointerMove(ev) {
    if (!drag || ev.pointerId !== drag.pointerId) return;
    drag.x = ev.clientX;
    drag.y = ev.clientY;
    if (!drag.active) {
      const dist = Math.hypot(drag.x - drag.startX, drag.y - drag.startY);
      if (drag.touch && dist > LONG_PRESS_SLOP) endDrag(); // le doigt fait défiler la page
      else if (!drag.touch && dist > DRAG_THRESHOLD) startDrag();
      return;
    }
    ev.preventDefault();
    moveGhost();
    updateTarget();
  }

  function startDrag() {
    if (!drag || drag.active) return;
    clearTimeout(drag.timer);
    drag.active = true;
    const rect = drag.tile.getBoundingClientRect();
    drag.offsetX = drag.startX - rect.left;
    drag.offsetY = drag.startY - rect.top;
    const ghost = drag.tile.cloneNode(true);
    ghost.classList.add("mg-ghost");
    ghost.removeAttribute("title");
    ghost.style.width = `${rect.width}px`;
    ghost.style.height = `${rect.height}px`;
    root.append(ghost);
    drag.ghost = ghost;
    drag.tile.classList.add("mg-dragging");
    root.classList.add("mg-is-dragging");
    drag.scroller = scrollContainer();
    const nav = window.navigator;
    if (drag.touch && nav && typeof nav.vibrate === "function") {
      try { nav.vibrate(15); } catch (e) { /* vibration refusée : sans importance */ }
    }
    moveGhost();
    updateTarget();
    if (typeof window.requestAnimationFrame === "function") drag.raf = window.requestAnimationFrame(autoScroll);
  }

  function moveGhost() {
    drag.ghost.style.transform = `translate(${drag.x - drag.offsetX}px, ${drag.y - drag.offsetY}px)`;
  }

  // Cellule de slot sous le pointeur (le fantôme, en pointer-events: none, est ignoré). Composant
  // monté dans un shadow DOM : elementFromPoint du shadow root, celui du document renverrait l'hôte.
  function slotAt(x, y) {
    const rootNode = root.getRootNode();
    const finder = rootNode && typeof rootNode.elementFromPoint === "function" ? rootNode : document;
    if (typeof finder.elementFromPoint !== "function") return null;
    const hit = finder.elementFromPoint(x, y);
    const cell = hit && hit.closest ? hit.closest(".mg-slot") : null;
    return cell && root.contains(cell) ? cell : null;
  }

  // Surligne la tuile de destination, seulement si le lâcher y changerait quelque chose.
  function updateTarget() {
    const cell = slotAt(drag.x, drag.y);
    const to = cell ? { team: cell.dataset.team, idx: Number(cell.dataset.slot) } : null;
    const own = to && to.team === drag.from.team && to.idx === drag.from.idx;
    const next = to && !own ? cell : null;
    if (next === drag.targetCell) return;
    if (drag.targetCell) drag.targetCell.classList.remove("mg-drop-target");
    drag.targetCell = next;
    drag.to = next ? to : null;
    if (next) next.classList.add("mg-drop-target");
  }

  // Premier ancêtre qui défile vraiment (en sortant du shadow DOM par son hôte), sinon la page.
  function scrollContainer() {
    let node = root.parentNode;
    while (node) {
      if (node.nodeType === 11) { node = node.host; continue; } // shadow root -> hôte
      if (node.nodeType === 1) {
        const oy = window.getComputedStyle(node).overflowY;
        if ((oy === "auto" || oy === "scroll") && node.scrollHeight > node.clientHeight) return node;
      }
      node = node.parentNode;
    }
    return document.scrollingElement || document.documentElement;
  }

  // Défilement automatique près du bord haut ou bas de l'écran ; la tuile visée change alors sous
  // un pointeur immobile, d'où le nouveau calcul de la cible.
  function autoScroll() {
    if (!drag || !drag.active) return;
    const step = autoScrollStep(drag.y, window.innerHeight);
    if (step && drag.scroller) {
      drag.scroller.scrollTop += step;
      updateTarget();
    }
    drag.raf = window.requestAnimationFrame(autoScroll);
  }

  function onPointerUp(ev) {
    if (!drag || ev.pointerId !== drag.pointerId) return;
    if (!drag.active) { endDrag(); return; } // simple clic : laissé à onClick
    drag.x = ev.clientX;
    drag.y = ev.clientY;
    updateTarget();
    const { from, to } = drag;
    endDrag();
    // Le navigateur peut envoyer un click juste après le lâcher : ignoré (voir onClickCapture).
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
    if (to) drop(from, to);
  }

  function drop(from, to) {
    const r = moveOrSwap(state, data, from, to);
    if (r.kind === "none") return;
    commit(r.state, [from.team, to.team]);
    // Pas de toast dans une même carte (comme ⇄).
    if (r.kind === "transfer") toast(addMessage("transfer", playerName(r.pid), teamName(to.team), teamName(from.team)));
    else if (r.kind === "trade") toast(tradeMessage(playerName(r.pid), playerName(r.other), from.team, to.team));
  }

  // Fin du geste, avec ou sans lâcher : aussi pointercancel, Échap, changement de saison, démontage.
  function endDrag() {
    if (!drag) return;
    clearTimeout(drag.timer);
    if (drag.raf && typeof window.cancelAnimationFrame === "function") window.cancelAnimationFrame(drag.raf);
    if (drag.ghost) drag.ghost.remove();
    drag.tile.classList.remove("mg-dragging");
    if (drag.targetCell) drag.targetCell.classList.remove("mg-drop-target");
    root.classList.remove("mg-is-dragging");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", endDrag);
    window.removeEventListener("keydown", onDragKey);
    drag = null;
  }

  function onDragKey(ev) {
    if (drag && drag.active && ev.key === "Escape") endDrag();
  }

  function onTouchMove(ev) {
    if (drag && drag.active && ev.cancelable) ev.preventDefault();
  }

  // Appui long sur Android : menu contextuel (enregistrer l'image...) bloqué pendant le geste.
  function onContextMenu(ev) {
    if (drag) ev.preventDefault();
  }

  function onClickCapture(ev) {
    if (!suppressClick) return;
    suppressClick = false;
    ev.preventDefault();
    ev.stopPropagation();
  }

  root.addEventListener("pointerdown", onPointerDown);
  root.addEventListener("touchmove", onTouchMove, { passive: false });
  root.addEventListener("contextmenu", onContextMenu);
  root.addEventListener("click", onClickCapture, true);

  // Clic simple sur un nom d'équipe : pas de rechargement complet de la page (qui ferait perdre
  // la session Streamlit), Python bascule sur la vue effectif réel via st.query_params. Clic avec
  // Cmd/Ctrl/Maj/Alt (nouvel onglet/fenêtre) : comportement normal du lien, rien d'intercepté.
  let trigger = null;
  function openTeam(ev, team) {
    if (!trigger || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    scrollPageToTop();
    trigger("open_team", team);
  }

  return {
    setData,
    setTrigger(fn) { trigger = typeof fn === "function" ? fn : null; },
    destroy() {
      clearTimeout(confirmTimer);
      endDrag();
      closeSearch();
      root.removeEventListener("click", onClick);
      root.removeEventListener("pointerdown", onPointerDown);
      root.removeEventListener("touchmove", onTouchMove, { passive: false });
      root.removeEventListener("contextmenu", onContextMenu);
      root.removeEventListener("click", onClickCapture, true);
      root.remove();
    },
  };
}

// Appelée par Streamlit au montage, puis de nouveau quand `data` change (changement de saison),
// avec le MÊME parentElement : la grille existante est réutilisée, pas recréée.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  if (!data || !parentElement) return undefined;
  let grid = parentElement.__mercatoGrid;
  if (!grid) {
    grid = createGrid(parentElement);
    parentElement.__mercatoGrid = grid;
  }
  grid.setTrigger(setTriggerValue);
  grid.setData(data);
  return () => {
    grid.destroy();
    delete parentElement.__mercatoGrid;
  };
}
"""

# Enregistré à chaque rerun avec une définition identique : Streamlit ne le signale pas (seule
# une définition DIFFÉRENTE sous le même nom déclenche un avertissement).
mercato_grid = st.components.v2.component("mercato_grid", css=MERCATO_GRID_CSS, js=MERCATO_GRID_JS)

st.title("👥 Effectifs")
st.caption(
    "Clique sur le nom d'une équipe pour voir son effectif complet, ou refais les compositions "
    "avec ✕, ⇄ et +, ou en faisant glisser un joueur (appui long sur écran tactile)."
)
st.caption(f"Composition à 6 joueurs par équipe — saison régulière {season}.")


# Clé fixe (pas une clé par saison) : le composant n'est pas démonté au changement de saison, sa
# fonction JS est rappelée avec les nouvelles données. Seul le déclencheur open_team (clic simple
# sur un nom d'équipe) relance Python ; les autres clics de la grille, non. height="content" :
# hauteur du contenu, pas de barre de défilement interne. on_open_team_change : nécessaire pour
# déclarer le déclencheur ; sa valeur est lue dans le résultat (grid.open_team), PAS dans
# st.session_state["mercato_grid"] depuis le callback -- cette clé n'existe pas tant que le
# composant n'a jamais envoyé d'état (KeyError, repéré en test).
grid = mercato_grid(
    key="mercato_grid", data=prep["grid_data"], height="content", on_open_team_change=lambda: None
)
if grid.open_team:
    # Clic simple sur un nom d'équipe (setTriggerValue("open_team", code) côté JS) : l'adresse
    # passe à ?saison=..&equipe=.., que Streamlit pousse dans l'historique du navigateur -- le
    # rerun affiche la vue effectif réel, et Précédent ramène à la grille.
    st.query_params.update({"saison": season, "equipe": grid.open_team})
    st.rerun()

st.caption(
    "Composition = 6 joueurs avec le plus de minutes par match dans leur équipe de fin de "
    "saison, en ne comptant que les matchs joués avec cette équipe (seuils minimum de matchs "
    "pour écarter les petits échantillons). Étiquettes de poste attribuées dans l'ordre "
    "M/A/AI/AF/P après tri par groupe de poste (Extérieur, Ailier, Intérieur) : elles peuvent "
    "ne pas correspondre au poste exact du joueur. Le 5 majeur correspond aux 5 joueurs les "
    "plus utilisés, pas forcément au 5 de départ officiel."
)
st.caption(PHOTO_NOTICE)
st.caption(LOGO_NOTICE)
