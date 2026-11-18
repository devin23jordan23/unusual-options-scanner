import os
import unittest
from unittest.mock import patch

from app.config import CORE_UNIVERSE, load_settings


class DisneyUniverseTests(unittest.TestCase):
    def test_dis_is_in_default_options_universe(self):
        with patch.dict(os.environ, {"UOA_CORE_UNIVERSE": ""}):
            settings = load_settings()
        self.assertIn("DIS", CORE_UNIVERSE)
        self.assertIn("DIS", settings.active_universe)
        self.assertEqual(settings.thresholds_for("DIS"), settings.thresholds)


if __name__ == "__main__":
    unittest.main()
