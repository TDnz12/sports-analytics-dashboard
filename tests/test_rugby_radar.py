"""Radar rugby (data_sources/rugby/radar.py) : axes selon les postes comparés (intersection), pire cas
sur toutes les combinaisons de postes, scores par poste, padding et NC, stats par 80 hors radar
rapprochées de la moyenne du poste, joueurs sans poste, cartes, colonnes hors radar et notes."""
import unittest
from itertools import combinations
from unittest import mock

import numpy as np
import pandas as pd

from data_sources.rugby import radar, schema
from data_sources.rugby.positions import (
    CENTRE, FLANKER, FULLBACK, HOOKER, LOCK, POSITION_GROUPS, PROP, UNDETERMINED, WING,
)


def _labels(axes):
    return [a["label"] for a in axes]


class TestAxesFor(unittest.TestCase):
    def test_un_poste_tous_ses_axes(self):
        for pos, keys in schema.RADAR_AXES_BY_POSITION.items():
            axes, notes = radar.radar_axes_for([pos])
            self.assertEqual([a["key"] for a in axes], list(keys))
            self.assertEqual(notes, [])

    def test_meme_poste_plusieurs_joueurs(self):
        axes, notes = radar.radar_axes_for([LOCK, LOCK, LOCK])
        self.assertEqual([a["key"] for a in axes], list(schema.RADAR_AXES_BY_POSITION[LOCK]))
        self.assertEqual(notes, [])

    def test_pilier_ailier_intersection(self):
        axes, notes = radar.radar_axes_for([PROP, WING])
        self.assertEqual(_labels(axes), ["Plaquages", "% plaquages", "Mètres", "% gain de ligne",
                                         "Courses", "Défenseurs battus", "Offloads"])
        self.assertTrue(any(n.startswith("Postes différents") for n in notes))
        removed = next(n for n in notes if n.startswith("Axes retirés"))
        self.assertIn("Grattages, Passes (Pilier)", removed)
        self.assertIn("Mètres au pied (Ailier)", removed)
        self.assertNotIn(radar.FEW_AXES_NOTE, notes)

    def test_ordre_du_premier_joueur(self):
        a, _ = radar.radar_axes_for([PROP, WING])
        b, _ = radar.radar_axes_for([WING, PROP])
        self.assertEqual(set(_labels(a)), set(_labels(b)))
        self.assertEqual([k for k in schema.RADAR_AXES_BY_POSITION[WING] if k in {x["key"] for x in b}],
                         [x["key"] for x in b])

    def test_arriere_sans_pourcentage_plaquages(self):
        axes, _ = radar.radar_axes_for([PROP, FULLBACK])
        self.assertNotIn("% plaquages", _labels(axes))

    def test_indetermine_ignore(self):
        self.assertEqual(radar.radar_axes_for([UNDETERMINED]), ([], []))
        self.assertEqual(radar.radar_axes_for([]), ([], []))
        axes, _ = radar.radar_axes_for([UNDETERMINED, CENTRE])
        self.assertEqual([a["key"] for a in axes], list(schema.RADAR_AXES_BY_POSITION[CENTRE]))

    def test_pire_cas_toutes_combinaisons(self):
        """1 à 4 postes différents (385 combinaisons) : 5 axes au minimum, donc jamais la note."""
        minimum = {}
        for k in range(1, 5):
            minimum[k] = min(len(radar.radar_axes_for(c)[0]) for c in combinations(POSITION_GROUPS, k))
        self.assertEqual(minimum, {1: 7, 2: 6, 3: 5, 4: 5})
        self.assertGreaterEqual(min(minimum.values()), radar.MIN_COMMON_AXES)
        axes, notes = radar.radar_axes_for([PROP, WING, FULLBACK])
        self.assertEqual(len(axes), 5)
        self.assertNotIn(radar.FEW_AXES_NOTE, notes)

    def test_note_peu_d_axes(self):
        fake = {PROP: ("tackles", "metres", "carries", "passes"), WING: ("tackles", "metres", "carries", "kick_metres")}
        with mock.patch.dict(schema.RADAR_AXES_BY_POSITION, fake):
            axes, notes = radar.radar_axes_for([PROP, WING])
        self.assertEqual(len(axes), 3)
        self.assertIn(radar.FEW_AXES_NOTE, notes)
        self.assertEqual(radar.FEW_AXES_NOTE, "Ces postes ont peu d'axes en commun : compare plutôt "
                                              "des joueurs de la même famille.")

    def test_textes_sans_tiret_cadratin(self):
        texts = [radar.RADAR_REFERENCE_CAPTION, radar.FEW_AXES_NOTE, *radar.RADAR_CAVEATS,
                 *radar.RADAR_EXTRA_HELP, *radar.RADAR_EXTRA_HELP.values()]
        texts += [a["label"] for a in radar.RADAR_AXES] + [a["help"] for a in radar.RADAR_AXES]
        for c in combinations(POSITION_GROUPS, 3):
            texts += radar.radar_axes_for(c)[1]
        self.assertFalse([t for t in texts if "—" in t])


def _players(n_per_pos=12, **overrides):
    """Joueurs fictifs : n_per_pos piliers et n_per_pos ailiers dans la référence (10 matchs, 800
    min), plus 2 Indéterminé et un pilier à échantillon court."""
    rng = np.random.default_rng(1)
    rows = []
    for pos in (PROP, WING):
        for _ in range(n_per_pos):
            rows.append({"position_group": pos, "games_played": 10, "minutes_total": 800.0})
    rows.append({"position_group": PROP, "games_played": 3, "minutes_total": 150.0})
    rows += [{"position_group": UNDETERMINED, "games_played": 4, "minutes_total": 200.0}] * 2
    df = pd.DataFrame(rows)
    n = len(df)
    for a in radar.RADAR_AXES:
        df[a["stat_col"]] = rng.uniform(1, 10, n)
    df["tackle_attempts"] = rng.integers(30, 150, n).astype(float)
    df["tackles"] = np.floor(df["tackle_attempts"] * rng.uniform(0.7, 0.95, n))
    df["carries"] = rng.integers(30, 120, n).astype(float)
    df["carries_gain_line"] = np.floor(df["carries"] * rng.uniform(0.3, 0.6, n))
    df["goal_attempts"] = 0.0
    df["goals_made"] = 0.0
    for col, val in overrides.items():
        df[col] = val
    df["tackle_pct"] = df["tackles"] / df["tackle_attempts"]
    df["gain_line_pct"] = df["carries_gain_line"] / df["carries"]
    df["goal_kick_pct"] = df["goals_made"] / df["goal_attempts"].where(df["goal_attempts"] > 0)
    return df


class TestScores(unittest.TestCase):
    def setUp(self):
        self.df = _players()
        self.out = radar.compute_radar_scores(self.df, competition="top14")

    def test_reference_et_eligibilite(self):
        out = self.out
        self.assertEqual(out["radar_reference"].sum(), 24)
        self.assertFalse(out.loc[out["position_group"] == UNDETERMINED, "radar_eligible"].any())
        self.assertTrue(out.loc[out["position_group"] != UNDETERMINED, "radar_eligible"].all())

    def test_indetermine_sans_score(self):
        und = self.out[self.out["position_group"] == UNDETERMINED]
        for a in radar.RADAR_AXES:
            self.assertTrue(und[f"radar_{a['key']}_score"].isna().all(), a["key"])

    def test_zscore_par_poste_sur_la_reference(self):
        out = self.out
        props = out[(out["position_group"] == PROP) & out["radar_reference"]]
        col = "tackles_per80"
        expected = (props[col] - props[col].mean()) / props[col].std()
        np.testing.assert_allclose(out.loc[props.index, "radar_tackles_z"], expected)
        short = out[(out["position_group"] == PROP) & ~out["radar_reference"]]
        self.assertTrue(short["radar_tackles_score"].notna().all())  # noté, hors référence

    def test_padding_vers_la_moyenne_du_poste(self):
        out, df = self.out, self.df
        props = df[df["position_group"] == PROP]
        mean = props["tackles"].sum() / props["tackle_attempts"].sum()
        i = props.index[0]
        expected = (df.at[i, "tackles"] + 97 * mean) / (df.at[i, "tackle_attempts"] + 97)
        self.assertAlmostEqual(out.at[i, "tackle_pct_adj"], expected)

    def test_nc_sous_le_seuil(self):
        df = _players()
        df.loc[0, ["tackle_attempts", "tackles"]] = [24.0, 20.0]
        df.loc[1, ["tackle_attempts", "tackles"]] = [25.0, 20.0]
        out = radar.compute_radar_scores(df, competition="top14")
        self.assertTrue(np.isnan(out.at[0, "tackle_pct_adj"]))
        self.assertTrue(np.isnan(out.at[0, "radar_tackle_pct_score"]))
        self.assertFalse(np.isnan(out.at[1, "radar_tackle_pct_score"]))

    def test_pied_reference_des_buteurs_qualifies(self):
        df = _players()
        df.loc[0, ["goal_attempts", "goals_made"]] = [60.0, 48.0]   # qualifié, 80 %
        df.loc[13, ["goal_attempts", "goals_made"]] = [40.0, 24.0]  # qualifié (ailier), 60 %
        df.loc[1, ["goal_attempts", "goals_made"]] = [10.0, 0.0]    # sous 35 : NC, hors moyenne
        out = radar.compute_radar_scores(df, competition="top14")
        mean = 72 / 100
        self.assertAlmostEqual(out.at[0, "goal_kick_pct_adj"], (48 + 146 * mean) / (60 + 146))
        self.assertTrue(np.isnan(out.at[1, "goal_kick_pct_adj"]))

    def test_scores_bornes(self):
        for a in radar.RADAR_AXES:
            s = self.out[f"radar_{a['key']}_score"].dropna()
            self.assertTrue(s.between(0, 100).all(), a["key"])

    def test_stats_par_80_rapprochees_du_poste(self):
        df = _players()
        df["penalties_conceded_per80"] = 1.0
        df.loc[0, ["penalties_conceded_per80", "minutes_total"]] = [4.0, 100.0]
        out = radar.compute_radar_scores(df, competition="top14")
        props = df[df["position_group"] == PROP]
        total = props["penalties_conceded_per80"] * props["minutes_total"] / 80
        rate = total.sum() / props["minutes_total"].sum()
        m = schema.PER80_SHRINK_M[schema.CLUB]["penalties_conceded"]
        expected = (4.0 * 100 / 80 + m * rate) / (100 + m) * 80
        self.assertAlmostEqual(out.at[0, "penalties_conceded_per80_adj"], expected)
        self.assertLess(out.at[0, "penalties_conceded_per80_adj"], 1.3)  # 4,0 ramené près du poste
        # Beaucoup de minutes : la valeur brute pèse plus ; radar inchangé (valeurs brutes).
        big = radar.compute_radar_scores(df.assign(minutes_total=df["minutes_total"] * 100), competition="top14")
        self.assertGreater(big.at[0, "penalties_conceded_per80_adj"], out.at[0, "penalties_conceded_per80_adj"])
        # Le radar ne change pas : mêmes colonnes radar_* avec ou sans rapprochement.
        with mock.patch.dict(schema.PER80_SHRINK_M, {schema.CLUB: {}}):
            plain = radar.compute_radar_scores(df, competition="top14")
        cols = [c for c in plain.columns if c.startswith("radar_")]
        pd.testing.assert_frame_equal(out[cols], plain[cols])
        self.assertFalse([c for c in plain.columns if c.endswith("_per80_adj")])

    def test_stats_par_80_sans_minutes(self):
        df = _players()
        df.loc[0, "minutes_total"] = 0.0
        df.loc[1, "tackles_per80"] = np.nan
        out = radar.compute_radar_scores(df, competition="top14")
        self.assertTrue(np.isnan(out.at[0, "tackles_per80_adj"]))
        self.assertTrue(np.isnan(out.at[1, "tackles_per80_adj"]))

    def test_m_de_la_calibration(self):
        """M club de calibration_v1.md, section 1.2, pour chaque stat par 80 des axes du radar."""
        m = schema.PER80_SHRINK_M[schema.CLUB]
        self.assertEqual((m["penalties_conceded"], m["turnovers_conceded"], m["turnovers_won"],
                          m["kick_metres"], m["lineouts_won_jumper"]), (1494, 1982, 550, 180, 89))
        per80 = {a["stat_col"][:-len("_per80")] for a in radar.RADAR_AXES if "made_col" not in a}
        self.assertTrue(per80 <= set(m))

    def test_notes_reference(self):
        notes = radar.radar_notes(self.out, [PROP, WING])
        self.assertEqual(notes[0], "Joueurs de référence : Pilier 12 joueurs, Ailier 12 joueurs.")
        self.assertIn("2 joueurs sans poste déterminé", notes[1])
        small = radar.compute_radar_scores(_players(n_per_pos=8), competition="top14")
        self.assertIn("Pilier 8 joueurs (moins de 10 : comparaison fragile)",
                      radar.radar_notes(small, [PROP])[0])


def _row(**kw):
    base = {"position_group": PROP, "position_source": "titulaire", "secondary_positions": None,
            "games_played": 12, "starts": 10, "minutes_per_game": 54.4, "availability": 0.857,
            "yellow_cards": 2.0, "red_cards": 0.0, "minutes_total": 650.0, "radar_reference": True,
            "tries": 3.0, "clean_breaks": 1.0, "penalties_conceded_per80": 1.25,
            "turnovers_conceded_per80": 0.5, "goal_attempts": 0.0, "goals_made": 0.0,
            "goal_kick_pct": np.nan, "goal_kick_pct_adj": np.nan, "cards": "2 / 0",
            "kick_metres_per80": 3.25, "turnovers_won_per80": 0.75, "passes_per80": 2.0,
            "turnovers_won_per80_adj": 0.6, "penalties_conceded_per80_adj": 1.04,
            "tackle_pct": 0.9, "tackles": 90.0, "tackle_attempts": 100.0, "tackle_pct_adj": 0.88}
    base.update(kw)
    return pd.Series(base)


class TestCardAndTable(unittest.TestCase):
    def test_carte(self):
        lines = radar.radar_card_lines(_row(secondary_positions="Talonneur 20 %"))
        self.assertEqual(lines, ["Pilier (aussi : Talonneur 20 %)",
                                 "10 titularisations · 54 min par match · disponibilité 86 %",
                                 "Essais : 3 · % au pied : aucune tentative · Cartons : 2 jaunes, 0 rouge"])

    def test_carte_banc_et_echantillon_court(self):
        lines = radar.radar_card_lines(_row(position_source="banc", starts=0, games_played=4,
                                            minutes_total=210.0, radar_reference=False,
                                            yellow_cards=1.0))
        self.assertEqual(lines[0], "Pilier, poste déduit du maillot de banc")
        self.assertTrue(lines[1].startswith("0 titularisation · "))
        self.assertEqual(lines[2], "Essais : 3 · % au pied : aucune tentative · Cartons : 1 jaune, 0 rouge")
        self.assertEqual(lines[3], "Échantillon court : 4 matchs, 210 min (hors population de référence)")

    def test_chiffres_cles_pied(self):
        kicker = _row(goal_attempts=67.0, goals_made=52.0, goal_kick_pct=52 / 67, red_cards=1.0)
        self.assertEqual(radar.radar_card_lines(kicker)[2],
                         "Essais : 3 · % au pied : 78 % (52/67) · Cartons : 2 jaunes, 1 rouge")
        nc = _row(goal_attempts=34.0, goals_made=30.0, goal_kick_pct=30 / 34)
        self.assertIn("% au pied : NC ·", radar.radar_card_lines(nc)[2])

    def test_colonnes_hors_radar(self):
        out = radar.radar_extra_columns(_row(), [PROP, WING])
        self.assertEqual(list(out)[:3], ["Grattages (ajusté)", "Passes (ajusté)", "Mètres au pied (ajusté)"])
        self.assertEqual(out["Grattages (ajusté)"], "0,6 (brut 0,8)")
        self.assertEqual(out["Passes (ajusté)"], "2,0")  # sans valeur ajustée : brute seule
        self.assertEqual(out["Essais"], "3")
        self.assertEqual(out["Pénalités concédées par 80 (ajusté, peu fiable)"], "1,0 (brut 1,2)")
        self.assertEqual(out["% au pied"], "aucune tentative")
        self.assertEqual(out["Cartons (J / R)"], "2 / 0")
        self.assertTrue(set(out) <= set(radar.RADAR_EXTRA_HELP))

    def test_pourcentage_plaquages_arriere(self):
        out = radar.radar_extra_columns(_row(position_group=FULLBACK), [FULLBACK, CENTRE])
        self.assertEqual(out["% plaquages"], "90 % (90/100)  ·  ajusté 88 %")
        nc = radar.radar_extra_columns(_row(tackle_pct_adj=np.nan, tackles=18.0,
                                            tackle_attempts=20.0), [FULLBACK, CENTRE])
        self.assertEqual(nc["% plaquages"], "90 % (18/20)  ·  NC")

    def test_pied(self):
        out = radar.radar_extra_columns(_row(goal_attempts=67.0, goals_made=52.0,
                                             goal_kick_pct=52 / 67, goal_kick_pct_adj=0.76), [PROP])
        self.assertEqual(out["% au pied"], "78 % (52/67)  ·  ajusté 76 %")
        nc = radar.radar_extra_columns(_row(goal_attempts=10.0, goals_made=7.0,
                                            goal_kick_pct=0.7), [PROP])
        self.assertEqual(nc["% au pied"], "70 % (7/10)  ·  NC")
        self.assertNotIn("Grattages (ajusté)", radar.radar_extra_columns(_row(), [PROP]))


class TestVraisCaches(unittest.TestCase):
    """Top 14 et Pro D2 2025-26 : chaque poste a au moins 12 joueurs de référence, aucun
    Indéterminé noté, aucun joueur « (banc) » exclu."""

    def test_caches(self):
        from data_sources.rugby import get_player_stats
        for comp in ("top14", "prod2"):
            df = radar.compute_radar_scores(get_player_stats("2025-26", competition=comp), competition=comp)
            counts = df.loc[df["radar_reference"], "position_group"].value_counts()
            self.assertEqual(set(counts.index), set(POSITION_GROUPS), comp)
            self.assertGreaterEqual(counts.min(), 12, comp)
            self.assertTrue(df.loc[df["position_source"] == "banc", "radar_eligible"].all())
            und = df["position_group"] == UNDETERMINED
            self.assertTrue(df.loc[und, "radar_tackles_score"].isna().all())
            self.assertTrue(df.loc[~und & (df["minutes_total"] > 0), "radar_tackles_score"].notna().all())


if __name__ == "__main__":
    unittest.main()
