import tempfile, unittest
from pathlib import Path
from core_foundation.knowledge_archive import SQLiteKnowledgeArchive
from core_foundation.research import *

class Search:
    def __init__(self,rows): self.rows,self.calls=rows,[]
    def search(self,q,*,limit): self.calls.append(q); return self.rows.get(q,[])
class Fetch:
    def __init__(self,pages): self.pages=pages
    def fetch(self,url,*,max_bytes): return self.pages[url]
class Synth:
    def synthesize(self,q,sources): return "Evidence-based answer" if sources else ""
class Review:
    def __init__(self,items): self.items=iter(items)
    def review(self,q,a,s): return next(self.items)
class Clock:
    def __init__(self): self.t=0
    def __call__(self): self.t+=.1; return self.t
def mkpage(url,title): return FetchedPage(url,url,title,"Content for "+title)

class ResearchTests(unittest.TestCase):
    def engine(self,rows,pages,reviews):
        s=Search(rows); f=Fetch(pages)
        return ResearchEngine(s,f,Synth(),Review(reviews),clock=Clock()),s
    def test_url_policy_blocks_local_addresses_and_credentials(self):
        for u in ["http://localhost/","http://127.0.0.1/","http://192.168.1.2/","file:///etc/passwd","https://a:b@example.com/"]:
            with self.assertRaises(ResearchSafetyError): validate_public_http_url(u)
    def test_researches_followup_and_passes(self):
        urls=["https://alpha.example/a","https://beta.example/b","https://gamma.example/c"]
        rows={"topic":[SearchHit("A",urls[0]),SearchHit("B",urls[1])],"more":[SearchHit("C",urls[2])]}
        pages={u:mkpage(u,str(i)) for i,u in enumerate(urls)}
        e,s=self.engine(rows,pages,[ResearchReview(False,("more",)),ResearchReview(True)])
        r=e.run("topic",budget=ResearchBudget(max_rounds=3))
        self.assertTrue(r.passed); self.assertEqual(r.searches,2); self.assertEqual(len(r.sources),3)
    def test_unverified_report_not_archived(self):
        u="https://alpha.example/a"; e,_=self.engine({"topic":[SearchHit("A",u)]},{u:mkpage(u,"A")},[ResearchReview(False)])
        with tempfile.TemporaryDirectory() as d:
            a=SQLiteKnowledgeArchive(Path(d)/"knowledge.sqlite3"); r=e.run("topic",archive=a)
            self.assertFalse(r.passed); self.assertEqual(a.search("topic"),[])
    def test_verified_report_archived(self):
        us=["https://alpha.example/a","https://beta.example/b","https://gamma.example/c"]
        e,_=self.engine({"topic":[SearchHit(x,x) for x in us]},{u:mkpage(u,u) for u in us},[ResearchReview(True)])
        with tempfile.TemporaryDirectory() as d:
            a=SQLiteKnowledgeArchive(Path(d)/"k.sqlite3"); r=e.run("topic",archive=a)
            self.assertTrue(r.passed); self.assertEqual(len(a.search("topic")),1)
    def test_search_budget_and_duplicate_query_stops(self):
        e,s=self.engine({"topic":[]},{},[ResearchReview(False,("topic",))])
        r=e.run("topic",budget=ResearchBudget(max_rounds=5,max_searches=1))
        self.assertEqual(r.stop_reason,"no_new_queries"); self.assertEqual(s.calls,["topic"])
    def test_invalid_budgets_rejected(self):
        with self.assertRaises(ValueError): ResearchBudget(max_rounds=0)

if __name__=="__main__": unittest.main()
