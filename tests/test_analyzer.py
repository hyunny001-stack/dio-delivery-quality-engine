import unittest

from dio_delivery_quality_engine.analyzer import analyze_records
from dio_delivery_quality_engine.config import load_config
from dio_delivery_quality_engine.core import Shipment, TrackingRecord


class AnalyzerTest(unittest.TestCase):
    def test_friday_and_holiday_eve_excluded(self):
        cfg = load_config()
        records = [
            TrackingRecord(Shipment("6890123456789", "epost", "2026-06-26"), True, delivered_date="2026-06-29", delivered_hhmm="10:00"),
            TrackingRecord(Shipment("6890123456790", "epost", "2026-06-02"), True, delivered_date="2026-06-04", delivered_hhmm="10:00"),
            TrackingRecord(Shipment("6890123456791", "epost", "2026-06-22"), True, delivered_date="2026-06-23", delivered_hhmm="16:00"),
        ]
        result = analyze_records(records, cfg)
        self.assertEqual(result["excludedCount"], 2)
        epost = result["summary"][0]
        self.assertEqual(epost["total"], 1)
        self.assertEqual(epost["cutoffFail"], 1)

    def test_non_next_day_quality_error(self):
        cfg = load_config()
        record = TrackingRecord(
            Shipment("123456789012", "cj_logistics", "2026-06-22", customer_name="테스트-강남구", address="서울특별시 강남구 테헤란로 1"),
            True,
            delivered_date="2026-06-24",
            delivered_hhmm="11:00",
        )
        result = analyze_records([record], cfg)
        cj = [row for row in result["summary"] if row["carrierCode"] == "cj_logistics"][0]
        self.assertEqual(cj["nonNextDay"], 1)
        self.assertEqual(cj["qualityError"], 1)
        self.assertEqual(result["regionDelay"][0][0], "서울특별시 강남구")


if __name__ == "__main__":
    unittest.main()
