import os
import sqlite3
import tempfile
import unittest

from dio_delivery_quality_engine.recommendation_mailer import (
    generate_email_drafts,
    seed_sales_rep_emails,
    upsert_monthly_recommendations,
)
from dio_delivery_quality_engine.store import init_db


class RecommendationMailerTests(unittest.TestCase):
    def test_generates_rep_grouped_drafts_for_ab_grade_cj_candidates_only(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "quality.db")
            init_db(db)
            seed_sales_rep_emails(db, [{"sales_rep_name": "김영업", "branch_name": "부산", "email": "rep@example.com"}])
            upsert_monthly_recommendations(db, "2026-06", [
                {
                    "customer_code": "C1",
                    "customer_name": "전주이든치과",
                    "branch_name": "부산",
                    "sales_rep_name": "김영업",
                    "current_main_carrier": "KOREA_POST",
                    "recommended_carrier": "CJ",
                    "grade": "A",
                    "reason": "최근 CJ 도착시각 우세",
                    "cj_recent_n": 23,
                    "kp_recent_n": 10,
                    "cj_next_rate": 1.0,
                    "kp_next_rate": 0.8,
                    "cj_avg_arrival": "11:26",
                    "kp_avg_arrival": "14:39",
                },
                {
                    "customer_code": "C2",
                    "customer_name": "미래연치과",
                    "branch_name": "부산",
                    "sales_rep_name": "김영업",
                    "current_main_carrier": "KOREA_POST",
                    "recommended_carrier": "CJ",
                    "grade": "B",
                    "reason": "2주 테스트 후보",
                    "cj_recent_n": 5,
                    "kp_recent_n": 9,
                    "cj_next_rate": 1.0,
                    "kp_next_rate": 0.778,
                    "cj_avg_arrival": "12:49",
                    "kp_avg_arrival": "13:05",
                },
                {
                    "customer_code": "C3",
                    "customer_name": "보류치과",
                    "branch_name": "부산",
                    "sales_rep_name": "김영업",
                    "current_main_carrier": "KOREA_POST",
                    "recommended_carrier": "CJ",
                    "grade": "D",
                    "reason": "보류",
                    "cj_recent_n": 1,
                    "kp_recent_n": 3,
                },
            ])

            drafts = generate_email_drafts(db, "2026-06", allowed_grades=("A", "B"))

            self.assertEqual(len(drafts), 1)
            draft = drafts[0]
            self.assertEqual(draft["recipient_email"], "rep@example.com")
            self.assertIn("CJ 예외 발송 테스트 후보", draft["subject"])
            self.assertIn("전주이든치과", draft["body"])
            self.assertIn("미래연치과", draft["body"])
            self.assertNotIn("보류치과", draft["body"])
            self.assertEqual(draft["recommendation_count"], 2)

            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM recommendation_email_logs WHERE status='draft'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
