import os
import unittest
from unittest.mock import patch

from app.config import CORE_UNIVERSE, load_settings


class SkyHynixUniverseTests(unittest.TestCase):
    def test_skyhynix_is_in_default_universe(self):
        self.assertIn("SKHY", CORE_UNIVERSE)

    def test_skyhynix_survives_older_railway_universe(self):
        with patch.dict(os.environ, {"UOA_CORE_UNIVERSE": "SPY,AMD"}):
            settings = load_settings()
        self.assertIn("SKHY", settings.active_universe)
        self.assertEqual(settings.thresholds_for("SKHY"), settings.thresholds)


if __name__ == "__main__":
    unittest.main()
