# Méthodologie détaillée

Ce document détaille les choix méthodologiques et leurs itérations, pour qui veut le détail complet au-delà du README.

## Mode "Toutes les saisons"

En plus du sélecteur saison par saison, le dashboard propose une vue combinée ("Toutes les
saisons (1996-97 → 2025-26)" dans le sélecteur) qui charge et concatène l'intégralité de
`sport.seasons` — chaque joueur y apparaît comme un point distinct par saison jouée.

Une saison dont le salaire est indisponible n'empêche pas d'afficher les autres : elle apparaît
simplement avec cette colonne vide plutôt que de faire échouer tout le mode combiné.

## Fiabilité (% de matchs joués, 3 dernières saisons)

Métrique `reliability_pct` = (somme des matchs joués par le joueur) / (somme des matchs
possibles de la ligue) sur la saison affichée et les `RELIABILITY_LOOKBACK_SEASONS - 1 = 2`
précédentes disponibles (`data_sources/nba._fetch_reliability`). "Matchs possibles" vient du
nombre réel de matchs joués par l'équipe qui en a joué le plus cette saison-là
(`LeagueDashTeamStats`), pas d'un 82 supposé — certaines saisons sont raccourcies (lockout
2011-12 : 66 matchs ; COVID 2019-20 : 64-75 selon l'équipe ; 2020-21 : 72 matchs). Plafonnée à
100% (quelques joueurs ressortaient légèrement au-dessus, probablement les matchs de Play-In
comptés différemment entre `LeagueDashPlayerStats` et `LeagueDashTeamStats`).

Une recrue avec moins de 3 saisons d'historique n'est sommée que sur les saisons où elle a
effectivement joué (`_seasons_lookback` s'arrête à `EARLIEST_SUPPORTED_SEASON_START_YEAR`)
plutôt que de planter ou de fausser le ratio avec des saisons inexistantes.

Mise en cache par saison, comme le reste — avec une précaution supplémentaire : si une des 3
saisons de la fenêtre échoue à se charger (ex: timeout réseau), la fiabilité est laissée vide
pour ce chargement (jamais une valeur calculée sur 2 saisons sur 3, donc fausse) et **rien n'est
mis en cache**, ni le résultat partiel, ni les données de la saison qui l'utilisent, pour ne pas
figer une donnée incomplète comme si elle était définitive — le prochain chargement retente les
saisons manquantes au lieu de rester bloqué sur un résultat dégradé.

Le cache disque (`data_cache/processed/nba/`) est versionné (`PROCESSED_SCHEMA_VERSION` dans
`nba.py`) : si la logique de calcul change (nouvelle colonne, nouveau calcul dérivé...), un
cache écrit sous une version différente est automatiquement ignoré et recalculé, sans besoin de
relancer quoi que ce soit à la main. Il n'y a pas de rechargement depuis l'interface : Streamlit
Cloud ne joint pas stats.nba.com. Les données se mettent à jour en local avec
`scripts/prefill_cache.py` (voir README), puis les caches sont versionnés dans git.

## Composition des effectifs (page Effectifs)

La carte de chaque équipe montre 6 joueurs de la saison régulière (jamais les playoffs) :
`data_sources/nba.get_mercato_lineup`.

**Rattachement et minutes.** Tout est recalculé depuis le journal des matchs joueur par joueur
(`LeagueGameLog`), pas depuis les moyennes de la saison : un joueur transféré a une moyenne
mélangée entre ses équipes (Gordon Hayward 2023-24 ressortait à 24,4 min/match toutes équipes
confondues, alors qu'il ne jouait qu'environ 17 min/match une fois à OKC). Chaque joueur est
rattaché à l'équipe de son dernier match de la saison, et ses minutes/match ne comptent que les
matchs joués avec elle. Il n'apparaît donc que dans une seule carte. Un joueur sans aucun match
cette saison n'apparaît nulle part.

**Éligibilité.** Un joueur est éligible s'il remplit au moins un de ces trois critères :
1. au moins 25% des matchs possibles de la saison avec son équipe de fin de saison ;
2. au moins 50% des matchs de son équipe depuis son premier match avec elle, et au moins 10
   matchs avec elle — pour un titulaire arrivé en cours de saison (Kyrie Irving, Dallas
   2022-23 : une vingtaine de matchs sur les 24 restants après son arrivée, sous les 25% de la
   saison) ; le plancher de 10 matchs évite de rendre éligible un contrat de 10 jours qui joue 3
   des 4 derniers matchs ;
3. au moins 25% des matchs de la saison toutes équipes confondues, et au moins 5 matchs avec
   son équipe de fin de saison — pour un joueur établi dont le passage dans sa dernière équipe
   est court (Kevin Durant, Phoenix 2022-23 : 8 matchs à Phoenix après une blessure, 47 sur la
   saison).

Les éligibles passent toujours devant les non-éligibles, quelles que soient leurs minutes ; si
une équipe a moins de 6 éligibles, les places restantes sont comblées par ses autres joueurs,
par minutes/match décroissantes. Les critères 2 et 3 élargissent seulement qui est éligible :
le classement, lui, reste basé sur les minutes/match avec l'équipe de fin de saison.

**Étiquettes de poste.** Les 5 premiers sont triés par groupe de poste (extérieurs, puis
ailiers, puis intérieurs, minutes décroissantes dans chaque groupe) et reçoivent les étiquettes
M/A/AI/AF/P dans cet ordre fixe, le 6e homme étant étiqueté "6e". Ce n'est pas le poste réel du
joueur : une équipe qui aligne 3 extérieurs aura 3 joueurs étiquetés M/A/AI. Compromis assumé,
plutôt qu'un système de quotas qui écarterait un joueur pour forcer un équilibre 2/2/1. Le 5
majeur est donc celui des 5 joueurs les plus utilisés, pas forcément le 5 de départ officiel.

## Radar de comparaison

Chaque axe est un z-score par poste (Intérieur / Ailier / Extérieur), calculé sur les joueurs
de la saison ayant au moins 15 matchs (4 en playoffs) : `data_sources/nba.compute_radar_scores`.
Le mode Indice ramène ce z-score, limité à ±3, sur 0-100 ; le mode Centile donne le rang dans le
poste. Jusqu'à 4 joueurs peuvent être comparés.

**Protection du ballon.** L'axe s'appelait "Sécurité de balle" et utilisait les pertes de balle
par match brutes, qui suivent surtout le volume de jeu (corrélation +0,78 avec les minutes en
2024-25) : Dončić, Jokić et Wembanyama étaient tout en bas, des remplaçants à 5 minutes par match
tout en haut. Il utilise désormais le TOV%, la part des possessions utilisées par le joueur qui
se terminent en perte de balle. Le TOV% exact (pertes / (tirs + 0,44 lancers francs + pertes))
n'est pas dans les caches ; il est estimé à partir de l'USG%, qui y est :
`TOV% ≈ 41,5 × pertes/match / (USG% × minutes/match)`. Contrôle sur 2024-25 contre le TOV% exact
(tirs et lancers francs du dataset Kaggle, 444 joueurs) : corrélation 0,995, écart médian 0,24
point, et plus aucun lien avec les minutes (corrélation -0,13). La constante ne change que la
valeur affichée, pas les scores ; sur les saisons anciennes, au rythme de jeu plus lent, cette
valeur peut être décalée d'environ 10 %. Le ratio passes décisives / pertes a été écarté : il
mélange création et protection du ballon (Wembanyama au 28e centile) et devient instable quand
les pertes sont rares.

**Tir extérieur et lancers francs.** Un pourcentage brut classe en tête les joueurs qui tirent
très peu (Matt Ryan à 100 % aux lancers francs en 2024-25, sur 2 tentatives). La position sur le
radar utilise donc un pourcentage ajusté par régression vers la moyenne ("padding", Kostya
Medvedovsky, "NBA Stabilization Rates and the Padding Approach", kmedved.com, 2020) :
`(réussis + P × moyenne du poste) / (tentatives + P)`, avec P = 242 pour les tirs à 3 points et
P = 156 pour les lancers francs. La moyenne est celle du poste du joueur (Intérieur / Ailier /
Extérieur), sur la saison et le type de stats choisis (total des réussis / total des tentatives),
pour rester cohérente avec le z-score par poste. Un faible volume est ainsi ramené vers la
moyenne de son poste (un 2/2 aux lancers francs donne presque exactement cette moyenne), un gros
volume garde son vrai niveau. Le z-score et le centile sont calculés sur ce pourcentage ajusté ;
le tableau et le survol affichent le vrai pourcentage et le nombre de tentatives. Les tentatives
exactes viennent de `LeagueDashPlayerStats` en mode Totals (`_fetch_shooting_totals`, caches
`shooting_<saison>[_playoffs]`).

**Volume minimum.** Avec très peu de tentatives, le pourcentage ajusté n'est presque que la moyenne
du poste et fait passer un non-tireur pour un tireur moyen : en 2020-21, Rudy Gobert (0/4 à 3
points) était ramené à 34,5 % (indice 45) et Ben Simmons (3/10) à 36,3 % (indice 50). Sous
1 tentative à 3 points par match (`MIN_FG3A_PER_GAME`) ou 0,5 lancer franc par match
(`MIN_FTA_PER_GAME`), calculé sur les matchs de la période affichée (donc aussi en playoffs),
l'axe est vide, comme sans aucune tentative, et le joueur sort de la population de référence de
cet axe. Le tableau garde le vrai pourcentage et les tentatives, avec "NC" (non classé) à la place
du score (`0.0% (4 tent.)  ·  NC`, ou `0 tent.  ·  NC` sans aucune tentative), et le survol du cercle creux indique "volume trop faible (4 tentatives en 71 matchs)". Part des
joueurs de référence sous chaque seuil :

| Saison | Type | 3PT < 1/match | LF < 0,5/match |
|---|---|---|---|
| 2004-05 | saison régulière | 53 % | 6 % |
| 2004-05 | playoffs | 48 % | 16 % |
| 2014-15 | saison régulière | 38 % | 10 % |
| 2014-15 | playoffs | 37 % | 15 % |
| 2024-25 | saison régulière | 20 % | 15 % |
| 2024-25 | playoffs | 23 % | 24 % |

Le seuil à 3 points écarte surtout les intérieurs qui ne tirent pas de loin (48 sur 96 en 2024-25,
la moitié de la ligue en 2004-05, reflet de l'époque). Pour les lancers francs, un seuil de 1 par
match écartait 38 % des joueurs de référence 2024-25, dont de bons tireurs qui obtiennent peu de
fautes (Tyus Jones, 51/57, 0,70 tentative par match) : d'où 0,5.

**Limites connues.** Scoring, Passe, Rebond, Interceptions et Contres sont des valeurs par match :
elles favorisent les joueurs qui jouent beaucoup, ce qui est assumé pour un radar de production.

## Métrique défensive individuelle (piste abandonnée)

Une tentative a été faite pour intégrer une métrique de "défense" individuelle
en complément des métriques offensives (PIE, impact hors scoring), basée sur
les statistiques "hustle" disponibles via nba_api (tirs contestés, déflections,
charges provoquées).

Trois constructions ont été testées :
1. Somme brute (tirs contestés + déflections)
2. Composite standardisé (z-scores) : tirs contestés + déflections + charges
   provoquées, par minute jouée
3. Le même composite, découpé par groupe de poste (intérieurs vs extérieurs)

Critère de validation retenu : un joueur élu Défenseur de l'Année (DPOY) doit
apparaître dans le haut de classement de sa saison. Testé sur Rudy Gobert
(2023-24), Jaren Jackson Jr. (2022-23) et Giannis Antetokounmpo (2019-20).

Résultat : échec dans les trois cas. Le plus flagrant : JJJ n'apparaît même
pas dans le top 5 des intérieurs sur la saison exacte où il a été élu DPOY.

Cause probable : les stats "hustle" par minute favorisent structurellement les
joueurs à haute activité (ailiers/arrières qui multiplient les contests et
déflections), pas les pivots qui défendent par positionnement et dissuasion
au cercle (ce que ces stats ne captent pas). La métrique propriétaire DBPM
(Basketball-Reference) capterait probablement mieux cet aspect, mais son
scraping est exclu par la politique du projet (voir README).

nba_api expose aussi LeagueDashPtDefend (défense par tracking), mais cet
endpoint s'est révélé peu fiable dans nos tests (JSONDecodeError, 3/3 essais).

Conclusion : aucune métrique défensive individuelle n'a été ajoutée au dashboard.
À réévaluer si LeagueDashPtDefend devient exploitable, ou si une autre source
de données fiable apparaît.
