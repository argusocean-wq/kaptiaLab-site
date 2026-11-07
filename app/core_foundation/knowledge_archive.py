"""SQLite archive for research reports that passed evidence gates."""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path
from .research import ResearchReport

class SQLiteKnowledgeArchive:
    def __init__(self,database_path):
        self.database_path=str(database_path)
        Path(self.database_path).parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""CREATE TABLE IF NOT EXISTS verified_knowledge(
                report_id TEXT PRIMARY KEY, query TEXT NOT NULL, quality_score REAL NOT NULL,
                report_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    def _connect(self):
        c=sqlite3.connect(self.database_path,timeout=10); c.row_factory=sqlite3.Row; return c
    def archive(self,report:ResearchReport)->str:
        if not isinstance(report,ResearchReport) or not report.passed:
            raise ValueError("只有通過品質門檻的研究報告可以封存")
        payload=report.to_dict()
        rid=hashlib.sha256((report.query+report.created_at+json.dumps(payload,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO verified_knowledge VALUES(?,?,?,?,?)",
                (rid,report.query,report.quality_score,json.dumps(payload,ensure_ascii=False),report.created_at))
        return rid
    def search(self,query,*,limit=10):
        if not isinstance(query,str) or not query.strip(): raise ValueError("query 不可為空")
        if isinstance(limit,bool) or not 1<=limit<=100: raise ValueError("limit 必須介於 1 到 100")
        with self._connect() as c:
            rows=c.execute("SELECT * FROM verified_knowledge WHERE query LIKE ? ORDER BY quality_score DESC,created_at DESC LIMIT ?",
                           (f"%{query.strip()}%",limit)).fetchall()
        return [{"report_id":r["report_id"],"query":r["query"],"quality_score":r["quality_score"],
                 "report":json.loads(r["report_json"]),"created_at":r["created_at"]} for r in rows]
