import unittest
from unittest.mock import patch
from kaptia_research_runtime import QwenResearchReviewer, QwenResearchSynthesizer, SafeHTTPPageFetcher

class ResearchAdapterTests(unittest.TestCase):
    def test_reviewer_fails_closed_on_invalid_json(self):
        reviewer=QwenResearchReviewer(lambda *a,**k:"not json")
        result=reviewer.review("q","a",())
        self.assertFalse(result.sufficient)
        self.assertEqual(result.follow_up_queries,())
    def test_reviewer_parses_bounded_followups(self):
        reviewer=QwenResearchReviewer(lambda *a,**k:'{"sufficient":false,"follow_up_queries":["one","two","three","four"],"rationale":"gap"}')
        result=reviewer.review("q","a",())
        self.assertFalse(result.sufficient)
        self.assertEqual(len(result.follow_up_queries),3)
    def test_synthesizer_includes_source_provenance_and_untrusted_warning(self):
        from core_foundation.research import ResearchSource
        seen={}
        def fake(messages,**kwargs):
            seen["prompt"]=messages[0]["content"]
            return "answer"
        source=ResearchSource("id","Title","https://example.com","example.com","snippet","content",None,"now","hash")
        answer=QwenResearchSynthesizer(fake).synthesize("question",(source,))
        self.assertEqual(answer,"answer")
        self.assertIn("https://example.com",seen["prompt"])
        self.assertIn("不可信資料",seen["prompt"])
    def test_fetcher_rejects_private_dns_before_socket(self):
        fetcher=SafeHTTPPageFetcher()
        with patch("kaptia_research_runtime.socket.getaddrinfo",return_value=[(2,1,6,"",("127.0.0.1",80))]):
            with self.assertRaises(ValueError):
                fetcher._resolve_public("example.com",80)

if __name__=="__main__": unittest.main()
