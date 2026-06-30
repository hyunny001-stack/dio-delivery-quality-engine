import os
import tempfile
import unittest

from dio_delivery_quality_engine.carrier_switch import analyze_carrier_switch
from dio_delivery_quality_engine.store import (
    carrier_switch_stats,
    init_db,
    upsert_carrier_switch_tracking_rows,
)


class CarrierSwitchStoreTests(unittest.TestCase):
    def test_ingests_tracking_rows_and_analyzes_from_sqlite(self):
        rows = [
            {
                "trackingNo": "CJ1",
                "carrier": "CJ",
                "orderId": "R1",
                "customerId": "C1",
                "customerName": "거래처1",
                "shipDate": "2026-04-01",
                "salesRepName": "담당",
                "hqName": "본부",
                "ok": True,
                "track": {"status": "DELIVERED", "last_updated": "2026-04-02T13:00:00+09:00", "delivery_region": "서울"},
            },
            {
                "trackingNo": "CJ2",
                "carrier": "CJ",
                "orderId": "R2",
                "customerId": "C1",
                "customerName": "거래처1",
                "shipDate": "2026-04-02",
                "ok": True,
                "track": {"status": "DELIVERED", "last_updated": "2026-04-03T13:00:00+09:00"},
            },
            {
                "trackingNo": "KP1",
                "carrier": "KOREA_POST",
                "orderId": "R3",
                "customerId": "C1",
                "customerName": "거래처1",
                "shipDate": "2026-05-20",
                "ok": True,
                "track": {"status": "DELIVERED", "last_updated": "2026.05.21 10:00:00"},
            },
            {
                "trackingNo": "KP2",
                "carrier": "KOREA_POST",
                "orderId": "R4",
                "customerId": "C1",
                "customerName": "거래처1",
                "shipDate": "2026-05-21",
                "ok": True,
                "track": {"status": "DELIVERED", "last_updated": "2026-05-22T10:00:00+09:00"},
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "quality.db")
            init_db(db)
            self.assertEqual(upsert_carrier_switch_tracking_rows(db, rows, source="unit"), 4)
            stats = carrier_switch_stats(db)
            self.assertEqual(stats["carrierSwitchShipments"], 4)
            self.assertEqual(stats["carrierSwitchDelivered"], 4)

            result = analyze_carrier_switch(
                db,
                cj_start="2026-01-01",
                cj_end="2026-05-09",
                kp_start="2026-05-20",
                kp_end="2026-06-28",
                min_cj=2,
                min_kp=2,
                threshold_hours=2,
            )
            self.assertEqual(result["summary"], {"KP_BETTER": 1, "CJ_BETTER": 0, "NO_CLEAR": 0, "INSUF": 0})
            self.assertEqual(result["customers"][0]["rec"], "KP_BETTER")
            self.assertAlmostEqual(result["customers"][0]["gap"], 3.0)


if __name__ == "__main__":
    unittest.main()
