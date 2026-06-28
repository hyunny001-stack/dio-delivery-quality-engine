import json
import os
import tempfile
import unittest
from unittest.mock import patch

from dio_delivery_quality_engine.erp_source import fetch_erp_rows


class ErpSourceTest(unittest.TestCase):
    def test_fetch_erp_rows_requires_endpoint(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                fetch_erp_rows("2026-06-01", "2026-06-30")


if __name__ == "__main__":
    unittest.main()
