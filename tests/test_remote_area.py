import unittest

from dio_delivery_quality_engine.remote_area import match_remote_area, normalize_address


class RemoteAreaTests(unittest.TestCase):
    def test_match_remote_area_prefers_specific_range(self):
        ranges = [
            {"carrier": "cj_logistics", "area_name": "제주 전지역", "zip_start": "63000", "zip_end": "63644"},
            {"carrier": "cj_logistics", "area_name": "제주 추자면", "zip_start": "63000", "zip_end": "63001"},
        ]
        hit = match_remote_area("cj_logistics", "63000", ranges)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["area_name"], "제주 추자면")
        hit = match_remote_area("cj_logistics", "63100", ranges)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["area_name"], "제주 전지역")
        self.assertIsNone(match_remote_area("epost", "63100", ranges))

    def test_normalize_address_strips_parentheses_and_spaces(self):
        self.assertEqual(normalize_address("서울시  강남구 (역삼동)  123"), "서울시 강남구 123")


if __name__ == "__main__":
    unittest.main()
