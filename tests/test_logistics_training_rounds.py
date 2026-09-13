"""命名训练回合：真实 SQLite 初始化、API 保存/回看/导出及隔离回归。"""

import importlib
import json
import os
import tempfile
import unittest
import uuid
from contextlib import closing
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from app.routers.logistics_agent import create_logistics_agent_router
from app.services.logistics_agent.service import LogisticsQuoteAgent


class TrainingRoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.disable("app.db_manager")
        # 全局单例仅在隔离内存库初始化，不接触账号运行库。
        with mock.patch.dict(os.environ, {"DB_PATH": ":memory:", "SQL_LOG_ENABLED": "false"}):
            cls.db_module = importlib.import_module("app.db_manager")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "training.db")
        self.db = self.db_module.DBManager(self.path)
        self.db.conn.executemany(
            "INSERT INTO cookies (id,value,user_id) VALUES (?,?,?)",
            [("own", "v", 1), ("own-two", "v", 1), ("other", "v", 2)],
        )
        self.db.conn.commit()
        self.user = {"user_id": 1}
        app = FastAPI()
        app.include_router(create_logistics_agent_router(lambda: self.user, self.db))
        self.client = TestClient(app)
        self.snapshot = mock.patch.object(LogisticsQuoteAgent, "thread_snapshot", return_value={"exists": True, "cookie_id": "own"})
        self.snapshot.start()
        self.payload = {
            "id": str(uuid.uuid4()), "thread_id": "test-example", "name": "重量未知，补充后报价",
            "messages": [
                {"role": "buyer", "content": "江西到河北多少钱？", "position": 0},
                {"role": "agent", "content": "请提供重量", "position": 1},
                {"role": "buyer", "content": "2公斤", "position": 4},
                {"role": "agent", "content": "试算运费7元", "position": 5, "decision": {"reason": "quoted"}},
            ],
        }

    def tearDown(self):
        self.snapshot.stop()
        self.client.close()
        from tests.test_logistics_quote_agent import close_cached_checkpointers
        close_cached_checkpointers()
        self.db.close()
        self.temp.cleanup()

    def save(self, payload=None, cookie="own"):
        return self.client.post(f"/api/logistics/agent/training-rounds?cookie_id={cookie}", json=payload or self.payload)

    def test_named_multiturn_round_persists_and_exports_only_selected_messages(self):
        result = self.save()
        self.assertEqual(result.status_code, 200, result.text)
        saved = result.json()["round"]
        self.assertEqual(saved["name"], self.payload["name"])
        self.assertEqual(saved["messages"], self.payload["messages"])
        self.assertEqual(saved["status"], "collected")
        # 新连接读到提交内容；原测试会话清空后采集内容仍存在。
        with mock.patch.object(LogisticsQuoteAgent, "thread_snapshot", return_value={"exists": False}):
            self.assertEqual(self.client.delete("/api/logistics/agent/threads/test-example?cookie_id=own").status_code, 200)
        import sqlite3
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM logistics_agent_training_rounds").fetchone()[0], 1)
        listed = self.client.get("/api/logistics/agent/training-rounds?cookie_id=own").json()["rounds"]
        self.assertEqual(listed, [saved])
        exported = self.client.get(f"/api/logistics/agent/training-rounds/{saved['id']}/export?cookie_id=own")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(len(exported.text.splitlines()), 1)
        self.assertEqual(json.loads(exported.text), {"messages": [
            {"role": "user" if m["role"] == "buyer" else "assistant", "content": m["content"]}
            for m in self.payload["messages"]
        ]})

    def test_retry_is_idempotent_and_new_save_is_a_new_round(self):
        self.assertTrue(self.save().json()["created"])
        self.assertFalse(self.save().json()["created"])
        conflict = {**self.payload, "name": "另一回合"}
        self.assertEqual(self.save(conflict).status_code, 409)
        self.assertTrue(self.save({**conflict, "id": str(uuid.uuid4())}).json()["created"])
        self.assertEqual(len(self.client.get("/api/logistics/agent/training-rounds?cookie_id=own").json()["rounds"]), 2)

    def test_validation_and_cookie_thread_user_isolation(self):
        for change in [
            {"name": "   "}, {"name": "长" * 101}, {"messages": []},
            {"messages": [self.payload["messages"][0]]},
            {"messages": list(reversed(self.payload["messages"]))},
            {"messages": [self.payload["messages"][1], self.payload["messages"][2]]},
            {"messages": [self.payload["messages"][0], {**self.payload["messages"][1], "position": 0}]},
            {"messages": [self.payload["messages"][0], {**self.payload["messages"][1], "content": " "}]},
        ]:
            with self.subTest(change=change):
                self.assertEqual(self.save({**self.payload, **change}).status_code, 422)
        self.assertEqual(self.save(cookie="other").status_code, 403)
        self.assertEqual(self.save(cookie="own-two").status_code, 403)
        self.assertEqual(self.save({**self.payload, "thread_id": "prod:own:chat"}).status_code, 400)
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.client.get("/api/logistics/agent/training-rounds?cookie_id=own-two").json()["rounds"], [])
        self.assertEqual(self.client.get(f"/api/logistics/agent/training-rounds/{self.payload['id']}/export?cookie_id=own-two").status_code, 404)
        self.user["user_id"] = 2
        self.assertEqual(self.client.get("/api/logistics/agent/training-rounds?cookie_id=own").status_code, 403)
        self.assertEqual(self.client.get(f"/api/logistics/agent/training-rounds/{self.payload['id']}/export?cookie_id=other").status_code, 404)

    def test_legacy_count_and_migration_are_accurate_and_repeatable(self):
        old = [{"thread_id": "test-example", "buyer_message": "问", "agent_reply": "答", "decision": {"reason": "ok"}}]
        url = "/api/logistics/agent/training-samples?cookie_id=own"
        self.assertEqual(self.client.post(url, json=old).json()["saved"], 1)
        self.assertEqual(self.client.post(url, json=old).json()["saved"], 0)
        for _ in range(2):
            self.db.close()
            self.db.init_db()
        rows = self.client.get("/api/logistics/agent/training-rounds?cookie_id=own").json()["rounds"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["name"].startswith("历史训练样本"))
        self.assertEqual(rows[0]["messages"][1]["decision"], {"reason": "ok"})


if __name__ == "__main__":
    unittest.main()
