"""Bounded web research loop with provenance and deterministic archive gates."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol
from urllib.parse import urlsplit
import hashlib, ipaddress, time

def utc_now():
    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class ResearchBudget:
    max_rounds: int = 4
    max_searches: int = 12
    max_sources: int = 30
    max_wall_seconds: float = 300.0
    max_energy_wh: float | None = None
    def __post_init__(self):
        if isinstance(self.max_rounds, bool) or not 1 <= self.max_rounds <= 20: raise ValueError("max_rounds 必須介於 1 到 20")
        if isinstance(self.max_searches, bool) or not 1 <= self.max_searches <= 100: raise ValueError("max_searches 必須介於 1 到 100")
        if isinstance(self.max_sources, bool) or not 1 <= self.max_sources <= 200: raise ValueError("max_sources 必須介於 1 到 200")
        if not 0 < self.max_wall_seconds <= 86400: raise ValueError("max_wall_seconds 無效")
        if self.max_energy_wh is not None and self.max_energy_wh <= 0: raise ValueError("max_energy_wh 必須大於 0")

@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None

@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    title: str
    text: str
    content_type: str = "text/html"
    fetched_at: str = field(default_factory=utc_now)

@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    title: str
    url: str
    domain: str
    snippet: str
    content: str
    published_at: str | None
    fetched_at: str
    content_hash: str

@dataclass(frozen=True)
class ResearchReview:
    sufficient: bool
    follow_up_queries: tuple[str, ...] = ()
    rationale: str = ""

@dataclass(frozen=True)
class ResearchReport:
    query: str
    answer: str
    sources: tuple[ResearchSource, ...]
    rounds: int
    searches: int
    quality_score: float
    passed: bool
    stop_reason: str
    issues: tuple[str, ...]
    elapsed_seconds: float
    energy_wh: float | None
    created_at: str = field(default_factory=utc_now)
    def to_dict(self):
        return {"query":self.query,"answer":self.answer,"sources":[asdict(x) for x in self.sources],
                "rounds":self.rounds,"searches":self.searches,"quality_score":self.quality_score,
                "passed":self.passed,"stop_reason":self.stop_reason,"issues":list(self.issues),
                "elapsed_seconds":self.elapsed_seconds,"energy_wh":self.energy_wh,"created_at":self.created_at}

class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int) -> Iterable[SearchHit]: ...
class PageFetcher(Protocol):
    def fetch(self, url: str, *, max_bytes: int) -> FetchedPage: ...
class AnswerSynthesizer(Protocol):
    def synthesize(self, query: str, sources: tuple[ResearchSource, ...]) -> str: ...
class ResearchReviewer(Protocol):
    def review(self, query: str, answer: str, sources: tuple[ResearchSource, ...]) -> ResearchReview: ...
class EnergyMeter(Protocol):
    def energy_wh(self) -> float: ...
class KnowledgeArchive(Protocol):
    def archive(self, report: ResearchReport) -> str: ...

class ResearchSafetyError(ValueError): pass

def validate_public_http_url(url: str) -> str:
    if not isinstance(url,str) or len(url)>2048: raise ResearchSafetyError("URL 無效")
    p=urlsplit(url.strip())
    if p.scheme not in {"http","https"} or not p.hostname: raise ResearchSafetyError("只允許完整 HTTP/HTTPS URL")
    if p.username or p.password: raise ResearchSafetyError("URL 不可包含帳密")
    host=p.hostname.rstrip(".").lower()
    if host=="localhost" or host.endswith(".localhost"): raise ResearchSafetyError("禁止 localhost")
    try: addr=ipaddress.ip_address(host)
    except ValueError: addr=None
    if addr is not None and (not addr.is_global or addr.is_multicast): raise ResearchSafetyError("禁止非公開 IP")
    return url.strip()

def _domain(url):
    host=(urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host

class ResearchEngine:
    def __init__(self, search: SearchProvider, fetcher: PageFetcher, synthesizer: AnswerSynthesizer,
                 reviewer: ResearchReviewer, *, max_page_bytes=1_000_000,
                 clock: Callable[[],float]=time.monotonic, energy_meter: EnergyMeter|None=None):
        if not 1024 <= max_page_bytes <= 5_000_000: raise ValueError("max_page_bytes 無效")
        self.search,self.fetcher,self.synthesizer,self.reviewer=search,fetcher,synthesizer,reviewer
        self.max_page_bytes,self.clock,self.energy_meter=max_page_bytes,clock,energy_meter

    def run(self, query: str, *, budget=ResearchBudget(), min_sources=3, min_domains=2,
            archive: KnowledgeArchive|None=None) -> ResearchReport:
        if not isinstance(query,str) or not query.strip() or len(query)>2000: raise ValueError("query 無效")
        if not 1<=min_sources<=20 or not 1<=min_domains<=min_sources: raise ValueError("來源門檻無效")
        started=self.clock()
        energy_start=self.energy_meter.energy_wh() if self.energy_meter else None
        sources={}; seen=set(); pending=[query.strip()]; searches=0; rounds=0; answer=""
        stop="round_limit"
        for round_no in range(1,budget.max_rounds+1):
            if not pending: stop="no_new_queries"; break
            if self.clock()-started>=budget.max_wall_seconds: stop="time_budget"; break
            if len(sources)>=budget.max_sources: stop="source_budget"; break
            if self.energy_meter and budget.max_energy_wh is not None:
                if self.energy_meter.energy_wh()-(energy_start or 0)>=budget.max_energy_wh: stop="energy_budget"; break
            rounds=round_no; queries=[]
            for q in pending:
                key=" ".join(q.split()).casefold()
                if key and key not in seen: seen.add(key); queries.append(q)
            pending=[]
            if not queries: stop="no_new_queries"; break
            for q in queries:
                if searches>=budget.max_searches: stop="search_budget"; break
                if self.clock()-started>=budget.max_wall_seconds: stop="time_budget"; break
                hits=self.search.search(q,limit=min(10,budget.max_sources)); searches+=1
                for hit in hits:
                    if len(sources)>=budget.max_sources: break
                    try:
                        url=validate_public_http_url(hit.url)
                        page=self.fetcher.fetch(url,max_bytes=self.max_page_bytes)
                        final=validate_public_http_url(page.final_url)
                        if page.content_type.split(";",1)[0].strip().lower() not in {"text/html","text/plain","application/xhtml+xml"}: continue
                        if not page.text.strip(): continue
                        digest=hashlib.sha256(page.text.encode("utf-8",errors="replace")).hexdigest()
                        if digest in sources: continue
                        sources[digest]=ResearchSource(digest[:16],(page.title or hit.title)[:500],final,_domain(final),
                            hit.snippet[:2000],page.text[:self.max_page_bytes],hit.published_at,page.fetched_at,digest)
                    except (ResearchSafetyError,ValueError,TimeoutError,OSError): continue
            source_tuple=tuple(sources.values())
            answer=self.synthesizer.synthesize(query.strip(),source_tuple) if source_tuple else ""
            review=self.reviewer.review(query.strip(),answer,source_tuple)
            if not isinstance(review,ResearchReview): raise TypeError("reviewer 必須回傳 ResearchReview")
            if review.sufficient: stop="quality_gate_passed"; break
            pending.extend(q for q in review.follow_up_queries if isinstance(q,str) and q.strip())
            if not pending: stop="review_no_followups"; break
        elapsed=max(0.0,self.clock()-started)
        energy=max(0.0,self.energy_meter.energy_wh()-(energy_start or 0)) if self.energy_meter else None
        domains=len({s.domain for s in sources.values()}); count=len(sources)
        score=min(1.0,.45*min(count/min_sources,1)+.35*min(domains/min_domains,1)+.20*bool(answer.strip()))
        passed=score>=.90 and count>=min_sources and domains>=min_domains and stop=="quality_gate_passed"
        issues=[]
        if not answer.strip(): issues.append("沒有可用來源或無法產生答案")
        if count<min_sources: issues.append(f"來源不足：{count}/{min_sources}")
        if domains<min_domains: issues.append(f"獨立網域不足：{domains}/{min_domains}")
        if stop!="quality_gate_passed": issues.append(f"研究停止原因：{stop}")
        report=ResearchReport(query.strip(),answer,tuple(sources.values()),rounds,searches,round(score,4),passed,
                              stop,tuple(issues),round(elapsed,3),round(energy,4) if energy is not None else None)
        if archive is not None and report.passed: archive.archive(report)
        return report
