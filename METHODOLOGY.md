# Méthodologie détaillée

Ce document détaille les choix méthodologiques et leurs itérations, pour qui veut le détail complet au-delà du README.

Il a deux parties : la NBA (les sections ci-dessous jusqu'à la métrique défensive), puis le
[rugby](#rugby-top-14-et-pro-d2) (Top 14 et Pro D2).

## Mode "Toutes les saisons"

En plus du sélecteur saison par saison, le dashboard propose une vue combinée ("Toutes les
saisons (1996-97 → 2025-26)" dans le sélecteur) qui charge et concatène l'intégralité de
`sport.seasons`. Chaque joueur y apparaît comme un point distinct par saison jouée.

Une saison dont le salaire est indisponible n'empêche pas d'afficher les autres : elle apparaît
simplement avec cette colonne vide plutôt que de faire échouer tout le mode combiné.

## Fiabilité (% de matchs joués, 3 dernières saisons)

Métrique `reliability_pct` = (somme des matchs joués par le joueur) / (somme des matchs
possibles de la ligue) sur la saison affichée et les `RELIABILITY_LOOKBACK_SEASONS - 1 = 2`
précédentes disponibles (`data_sources/nba._fetch_reliability`). "Matchs possibles" vient du
nombre réel de matchs joués par l'équipe qui en a joué le plus cette saison-là
(`LeagueDashTeamStats`), pas d'un 82 supposé, car certaines saisons sont raccourcies (lockout
2011-12 : 66 matchs ; COVID 2019-20 : 64-75 selon l'équipe ; 2020-21 : 72 matchs). Plafonnée à
100% (quelques joueurs ressortaient légèrement au-dessus, probablement les matchs de Play-In
comptés différemment entre `LeagueDashPlayerStats` et `LeagueDashTeamStats`).

Une recrue avec moins de 3 saisons d'historique n'est sommée que sur les saisons où elle a
effectivement joué (`_seasons_lookback` s'arrête à `EARLIEST_SUPPORTED_SEASON_START_YEAR`)
plutôt que de planter ou de fausser le ratio avec des saisons inexistantes.

Mise en cache par saison, comme le reste, avec une précaution supplémentaire : si une des 3
saisons de la fenêtre échoue à se charger (ex: timeout réseau), la fiabilité est laissée vide
pour ce chargement (jamais une valeur calculée sur 2 saisons sur 3, donc fausse) et **rien n'est
mis en cache**, ni le résultat partiel, ni les données de la saison qui l'utilisent, pour ne pas
figer une donnée incomplète comme si elle était définitive : le prochain chargement retente les
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
   matchs avec elle, pour un titulaire arrivé en cours de saison (Kyrie Irving, Dallas
   2022-23 : une vingtaine de matchs sur les 24 restants après son arrivée, sous les 25% de la
   saison) ; le plancher de 10 matchs évite de rendre éligible un contrat de 10 jours qui joue 3
   des 4 derniers matchs ;
3. au moins 25% des matchs de la saison toutes équipes confondues, et au moins 5 matchs avec
   son équipe de fin de saison, pour un joueur établi dont le passage dans sa dernière équipe
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

# Rugby (Top 14 et Pro D2)

**Données arrêtées à la fin de la saison 2025-26** : dernier match du Pro D2 le 6 juin 2026,
finale du Top 14 le 27 juin 2026.

## Source et saisons

Les stats viennent du flux InCrowd (rugbyviz) : compositions, stats par joueur et par match,
remplacements, cartons et actions de score. Les données sont téléchargées une fois en local,
puis mises en cache dans `data_cache/` : le site ne fait aucun appel réseau pour le rugby.

| Compétition | Saisons | Matchs par saison |
|---|---|---|
| Top 14 | 2021-22 à 2025-26 | 187 (182 de phase régulière, 26 journées, et 5 de phases finales) |
| Pro D2 | 2022-23 à 2025-26 | 245 (240 de phase régulière, 30 journées, et 5 de phases finales) |

Les 5 matchs de phases finales sont les 2 barrages, les 2 demi-finales et la finale. Un match est
classé en phase finale par son numéro de journée (au-delà de 26 ou de 30), pas par le type de
journée de la source, qui range les phases finales du Top 14 2021-22 en phase régulière.

Deux périodes au choix : « saison complète » (phases finales comprises, par défaut) et « phase
régulière ».

## Minutes jouées

La source donne les minutes de chaque joueur sur une base de 80, temps d'exclusion déduit. Elles
sont contrôlées équipe par équipe : la somme des minutes d'une équipe doit valoir 15 x 80 =
1 200 (15 x 100 en prolongation), moins le temps d'exclusion de ses joueurs, à 5 minutes près.

Les minutes sont reconstruites à partir des remplacements et des cartons dans deux cas :
- en prolongation, toujours : la source y est fausse (finale du Top 14 2024-25 : 1 557 minutes
  pour Bordeaux-Bègles au lieu de 1 480, la reconstruction en donne 1 481) ;
- quand la somme de l'équipe sort de la tolérance alors que la reconstruction y entre.

Règles de la reconstruction : les titulaires entrent à 0, chaque sortie ferme un passage sur le
terrain et chaque entrée en ouvre un (retours après protocole commotion compris). Un carton jaune
retire les 10 minutes d'exclusion, un rouge ferme le passage.

Sur les 9 saisons, 29 équipes-matchs (667 lignes joueur-match) ont des minutes reconstruites.
Une minute impossible devient inconnue au lieu d'être gardée : c'est le cas d'une seule ligne,
un remplaçant de Brive en Pro D2 2023-24 (Julien Delannoy), à qui la source donnait -10 minutes.

## Scores recomptés et compteurs corrigés

- **Scores perdus par la source.** Dans 16 équipes-matchs sur les 9 saisons (surtout en Pro D2
  2023-24 et 2024-25), les points des joueurs ne redonnent pas le score officiel. Les essais,
  transformations, pénalités, drops et points de chaque joueur y sont recomptés à partir des
  actions de score, seulement si le recomptage redonne exactement le score officiel.
- **Compteurs contradictoires.** 19 lignes joueur-match ont des compteurs (essais, coups de pied)
  qui contredisent à la fois les points de la source et les actions de score. Comme les points
  et les actions de score concordent, les compteurs sont repris des actions de score (exemple :
  2 essais rendus à Chinarro). 14 autres lignes, où ce sont les actions de score qui se
  trompent, gardent les chiffres de la source.
- Un essai de pénalité (7 points) revient à l'équipe, jamais à un joueur.

## Points

Les points d'un joueur sont ses **points totaux, essais compris**. Les classements officiels de
réalisateurs ne comptent souvent que les points au pied : l'écart vaut alors 5 points par essai.
Exemple, Top 14 2023-24 en phase régulière : Melvyn Jaminet a 208 points ici et 188 au
classement officiel, soit ses 4 essais.

## « A joué »

Un joueur a joué un match s'il a des minutes au-dessus de 0, ou au moins une stat de jeu
(plaquage, course, passe, points...). Les cartons ne comptent pas : un remplaçant peut en recevoir
sans entrer en jeu. 22 lignes à 0 minute avec des stats, et la ligne aux minutes inconnues, sont
ainsi comptées comme jouées.

## Stats par 80 minutes

Total divisé par les minutes jouées, multiplié par 80. Le calcul se fait stat par stat, sur les
seuls matchs où les minutes sont connues et au-dessus de 0 et où la stat est connue : les lignes
à 0 minute ou aux minutes inconnues comptent dans les totaux, pas dans les par 80. Les
pourcentages sont toujours calculés sur les totaux de la saison, jamais en moyenne de
pourcentages par match. Le % au pied compte les transformations et les pénalités, sans les
drops.

## Postes

Le poste est calculé sur la saison complète : il est le même dans les deux périodes.
- **Poste principal** : le poste le plus porté comme titulaire (maillots 1 à 15). En cas
  d'égalité : celui où le joueur a le plus de minutes, puis le plus récent.
- **Postes secondaires** : les autres postes portés comme titulaire, avec leur part des
  titularisations.
- **Poste mixte** : badge affiché quand le poste principal pèse moins de 60 % des
  titularisations (18 à 28 joueurs par saison en Top 14 et 19 à 33 en Pro D2, parmi ceux qui
  ont au moins 5 titularisations). Les
  maillots de la source sont justes : Paul Boudehent a bien été aligné en deuxième ligne par
  La Rochelle, et Charles Ollivon titulaire en n° 4 avec Toulon, ce qui fait d'eux des « postes
  mixtes ».
- **Joueur jamais titulaire** : poste déduit du maillot de banc le plus porté. Le 16 est
  talonneur, le 17 et le 18 sont piliers (règle de remplacement de la première ligne). Du 19 au
  23, rien ne permet de déduire le poste (bancs à 5 avants et 3 arrières, ou 6 et 2) : le joueur
  est « Indéterminé » et n'a pas de radar. C'est le cas de 36 à 52 joueurs par saison, avec au
  plus 333 minutes sur la saison : aucun n'atteindrait le seuil de la population de référence.

## Club principal

Un joueur qui a changé de club en cours de saison est rangé dans le club où il a joué le plus de
minutes. En cas d'égalité : celui où il a joué le plus de matchs, puis le plus récent. La colonne
« Clubs » liste tous ses clubs avec le nombre de matchs joués dans chacun, et le filtre par équipe
le trouve dans chacun d'eux.

## Disponibilité

Matchs sur la feuille de match divisés par les matchs de son équipe entre son premier et son
dernier match de la saison (additionnés club par club s'il en a changé). Les absences ne se
distinguent pas : blessure, choix de l'entraîneur ou sélection internationale.

## Radar de comparaison

**Population de référence.** Chaque axe est un z-score calculé dans le poste du joueur, sur les
joueurs de la même compétition, saison et période qui ont joué au moins 5 matchs et 520 minutes.
520 minutes est le plus grand seuil qui garde, dans chaque poste et chaque saison, au moins 12
joueurs et 70 % des minutes jouées ; au-delà, les piliers (39 minutes par match en médiane)
passent sous 70 %. Les 5 matchs n'ont pas d'effet à 520 minutes, mais restent pour le badge
« Échantillon court », affiché pour les joueurs sous ces seuils. Un avertissement apparaît sous
le radar quand un poste compte moins de 10 joueurs de référence.

**Score.** Le mode Indice borne le z-score à ±3 puis le ramène sur 0-100. Le mode Centile donne le
rang du joueur parmi les joueurs de référence de son poste. Les ex aequo partagent leur rang
moyen : sinon, les 27 deuxièmes lignes à 0 touche volée sur 70 (Pro D2 2025-26) étaient tous au
39e centile, au lieu du 20e. Le centile est vide quand le score l'est (référence trop petite ou
sans écart entre joueurs).

**Choix des axes.** Un axe n'est sur le radar d'un poste que si sa fiabilité, sur une saison de
520 minutes, atteint 0,4 pour ce poste. La fiabilité mesure la part des écarts entre joueurs qui
ne vient pas du hasard : elle compare deux moitiés de saison du même joueur (méthode
« split-half »).

| Postes | Axes |
|---|---|
| Tous | Plaquages, % plaquages réussis (sauf l'arrière), Mètres, % gain de ligne |
| Avants | + Courses, Grattages, Défenseurs battus, Passes |
| Arrières | + Défenseurs battus, Courses, Mètres au pied |
| Pilier, talonneur, troisième ligne centre | + Passes après contact |
| Deuxième ligne | + Touches gagnées, Touches volées |
| Troisième ligne aile | + Touches gagnées |
| Demi de mêlée, demi d'ouverture, arrière | + Passes |
| Centre | + Passes après contact, Passes |
| Ailier | + Passes après contact |

L'arrière n'a pas l'axe % plaquages réussis : il tente trop peu de plaquages sur une saison
(fiabilité 0,32). Les stats par 80 du radar sont les valeurs brutes. Quand les joueurs comparés
ont des postes différents, seuls les axes communs à tous leurs postes restent : chaque axe affiché
est ainsi fiable pour chacun. Une note apparaît sous 5 axes en commun.

Restent hors radar, dans le tableau et la fiche du joueur : pénalités concédées et ballons perdus
par 80 (« peu fiable sur une saison »), franchissements, essais, % au pied.

## Radar sur 3 saisons

Sur la page Radar, le choix « Durée » passe de 1 saison (par défaut) à 3 saisons : la saison
choisie et les 2 précédentes, dans la même compétition. Une fenêtre ne mélange jamais deux
sources. Le choix est grisé, avec la raison, quand les 3 saisons n'existent pas :

| Compétition | Fenêtres disponibles | Indisponible |
|---|---|---|
| Top 14 | 2023-24, 2024-25, 2025-26 | 2021-22, 2022-23 |
| Pro D2 | 2024-25, 2025-26 | 2022-23, 2023-24 |

**Calcul.** Les stats sont additionnées match par match sur les 3 saisons, puis divisées : par 80
minutes = somme des totaux / somme des minutes x 80, pourcentages = somme des réussis / somme des
tentatives. Jamais de moyenne des 3 saisons. Exemple, Léo Barré : 130 plaquages en 4 746 minutes,
soit 2,19 par 80 minutes ; la moyenne des 3 saisons (2,44, 1,84, 2,23) donnerait 2,17. Les
totaux de chaque fenêtre sont contrôlés : ils égalent, pour tous les joueurs, la somme des 3
saisons (matchs, minutes, plaquages, mètres...).

**Référence.** Les joueurs du poste sur la même fenêtre, avec les mêmes seuils : au moins 5 matchs
et 520 minutes au total. En Top 14 2023-24 à 2025-26, saison complète, la référence passe de 381
joueurs (2025-26 seule) à 641. Sur les 244 joueurs de 2025-26 en échantillon court, 122 y
entrent sur 3 saisons. Axes, padding (P), seuils NC et M inchangés : les axes restent ceux de la
règle des 0,4 sur une saison.

**Poste, club, disponibilité.** Poste principal et club principal sont calculés sur la fenêtre, avec
les mêmes règles que sur une saison. Le poste peut donc différer de celui de la saison choisie (40
joueurs en Top 14 2025-26 : Paul Boudehent, deuxième ligne en 2025-26, troisième ligne aile sur 3
saisons) ; la carte le signale. La disponibilité est comptée saison par saison : un joueur parti
puis revenu dans un club ne se voit pas compter les matchs du club pendant son absence. Une saison
entière sans match n'entre pas dans le calcul.

**Joueurs proposés.** Tous ceux de la fenêtre, y compris ceux qui n'ont pas joué la saison choisie,
comme la population de référence. La carte donne les saisons jouées (« A joué 2 saisons sur 3
(dernière : 2024-25) ») et une ligne par saison (club, matchs, minutes). Une fenêtre Top 14 ne
compte que les matchs de Top 14 : les saisons passées en Pro D2 n'y sont pas.

**Affichage.** La fenêtre est écrite dans le titre, sur les cartes et sur le radar lui-même. Sur la
carte d'un joueur en échantillon court, un bouton « Voir sur 3 saisons » passe la page en mode 3
saisons en gardant les joueurs choisis.

## Pourcentages ajustés et « NC »

Même méthode que la NBA (padding) : `(réussis + P x moyenne de référence) / (tentatives + P)`.
Un faible volume est ramené vers la moyenne, un gros volume garde son vrai niveau. Le z-score et
le centile utilisent ce pourcentage ajusté ; le tableau affiche aussi le vrai pourcentage. Sous un
volume minimum sur la saison, l'axe est vide et le tableau affiche « NC » (non classé).

| Pourcentage | P | NC sous | Moyenne de référence |
|---|---|---|---|
| % plaquages réussis | 97 | 25 plaquages tentés | celle du poste |
| % gain de ligne | 82 | 20 courses | celle du poste |
| % au pied (hors radar) | 146 | 35 tentatives au but | celle de tous les buteurs qualifiés |

P est estimé par la méthode split-half sur les tentatives : c'est le volume auquel la moitié de
l'écart observé entre joueurs est du bruit. Le seuil NC est le volume où le vrai pourcentage du
joueur ne pèse que 0,2 dans son pourcentage ajusté (P / 4, arrondi à 5).

## Stats par 80 hors radar

Dans le tableau du radar, les stats par 80 qui ne sont pas sur le radar (pénalités concédées,
ballons perdus, axes retirés quand les postes diffèrent) sont rapprochées de la moyenne du poste,
d'autant plus que le joueur a peu joué, même logique que le padding des pourcentages :
`(total + M x taux moyen du poste par minute) / (minutes + M) x 80`. M est estimé pour chaque
stat par la méthode split-half, de 89 minutes pour les touches gagnées à 1 982 pour les ballons
perdus. La valeur brute reste affichée entre parenthèses.

## Calibration figée pour la V1

Les seuils ci-dessus viennent de `scripts/rugby_calibrate.py`, sur toutes les saisons du Top 14 et
du Pro D2. Après les corrections de données (minutes, compteurs de score, club principal), la
calibration rejouée donne les mêmes valeurs, sauf trois : P du % au pied 167 au lieu de 146,
seuil NC du % au pied 40 au lieu de 35, M des essais 1 923 au lieu de 1 919. Les valeurs
d'origine sont gardées : l'estimation de P au pied est instable (une douzaine de tentatives
corrigées la déplace de 14 %), et son effet est au plus 0,5 point de % au pied ajusté. On
recalibrera en ajoutant des saisons, pas à chaque correction de données.

## Limites connues

- **Match d'accès absent.** Le match d'accès entre le Top 14 et la Pro D2 n'est dans aucune des
  deux compétitions de la source, pour aucune saison.
- **Noms sans accents.** La source écrit presque tous les noms sans accents (26 sur 2 319 en
  ont), et sans nationalité on ne peut pas les rétablir de façon sûre (« Jeremy » anglais ou
  « Jérémy » français). À l'affichage seulement : un seul nom par joueur sur toutes les saisons
  (celui du match le plus récent, ou la forme accentuée si la source la donne ailleurs ; 29
  joueurs ont plusieurs graphies dans la source), puis une table de 30 corrections vérifiées à
  la main contre la presse et des bases spécialisées (accents, une faute de frappe, le prénom de
  Charles-Henri Berguet). Les autres noms restent tels que la source les donne. Le tri et la
  recherche de joueurs ignorent accents et majuscules : « gael » trouve « Gaël ».
- **Un identifiant pour deux noms.** En Pro D2, la source range « Aurelien Lafforgue » et
  « Aurelien Lisena » sous le même identifiant (même club, mêmes maillots, jamais sur la même
  feuille de match). Rien ne prouve qu'il s'agit du même joueur : chaque saison garde le nom donné
  par la source.
- **Stats d'impact des remplaçants.** Les stats par 80 des joueurs qui entrent souvent en cours
  de match peuvent être plus élevées : jambes fraîches face à une défense fatiguée, extrapolées
  sur 80 minutes. Le seuil de 520 minutes limite l'effet sur le radar, pas dans les tableaux du
  Dashboard.
- **Pénalités manquées par joueur** : absentes des stats du joueur, elles sont comptées à partir
  des actions de score.
- **Stats absentes** : pas de mêlée ni de rucks par joueur, pas de passes décisives par joueur
  dans la source.
- **Pas d'âge, de taille ni de poids** : les fiches joueur de la source manquaient trop souvent
  (environ 60 % introuvables), elles ont été abandonnées.
