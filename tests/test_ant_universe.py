import os
import unittest
from unittest.mock import patch

from app.config import CORE_UNIVERSE, load_settings


class AnthropicUniverseTests(unittest.TestCase):
    def test_ant_is_in_default_options_universe(self):
        with patch.dict(os.environ, {"UOA_CORE_UNIVERSE": ""}):
            settings = load_settings()
        self.assertIn("ANT", CORE_UNIVERSE)
        self.assertIn("ANT", settings.active_universe)
        self.assertEqual(settings.thresholds_for("ANT"), settings.thresholds)


if __name__ == "__main__":
    unittest.main()
