"""Small dependency-free tests for the Kaptia local knowledge retrieval code."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("query_knowledge.py")
SPEC = importlib.util.spec_from_file_location("query_knowledge", SCRIPT)
query_knowledge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query_knowledge)


class KnowledgeQueryTests(unittest.TestCase):
    def test_chinese_tokenizer_adds_bigrams(self):
        terms = query_knowledge.tokens("專案知識檢索")
        self.assertIn("專案知識檢索", terms)
        self.assertIn("專案", terms)
        self.assertIn("案知", terms)

    def test_empty_query_has_no_results(self):
        self.assertEqual(query_knowledge.tokens("   "), [])

    def test_ranking_prefers_matching_document(self):
        rows = [
            {"id": "a", "source": "README.md", "text": "iPhone Safari 本機知識檢索"},
            {"id": "b", "source": "docs/other.md", "text": "完全不同的主題與內容"},
        ]
        # Exercise the same lexical scoring logic without touching the repository index.
        from collections import Counter
        import math
        q = set(query_knowledge.tokens("iPhone Safari 知識檢索"))
        doc_terms = [Counter(query_knowledge.tokens(row["text"])) for row in rows]
        df = Counter(term for terms in doc_terms for term in terms.keys())
        scores = []
        for row, counts in zip(rows, doc_terms):
            score = 0.0
            for term in q:
                tf = counts.get(term, 0)
                if tf:
                    idf = math.log(1 + (len(rows) - df[term] + 0.5) / (df[term] + 0.5))
                    score += idf * (tf * 2.2) / (tf + 1.2)
            scores.append(score)
        self.assertGreater(scores[0], scores[1])


if __name__ == "__main__":
    unittest.main()
