import os
import tempfile
import unittest

from dio_delivery_quality_engine.core import Shipment, TrackingRecord
from dio_delivery_quality_engine.store import init_db, records_for_period, upsert_shipments, upsert_tracking_records, db_stats


class StoreTest(unittest.TestCase):
    def test_sqlite_accumulates_shipments_and_tracking(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "quality.db")
            init_db(db)
            shipment = Shipment("6890123456789", "epost", "2026-06-22", customer_name="테스트", address="서울특별시 강남구")
            self.assertEqual(upsert_shipments(db, [shipment]), 1)
            record = TrackingRecord(shipment, True, "DELIVERED", delivered_date="2026-06-23", delivered_hhmm="14:00")
            self.assertEqual(upsert_tracking_records(db, [record]), 1)
            rows = records_for_period(db, "2026-06-01", "2026-06-30")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].delivered_hhmm, "14:00")
            self.assertEqual(db_stats(db)["shipments"], 1)
            self.assertEqual(db_stats(db)["trackingResults"], 1)


if __name__ == "__main__":
    unittest.main()
