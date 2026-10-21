"""Cohérence des constantes du radar rugby (schema.py) : seuils calibrés, padding, axes par poste."""
import unittest

from data_sources.rugby import schema
from data_sources.rugby.positions import FULLBACK, GROUP_FAMILY, POSITION_GROUPS


class TestRadarConfig(unittest.TestCase):
    def test_club_thresholds(self):
        self.assertEqual(schema.SAMPLE_THRESHOLDS[schema.CLUB_ICW], (5, 520))

    def test_padding_values(self):
        club = schema.PCT_PADDING[schema.CLUB_ICW]
        self.assertEqual({k: (v[2], v[3]) for k, v in club.items()},
                         {"tackle_pct_adj": (97, 25), "gain_line_pct_adj": (82, 20),
                          "goal_kick_pct_adj": (146, 35)})

    def test_nc_threshold_rule(self):
        """Minimum NC = P / 4 arrondi à 5 (poids 0,2 du joueur dans son % ajusté)."""
        for made, att, p, nc, ref in schema.PCT_PADDING[schema.CLUB_ICW].values():
            self.assertEqual(nc, 5 * round(p / 4 / 5))

    def test_every_position_has_axes_without_duplicates(self):
        self.assertEqual(set(schema.RADAR_AXES_BY_POSITION), set(POSITION_GROUPS))
        for pos, axes in schema.RADAR_AXES_BY_POSITION.items():
            self.assertEqual(len(axes), len(set(axes)), pos)
            self.assertTrue(set(axes) <= set(schema.RADAR_AXES_CLUB), pos)

    def test_family_axes_present(self):
        for pos, axes in schema.RADAR_AXES_BY_POSITION.items():
            self.assertTrue(set(schema.RADAR_FAMILY[GROUP_FAMILY[pos]]) <= set(axes), pos)

    def test_axes_removed_from_radar(self):
        removed = {"penalties_conceded", "turnovers_conceded", "clean_breaks", "tries", "goal_kick_pct"}
        for axes in schema.RADAR_AXES_BY_POSITION.values():
            self.assertFalse(removed & set(axes))
        self.assertNotIn("tackle_pct", schema.RADAR_AXES_BY_POSITION[FULLBACK])

    def test_padded_axes_use_padding_columns(self):
        adj = set(schema.PCT_PADDING[schema.CLUB_ICW])
        for label, stat_col, score_col, attempts_col in schema.RADAR_AXES_CLUB.values():
            if score_col is not None:
                self.assertIn(score_col, adj, label)
                self.assertIsNotNone(attempts_col, label)


if __name__ == "__main__":
    unittest.main()
