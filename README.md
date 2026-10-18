# Sports Analytics Dashboard : NBA et rugby

Dashboard interactif de stats de joueurs, construit avec Streamlit, pour deux sports. En NBA, il croise stats de jeu et salaires, saison par saison ou sur l'historique complet. En rugby (Top 14 et Pro D2), il compare la performance des joueurs, sans salaires. Le sport et la compétition se choisissent dans la barre latérale ; les pages se construisent à partir d'un registre commun des sports.

**Démo en ligne :** https://sportsanalyticsdashboard.streamlit.app

## Fonctionnalités

### NBA

- Scatter plot salaire vs performance, sur 30 saisons NBA (1996-97 à 2025-26)
- Vue combinée toutes saisons, badges MVP/DPOY/champion, mode saison régulière ou playoffs
- Radar de comparaison entre joueurs sur un ensemble de métriques normalisées par poste
- Normalisation en % du plafond salarial pour comparer des saisons éloignées dans le temps
- Page Effectifs : les 6 joueurs clés de chaque équipe, modifiables, et l'effectif réel complet de chaque saison (détails ci-dessous)

### Rugby

- Top 14 de 2021-22 à 2025-26, Pro D2 de 2022-23 à 2025-26, en saison complète (phases finales comprises) ou en phase régulière
- Dashboard : nuage de points entre deux stats au choix (totaux, par 80 minutes, pourcentages), filtres par équipe et par poste, vue toutes saisons
- Radar de comparaison par poste, jusqu'à 4 joueurs, avec des axes choisis selon leur fiabilité, sur 1 saison ou sur 3 saisons (la saison choisie et les 2 précédentes, totaux additionnés)
- La page Effectifs n'existe que pour la NBA

### Recherche de joueurs

Sur le Dashboard et le Radar, une seule case sert à chercher et à choisir les joueurs. La liste se filtre dans le navigateur à chaque lettre, sans recharger la page, en ignorant accents et majuscules, mots dans n'importe quel ordre : « gael », « fickou gael » et « doncic » trouvent Gaël Fickou et Luka Dončić. Flèches, Entrée et Échap au clavier. Sur le Dashboard, un joueur (croix pour le désélectionner) ; sur le Radar, jusqu'à 4 joueurs en pastilles. En rugby, chaque joueur apparaît sous la forme « Nom · Poste », avec le club entre parenthèses pour les homonymes.

Les règles de calcul (minutes, postes, seuils, radar) sont détaillées dans la partie rugby de [METHODOLOGY.md](METHODOLOGY.md).

## Page Effectifs (NBA uniquement)

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

Python 3.12 minimum est requis (3.13 recommandé, c'est la version de Streamlit Cloud) : `numpy==2.5.3` refuse de s'installer sous Python 3.11. Pour vérifier ta version :

```bash
python3 --version
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run Dashboard.py
```

> Si ton dossier de projet est synchronisé avec iCloud Drive (réglage "Bureau et Documents" sur Mac), déplace plutôt le `.venv` hors du dossier synchronisé (`python3 -m venv ~/.venvs/nom-du-projet`). iCloud a tendance à évincer les milliers de petits fichiers d'un environnement virtuel vers le cloud, ce qui peut rendre chaque lancement très lent.

## Sources de données

### NBA

Les stats de jeu viennent de `nba_api` (endpoints publics de stats.nba.com, pas de clé requise). Les salaires viennent de deux datasets Kaggle, combinés automatiquement selon la saison :

| Saisons | Dataset | Détails |
|---|---|---|
| 2010-11 → aujourd'hui | ratin21/nba-player-stats-and-salaries-2010-2025 | Pas de PER dans ce dataset, remplacé par le PIE (nba_api) comme métrique d'efficacité |
| 1996-97 → 2009-10 | iampunitkmryh/nba-players-details-198518 (licence CC0) | Comble le trou non couvert par le premier dataset |

1996-97 est la première saison couverte : c'est la plus ancienne où `nba_api` renvoie des données exploitables (1995-96 renvoie 0 ligne).

#### Configurer l'accès Kaggle

Deux options, gratuites :

**Automatique (recommandé)** : crée un compte Kaggle, génère un token API (Settings → API → Create New Token), place `kaggle.json` dans `~/.kaggle/`. L'app télécharge chaque dataset une fois puis le met en cache.

**Manuelle** : télécharge les CSV directement depuis les pages Kaggle et dépose-les dans `data_cache/raw/nba/manual/` (et `manual_legacy/` pour le second dataset). L'app les détecte automatiquement.

Sans configuration, le dashboard fonctionne quand même : les stats de jeu s'affichent, seule la colonne salaire reste vide pour les saisons concernées.

#### Normalisation en % du plafond salarial

Le plafond salarial NBA a été multiplié par plus de 6 entre 1996-97 (24,4 M$) et 2025-26 (154,6 M$), donc comparer des montants bruts entre saisons éloignées n'a pas grand sens. Le dashboard calcule aussi le salaire en % du plafond de la saison, sélectionnable comme n'importe quelle autre métrique.

### Rugby

Les stats de match viennent du flux InCrowd (rugbyviz) du Top 14 et du Pro D2 : compositions, stats par joueur, remplacements, cartons et actions de score. Le site ne fait aucun appel réseau pour le rugby : tout est lu dans `data_cache/`. Mise à jour, en local :

```bash
PYTHONPATH=. python scripts/rugby_download.py incrowd --comp top14   # JSON bruts, dans ~/rugby_raw_json (hors du dépôt)
PYTHONPATH=. python scripts/rugby_build.py --comp top14              # tables brutes et caches traités, avec un rapport de contrôle
PYTHONPATH=. python scripts/rugby_build.py --comp top14 --windows-only   # caches sur 3 saisons seuls, depuis les tables déjà construites
```

Même chose avec `--comp prod2`, puis on commite les fichiers de `data_cache/`. Le dossier des JSON peut être changé avec la variable d'environnement `RUGBY_JSON_DIR`.

## Pré-remplir le cache (NBA)

Par défaut chaque saison est calculée au premier chargement, ce qui peut être lent. Pour pré-calculer les 30 saisons à l'avance (avant une démo par exemple) :

```bash
PYTHONPATH=. python scripts/prefill_cache.py            # saisons manquantes seulement
PYTHONPATH=. python scripts/prefill_cache.py --force     # tout recalculer
```

C'est aussi la seule façon de mettre à jour les données : l'application en ligne n'a pas de bouton de rechargement, car Streamlit Cloud ne joint pas stats.nba.com. On lance le script en local, puis on commite les fichiers de `data_cache/`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .   # tests Python (NBA, rugby, moteur du radar, caches)
.venv/bin/python tests/apptest_dashboard.py           # Dashboard de bout en bout avec AppTest
.venv/bin/python tests/apptest_radar.py               # Radar de comparaison
.venv/bin/python tests/apptest_navigation.py          # navigation entre les 3 pages
.venv/bin/python tests/apptest_effectifs.py           # page Effectifs (~1 min)
cd tests/js && npm install && npm test                 # JavaScript de la grille Effectifs et de la recherche de joueurs (node + jsdom)
```

Les tests Python et AppTest lisent les données en cache dans `data_cache/` sans jamais les modifier. Les tests JavaScript testent directement le code de la grille tel qu'il est dans `pages/2_Effectifs.py`.

Avant de commiter un changement qui touche du code commun aux sports (pages, `radar_common.py`, `base.py`), vérifier que les pages NBA affichent exactement la même chose qu'avant :

```bash
.venv/bin/python scripts/instantanes_nba.py              # copie de travail contre HEAD
.venv/bin/python scripts/instantanes_nba.py --ref <commit>
```

Le script rend 11 situations NBA (Dashboard, Radar, Effectifs) dans le commit de référence et dans la copie de travail, puis compare tout ce qui est affiché : code de sortie 0 si tout est identique, sinon les différences sont listées.

## Architecture

```
Dashboard.py                 # UI Streamlit, ne connaît que data_sources.SPORTS
pages/
  1_Radar_de_comparaison.py
  2_Effectifs.py              # grille des compositions + effectif réel (NBA)
player_picker/                # recherche de joueurs (composant maison, JS et CSS) du Dashboard et du Radar
data_sources/
  base.py                     # schéma commun, cache parquet
  radar_common.py             # moteur du radar commun aux sports (z-score, centile, padding)
  nba.py                      # logique spécifique NBA
  nba_logos.csv               # table saison -> logo d'époque
  rugby/
    schema.py                 # compétitions, saisons, colonnes, seuils et axes du radar
    incrowd.py                # JSON InCrowd -> tables brutes, corrections de minutes et de scores
    minutes.py                # minutes reconstruites depuis les remplacements et les cartons
    positions.py              # poste principal, postes secondaires, poste mixte
    aggregate.py              # une ligne par joueur et par saison (totaux, par 80, clubs)
    stats.py                  # lecture des caches, noms affichés, métriques du Dashboard
    radar.py                  # axes et scores du radar rugby
data_cache/
  raw/nba/, raw/rugby/        # fichiers bruts
  processed/nba/, processed/rugby/  # données normalisées, en cache par saison
static/logos/nba/             # logos d'époque, servis par Streamlit (.streamlit/config.toml)
scripts/
  prefill_cache.py
  instantanes_nba.py          # comparaison des pages NBA avec un commit de référence
  update_nba_logos.py
  rugby_download.py           # téléchargement des JSON InCrowd (hors ligne)
  rugby_build.py              # construction des caches rugby
  rugby_calibrate.py          # calibration des seuils du radar rugby
tests/                        # tests Python et AppTest
  js/                         # tests JavaScript
```

Ajouter un sport revient à créer `data_sources/<sport>.py` (ou un dossier, comme `data_sources/rugby/`) avec une fonction `get_player_stats()` et l'enregistrer dans `data_sources/__init__.py`, sans rien changer dans `Dashboard.py` : le sélecteur de sport et les graphiques se construisent automatiquement à partir du registre.

## Méthodologie

Détail des choix de métriques, des pistes testées et abandonnées, et des limites connues : voir [METHODOLOGY.md](METHODOLOGY.md).

## Limites connues

NBA :

- La jointure salaire/stats se fait sur le nom du joueur normalisé, de rares homonymes peuvent ne pas matcher (ligne alors exclue automatiquement du scatter).
- Le dataset de salaires récent s'arrête à sa dernière saison couverte ; les saisons plus récentes affichent les stats mais pas le salaire tant que le dataset n'est pas mis à jour.
- Aucune métrique défensive individuelle n'a été retenue : les stats hustle disponibles via `nba_api` se sont révélées peu discriminantes (testées contre les DPOY de plusieurs saisons, sans résultat concluant).

Rugby :

- Le match d'accès entre le Top 14 et la Pro D2 n'est pas dans les données.
- La source écrit presque tous les noms sans accents ; seuls les noms vérifiés à la main sont corrigés.
- Pas de stats de mêlée ni de rucks par joueur, pas d'âge, de taille ni de poids.

Détail et autres limites : [METHODOLOGY.md](METHODOLOGY.md).

## Feuille de route

Prochaine étape : le Six Nations (source ESPN), avec la même page Dashboard et le même radar.

## Stack technique

Python, Streamlit, pandas, Plotly, nba_api, datasets Kaggle, flux InCrowd (rugby).

---

Logos : propriété de la NBA et de ses équipes, utilisés à titre non commercial.
