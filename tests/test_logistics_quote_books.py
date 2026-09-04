"""物流报价表识别结果持久化与接口测试。"""

import os
import sqlite3
import tempfile
import threading
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.logistics_quote import create_logistics_quote_router
from app.services.logistics_quote_books import LogisticsQuoteBookService


QUOTE_CSV = (
    "店家,承运商,线路,时效,首重价,续重价\n"
    "小鹿家居,中通快运,杭州→上海,1-2天,12元,4.8元/kg\n"
).encode("utf-8-sig")

QUOTE_CSV_OTHER = (
    "店家,承运商,线路,时效,首重价,续重价\n"
    "北岸数码,顺丰速运,深圳→北京,2-3天,23元,7.5元/kg\n"
).encode("utf-8-sig")


class QuoteBookTestDatabase:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            );
            CREATE TABLE logistics_quote_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                book_kind TEXT,
                service_count INTEGER DEFAULT 0,
                route_count INTEGER DEFAULT 0,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, sha256),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


class LogisticsQuoteBookServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = QuoteBookTestDatabase(os.path.join(self.temp_dir.name, "quotes.db"))
        self.service = LogisticsQuoteBookService(self.manager)

    def tearDown(self):
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def _sample_result(self, filename="报价.csv"):
        return {
            "mode": "rate_book_summary",
            "source": {
                "filename": filename,
                "size": 128,
                "sha256": f"hash-{filename}",
                "content_type": "text/csv",
                "file_type": "csv",
                "parser_version": "test",
                "status": "parsed",
            },
            "book_kind": "express",
            "service_count": 1,
            "route_count": 1,
            "services": [{"name": "中通快运", "sheet_name": "CSV", "row_count": 1, "route_count": 1, "rule_type": "first_additional", "book_kind": "express", "mapping": {}}],
            "carriers": [],
            "rows": [],
            "warning_count": 0,
            "warnings": [],
            "mapping": {"matched": {}, "unmatched": []},
            "summary": {"total": 1, "valid": 1, "review": 0, "rejected": 0},
        }

    def test_save_and_list_multiple_books(self):
        self.service.save_book(1, "报价A.csv", self._sample_result("报价A.csv"))
        self.service.save_book(1, "报价B.csv", self._sample_result("报价B.csv"))

        books = self.service.list_books(1)
        self.assertEqual(len(books), 2)
        self.assertEqual({book["filename"] for book in books}, {"报价A.csv", "报价B.csv"})
        first = books[0]
        self.assertEqual(first["payload"]["mode"], "rate_book_summary")
        self.assertEqual(first["payload"]["services"][0]["name"], "中通快运")
        self.assertIsNotNone(first["updated_at"])

    def test_reupload_same_file_refreshes_instead_of_duplicating(self):
        first = self.service.save_book(1, "报价.csv", self._sample_result())
        refreshed = self.service.save_book(1, "报价-最新.csv", self._sample_result())

        self.assertEqual(first["id"], refreshed["id"])
        books = self.service.list_books(1)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["filename"], "报价-最新.csv")

    def test_books_are_isolated_per_user(self):
        self.service.save_book(1, "报价A.csv", self._sample_result("报价A.csv"))
        self.service.save_book(2, "报价B.csv", self._sample_result("报价B.csv"))

        self.assertEqual([book["filename"] for book in self.service.list_books(1)], ["报价A.csv"])
        self.assertEqual([book["filename"] for book in self.service.list_books(2)], ["报价B.csv"])

    def test_delete_scoped_to_owner(self):
        book = self.service.save_book(1, "报价.csv", self._sample_result())

        self.assertFalse(self.service.delete_book(2, book["id"]))
        self.assertTrue(self.service.delete_book(1, book["id"]))
        self.assertEqual(self.service.list_books(1), [])
        self.assertFalse(self.service.delete_book(1, book["id"]))


class LogisticsQuoteRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = QuoteBookTestDatabase(os.path.join(self.temp_dir.name, "quotes.db"))
        app = FastAPI()

        def get_current_user():
            return {"user_id": 1, "username": "admin"}

        app.include_router(create_logistics_quote_router(get_current_user, self.manager))
        self.client = TestClient(app)

    def tearDown(self):
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def test_full_book_lifecycle(self):
        listed = self.client.get("/api/logistics/quote-books")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["books"], [])

        created = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("报价.csv", QUOTE_CSV, "text/csv")},
        )
        self.assertEqual(created.status_code, 200)
        book = created.json()["book"]
        self.assertEqual(book["filename"], "报价.csv")
        self.assertEqual(book["file_type"], "csv")
        self.assertEqual(book["service_count"], 1)
        self.assertEqual(book["payload"]["source"]["file_type"], "csv")

        listed = self.client.get("/api/logistics/quote-books")
        self.assertEqual(len(listed.json()["books"]), 1)

        reuploaded = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("报价-更新.csv", QUOTE_CSV, "text/csv")},
        )
        self.assertEqual(reuploaded.json()["book"]["id"], book["id"])

        other = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("报价2.csv", QUOTE_CSV_OTHER, "text/csv")},
        )
        self.assertNotEqual(other.json()["book"]["id"], book["id"])

        listed = self.client.get("/api/logistics/quote-books")
        self.assertEqual(len(listed.json()["books"]), 2)

        deleted = self.client.delete(f"/api/logistics/quote-books/{book['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(len(self.client.get("/api/logistics/quote-books").json()["books"]), 1)

        missing = self.client.delete(f"/api/logistics/quote-books/{book['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_invalid_file_returns_400_and_saves_nothing(self):
        failed = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("报价.txt", b"not a quote", "text/plain")},
        )
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.client.get("/api/logistics/quote-books").json()["books"], [])

    def test_parse_endpoint_still_works_without_saving(self):
        parsed = self.client.post(
            "/api/logistics/quote-sources/parse",
            files={"file": ("报价.csv", QUOTE_CSV, "text/csv")},
        )
        self.assertEqual(parsed.status_code, 200)
        self.assertTrue(parsed.json()["success"])
        self.assertEqual(self.client.get("/api/logistics/quote-books").json()["books"], [])


if __name__ == "__main__":
    unittest.main()
