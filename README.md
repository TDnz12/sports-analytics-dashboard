# NBA Salary vs Performance Dashboard

Dashboard interactif qui croise stats de jeu et salaires NBA, saison par saison ou sur l'historique complet. Construit avec Streamlit, architecture pensée pour accueillir d'autres sports sans réécrire le dashboard (le rugby est le prochain, voir la feuille de route).

**Démo en ligne :** https://sportsanalyticsdashboard.streamlit.app

## Fonctionnalités

- Scatter plot salaire vs performance, sur 30 saisons NBA (1996-97 à 2025-26)
- Vue combinée toutes saisons, badges MVP/DPOY/champion, mode saison régulière ou playoffs
- Radar de comparaison entre joueurs sur un ensemble de métriques normalisées par poste
- Normalisation en % du plafond salarial pour comparer des saisons éloignées dans le temps
- Page Effectifs : les 6 joueurs clés de chaque équipe, modifiables, et l'effectif réel complet de chaque saison (détails ci-dessous)

## Page Effectifs

Une carte par équipe avec ses 6 joueurs clés de la saison : le 5 majeur et le 6e homme, étiquetés M/A/AI/AF/P (meneur, arrière, ailier, ailier fort, pivot) puis 6e.

**Refaire les compositions.** Chaque carte se modifie à la main : ✕ retire un joueur, un clic sur une place vide ouvre une recherche pour en ajouter un (n'importe quel joueur de la saison, qui quitte alors son ancienne carte), ⇄ échange deux joueurs voisins, un joueur peut aussi être glissé vers une autre place, de sa carte ou d'une autre (appui long sur écran tactile : lâché sur une place vide il s'y installe, lâché sur un joueur les deux échangent leur place), ↺ remet une équipe dans son état d'origine et "Tout réinitialiser" remet toute la grille. Les modifications restent enregistrées dans le navigateur, saison par saison, même après un rechargement de la page.

**Comment la composition d'origine est choisie.** Chaque joueur est rattaché à l'équipe de son dernier match de la saison régulière, et ses minutes par match ne comptent que les matchs joués avec cette équipe : un joueur transféré en cours de saison n'apparaît que dans sa dernière équipe, avec ses vraies minutes là-bas. Pour écarter les petits échantillons, un joueur doit être éligible pour passer devant les autres, c'est-à-dire avoir joué au moins un quart des matchs de la saison avec son équipe, ou la moitié des matchs de son équipe depuis son arrivée (avec un minimum de 10 matchs, pour un transfert en cours de saison), ou un quart des matchs de la saison toutes équipes confondues (avec au moins 5 matchs dans sa dernière équipe). Les 6 éligibles avec le plus de minutes par match forment la carte. Les étiquettes de poste suivent un ordre fixe après un tri par groupe de poste (extérieurs, ailiers, intérieurs), elles peuvent donc ne pas correspondre au poste exact du joueur. Le détail est dans [METHODOLOGY.md](METHODOLOGY.md).

**Effectif réel.** Un clic sur le nom d'une équipe ouvre son effectif complet de la saison : une carte par joueur avec photo, points, rebonds, passes et PIE. Cette vue montre toujours le vrai effectif, jamais les modifications de la grille. Son adresse (`?saison=2024-25&equipe=BOS`) peut être partagée, et le bouton Précédent du navigateur ramène à la grille.

**Logos d'époque.** Chaque équipe apparaît avec le logo qu'elle portait cette saison-là (le dinosaure des Raptors en 2003-04, les SuperSonics à Seattle jusqu'en 2008, les Bobcats à Charlotte...). Les logos sont stockés dans le projet (`static/logos/nba/`), servis par Streamlit, et la table saison → logo est dans `data_sources/nba_logos.csv`, avec la source de chaque fichier. Pour les régénérer :

```bash
.venv/bin/python scripts/update_nba_logos.py --dry-run   # affiche la table, ne télécharge rien
.venv/bin/python scripts/update_nba_logos.py             # télécharge et réécrit logos + table
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run Dashboard.py
```

> Si ton dossier de projet est synchronisé avec iCloud Drive (réglage "Bureau et Documents" sur Mac), déplace plutôt le `.venv` hors du dossier synchronisé (`python3 -m venv ~/.venvs/nom-du-projet`). iCloud a tendance à évincer les milliers de petits fichiers d'un environnement virtuel vers le cloud, ce qui peut rendre chaque lancement très lent.

## Sources de données

Les stats de jeu viennent de `nba_api` (endpoints publics de stats.nba.com, pas de clé requise). Les salaires viennent de deux datasets Kaggle, combinés automatiquement selon la saison :

| Saisons | Dataset | Détails |
|---|---|---|
| 2010-11 → aujourd'hui | ratin21/nba-player-stats-and-salaries-2010-2025 | Pas de PER dans ce dataset, remplacé par le PIE (nba_api) comme métrique d'efficacité |
| 1996-97 → 2009-10 | iampunitkmryh/nba-players-details-198518 (licence CC0) | Comble le trou non couvert par le premier dataset |

1996-97 est la première saison couverte : c'est la plus ancienne où `nba_api` renvoie des données exploitables (1995-96 renvoie 0 ligne).

### Configurer l'accès Kaggle

Deux options, gratuites :

**Automatique (recommandé)** : crée un compte Kaggle, génère un token API (Settings → API → Create New Token), place `kaggle.json` dans `~/.kaggle/`. L'app télécharge chaque dataset une fois puis le met en cache.

**Manuelle** : télécharge les CSV directement depuis les pages Kaggle et dépose-les dans `data_cache/raw/nba/manual/` (et `manual_legacy/` pour le second dataset). L'app les détecte automatiquement.

Sans configuration, le dashboard fonctionne quand même : les stats de jeu s'affichent, seule la colonne salaire reste vide pour les saisons concernées.

### Normalisation en % du plafond salarial

Le plafond salarial NBA a été multiplié par plus de 6 entre 1996-97 (24,4 M$) et 2025-26 (154,6 M$), donc comparer des montants bruts entre saisons éloignées n'a pas grand sens. Le dashboard calcule aussi le salaire en % du plafond de la saison, sélectionnable comme n'importe quelle autre métrique.

## Pré-remplir le cache

Par défaut chaque saison est calculée au premier chargement, ce qui peut être lent. Pour pré-calculer les 30 saisons à l'avance (avant une démo par exemple) :

```bash
PYTHONPATH=. python scripts/prefill_cache.py            # saisons manquantes seulement
PYTHONPATH=. python scripts/prefill_cache.py --force     # tout recalculer
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .   # tests Python (fiabilité, table des logos, caches complets)
.venv/bin/python tests/apptest_effectifs.py           # page Effectifs de bout en bout avec AppTest (~1 min)
cd tests/js && npm install && npm test                 # JavaScript de la grille Effectifs (node + jsdom)
```

Les tests Python et AppTest lisent les données en cache dans `data_cache/` sans jamais les modifier. Les tests JavaScript testent directement le code de la grille tel qu'il est dans `pages/2_Effectifs.py`.

## Architecture

```
Dashboard.py                 # UI Streamlit, ne connaît que data_sources.SPORTS
pages/
  1_Radar_de_comparaison.py
  2_Effectifs.py              # grille des compositions + effectif réel
data_sources/
  base.py                     # schéma commun, cache parquet
  nba.py                      # logique spécifique NBA
  nba_logos.csv               # table saison -> logo d'époque
data_cache/
  raw/nba/                    # fichiers bruts
  processed/nba/              # données normalisées, en cache par saison
static/logos/nba/             # logos d'époque, servis par Streamlit (.streamlit/config.toml)
scripts/
  prefill_cache.py
  update_nba_logos.py
tests/                        # tests Python et AppTest
  js/                         # tests JavaScript
```

Ajouter un sport revient à créer `data_sources/<sport>.py` avec une fonction `get_player_stats()` et l'enregistrer dans `data_sources/__init__.py` — rien à changer dans `Dashboard.py`, le sélecteur de sport et les graphiques se construisent automatiquement à partir du registre.

## Méthodologie

Détail des choix de métriques, des pistes testées et abandonnées, et des limites connues : voir [METHODOLOGY.md](METHODOLOGY.md).

## Limites connues

- La jointure salaire/stats se fait sur le nom du joueur normalisé, de rares homonymes peuvent ne pas matcher (ligne alors exclue automatiquement du scatter).
- Le dataset de salaires récent s'arrête à sa dernière saison couverte ; les saisons plus récentes affichent les stats mais pas le salaire tant que le dataset n'est pas mis à jour.
- Aucune métrique défensive individuelle n'a été retenue : les stats hustle disponibles via `nba_api` se sont révélées peu discriminantes (testées contre les DPOY de plusieurs saisons, sans résultat concluant).

## Feuille de route

Le prochain sport sera le rugby, dans une version centrée sur la performance uniquement, sans comparaison salariale.

## Stack technique

Python, Streamlit, pandas, Plotly, nba_api, datasets Kaggle.

---

Logos : propriété de la NBA et de ses équipes, utilisés à titre non commercial.
