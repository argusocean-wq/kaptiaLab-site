import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from cloud_worker import app as worker


class CloudWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.sqlite3"
        self.db_patch = mock.patch.object(worker, "DB_PATH", self.db)
        self.db_patch.start()
        self.token_patch = mock.patch.object(worker, "TOKEN", "t" * 32)
        self.token_patch.start()

    def tearDown(self):
        self.token_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_auth_requires_bearer_scheme(self):
        with self.assertRaises(HTTPException) as caught:
            worker._auth("t" * 32)
        self.assertEqual(caught.exception.status_code, 401)

    def test_auth_uses_constant_time_token_check(self):
        worker._auth("Bearer " + "t" * 32)
        with self.assertRaises(HTTPException):
            worker._auth("Bearer " + "x" * 32)

    def test_restart_marks_interrupted_jobs_failed_and_erases_source(self):
        with worker._db() as con:
            con.execute(
                "INSERT INTO jobs(id,task_type,status,created,updated,timeout,source) "
                "VALUES(?,?,?,?,?,?,?)",
                ("interrupted-job-0001", "python_script", "running", 1, 1, 30, "secret source"),
            )
        worker._recover_and_prune()
        with worker._db() as con:
            row = con.execute(
                "SELECT status,source,stderr,exit_code FROM jobs WHERE id=?",
                ("interrupted-job-0001",),
            ).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], "")
        self.assertIn("restarted", row[2])
        self.assertEqual(row[3], -2)

    def test_prunes_old_terminal_jobs(self):
        with worker._db() as con:
            con.execute(
                "INSERT INTO jobs(id,task_type,status,created,updated,timeout,source) "
                "VALUES(?,?,?,?,?,?,?)",
                ("old-finished-job-001", "python_script", "completed", 1, 1, 30, ""),
            )
        worker._recover_and_prune()
        with worker._db() as con:
            row = con.execute(
                "SELECT 1 FROM jobs WHERE id=?", ("old-finished-job-001",)
            ).fetchone()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
