"""Regression tests for Kaptia's optional extended tools; no network/model required."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaptia_extended_tools as tools


class CalculatorTests(unittest.TestCase):
    def test_arithmetic_and_precedence(self):
        result = tools.calculate("2 + 3 * (4 ** 2)")
        self.assertTrue(result["ok"])
        self.assertEqual(result["value"], 50)

    def test_division_by_zero_fails_closed(self):
        result = tools.calculate("1 / 0")
        self.assertFalse(result["ok"])

    def test_names_calls_and_attributes_are_rejected(self):
        for expression in ("__import__('os')", "open('secret')", "x + 1", "(1).__class__"):
            with self.subTest(expression=expression):
                self.assertFalse(tools.calculate(expression)["ok"])

    def test_boolean_is_not_a_number(self):
        self.assertFalse(tools.calculate("True + 1")["ok"])

    def test_expression_and_exponent_limits(self):
        self.assertFalse(tools.calculate("1" * 301)["ok"])
        self.assertFalse(tools.calculate("2 ** 101")["ok"])

    def test_non_finite_or_excessive_results_rejected(self):
        self.assertFalse(tools.calculate("1e309")["ok"])
        self.assertFalse(tools.calculate("10 ** 100")["ok"])


class DispatchAndDomainTests(unittest.TestCase):
    def test_dispatch_rejects_unknown_tool(self):
        result = tools.dispatch_tool("execute_shell", {"command": "whoami"})
        self.assertFalse(result["ok"])
        self.assertIn("allowed_tools", result)

    def test_dispatch_requires_object_arguments(self):
        result = tools.dispatch_tool("calculate", ["1+1"])
        self.assertFalse(result["ok"])

    def test_dispatch_rejects_unknown_arguments(self):
        result = tools.dispatch_tool("calculate", {"expression": "1+1", "extra": True})
        self.assertFalse(result["ok"])

    def test_search_input_limits_are_checked_before_network(self):
        self.assertFalse(tools.web_search("", 5)["ok"])
        self.assertFalse(tools.web_search("x", True)["ok"])
        self.assertFalse(tools.web_search("x", 9)["ok"])

    def test_missing_domain_config_returns_safe_defaults(self):
        with patch.object(tools, "DOMAIN_CONFIG", Path("/path/that/does/not/exist/kaptia-domain.json")):
            config = tools.get_domain_config()
        self.assertFalse(config["enabled"])
        self.assertEqual(config["allowed_topics"], [])

    def test_malformed_domain_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.json"
            path.write_text(json.dumps({"enabled": True, "allowed_topics": "not-a-list"}), encoding="utf-8")
            with patch.object(tools, "DOMAIN_CONFIG", path):
                with self.assertRaises(ValueError):
                    tools.get_domain_config()


class RagIndexPointerTests(unittest.TestCase):
    def test_invalid_pointer_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = root / "CURRENT"
            indexes = root / "indexes"
            indexes.mkdir()
            pointer.write_text("../outside", encoding="ascii")
            with patch.object(tools, "VECTOR_DIR", root), \
                 patch.object(tools, "CURRENT_INDEX_FILE", pointer), \
                 patch.object(tools, "INDEXES_DIR", indexes):
                with self.assertRaises(ValueError):
                    tools._resolve_active_index_dir()

    def test_current_resolves_only_valid_versioned_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            indexes = root / "indexes"
            index_id = "index-" + "a" * 32
            index_dir = indexes / index_id
            index_dir.mkdir(parents=True)
            pointer = root / "CURRENT"
            pointer.write_text(index_id + "\n", encoding="ascii")
            with patch.object(tools, "VECTOR_DIR", root), \
                 patch.object(tools, "CURRENT_INDEX_FILE", pointer), \
                 patch.object(tools, "INDEXES_DIR", indexes):
                self.assertEqual(tools._resolve_active_index_dir(), index_dir)

    def test_missing_pointer_allows_legacy_layout_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("vectors.npy", "documents.json", "manifest.json"):
                (root / name).write_text("legacy", encoding="utf-8")
            with patch.object(tools, "VECTOR_DIR", root), \
                 patch.object(tools, "CURRENT_INDEX_FILE", root / "CURRENT"), \
                 patch.object(tools, "INDEXES_DIR", root / "indexes"):
                self.assertEqual(tools._resolve_active_index_dir(), root)

    def test_atomic_pointer_switch_preserves_previous_pointer_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            pointer = root / "CURRENT"
            pointer.write_text("index-" + "b" * 32 + "\n", encoding="ascii")
            with patch.object(tools, "VECTOR_DIR", root), \
                 patch.object(tools, "CURRENT_INDEX_FILE", pointer), \
                 patch("kaptia_extended_tools.os.replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    tools._publish_index_pointer("index-" + "c" * 32)
            self.assertEqual(pointer.read_text(encoding="ascii").strip(), "index-" + "b" * 32)


class HybridRetrievalTests(unittest.TestCase):
    def test_lexical_tokens_cover_latin_and_chinese_ngrams(self):
        tokens = tools._lexical_tokens("RAG 向量檢索")
        self.assertIn("rag", tokens)
        self.assertIn("向量", tokens)
        self.assertIn("檢索", tokens)

    def test_hybrid_rank_can_promote_exact_lexical_match(self):
        docs = [
            {"text": "一般向量資料庫介紹", "source": "a.md", "chunk": 0},
            {"text": "RAG 向量檢索錯誤修復步驟", "source": "b.md", "chunk": 0},
        ]
        # Vector-only order prefers doc 0, while lexical evidence strongly matches doc 1.
        ranked = tools._hybrid_rank("RAG 向量檢索錯誤修復", docs, [0.95, 0.70], 2)
        self.assertEqual(ranked[0][0], 1)

    def test_hybrid_rank_respects_top_k(self):
        docs = [{"text": f"資料 {i}", "source": "x.md", "chunk": i} for i in range(6)]
        ranked = tools._hybrid_rank("資料", docs, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], 3)
        self.assertEqual(len(ranked), 3)


class ReviewScopeRoutingTests(unittest.TestCase):
    def test_specific_virology_scope_is_detected_ahead_of_biology(self):
        result = tools.detect_review_scope("請以生物學角度審查這份病毒學研究")
        self.assertTrue(result["ok"])
        self.assertEqual(result["scope"], "virology")
        self.assertIn("biology", [item["id"] for item in result["matches"]])
        self.assertIn("病毒學", result["scope_label"])

    def test_english_domain_alias_is_supported(self):
        result = tools.detect_review_scope("Review this paper from a virology perspective")
        self.assertEqual(result["scope"], "virology")

    def test_unmatched_query_does_not_force_a_domain(self):
        result = tools.detect_review_scope("幫我整理這段內容")
        self.assertIsNone(result["scope"])
        self.assertTrue(result["needs_clarification"])

    def test_scoped_retrieval_expands_query_and_preserves_evidence(self):
        fake = {
            "ok": True,
            "results": [{"source": "virus.md", "chunk": 2, "text": "病毒複製相關筆記"}],
            "retrieval": "reciprocal_rank_fusion(vector+lexical)",
        }
        with patch.object(tools, "search_user_documents", return_value=fake) as search:
            result = tools.retrieve_scoped_knowledge("審查病毒學研究")
        self.assertTrue(result["ok"])
        self.assertEqual(result["scope"], "virology")
        self.assertEqual(result["evidence"][0]["source"], "virus.md")
        self.assertIn("病毒學", search.call_args.args[0])
        self.assertTrue(result["synthesis_plan"])


class EmbeddingModelCacheTests(unittest.TestCase):
    def setUp(self):
        self.old_model = tools._EMBEDDING_MODEL
        self.old_name = tools._EMBEDDING_MODEL_NAME
        tools._EMBEDDING_MODEL = None
        tools._EMBEDDING_MODEL_NAME = None

    def tearDown(self):
        tools._EMBEDDING_MODEL = self.old_model
        tools._EMBEDDING_MODEL_NAME = self.old_name

    def test_same_model_name_loads_only_once(self):
        import sys
        import types
        from unittest.mock import patch
        calls = []

        class FakeModel:
            def __init__(self, name):
                self.name = name
                calls.append(name)

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeModel
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            first = tools._get_embedding_model("fake/model")
            second = tools._get_embedding_model("fake/model")
        self.assertIs(first, second)
        self.assertEqual(calls, ["fake/model"])

    def test_model_switch_retains_only_selected_model(self):
        import sys
        import types
        from unittest.mock import patch
        calls = []

        class FakeModel:
            def __init__(self, name):
                self.name = name
                calls.append(name)

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeModel
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            first = tools._get_embedding_model("fake/first")
            second = tools._get_embedding_model("fake/second")
        self.assertIsNot(first, second)
        self.assertIs(tools._EMBEDDING_MODEL, second)
        self.assertEqual(tools._EMBEDDING_MODEL_NAME, "fake/second")
        self.assertEqual(calls, ["fake/first", "fake/second"])


if __name__ == "__main__":
    unittest.main()
