"""Free-first public business discovery and evidence-bound website enrichment.

This module deliberately avoids logging into, bypassing, or scraping restricted
social platforms.  Search results may reference public profiles, but business
facts are collected from public company websites and explicitly allowed
business directories only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import fetch_public_text, validate_public_url

_EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)")
_SPACE_RE = re.compile(r"\s+")
_RESTRICTED_HOSTS = {
    "linkedin.com",
    "www.linkedin.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "maps.google.com",
    "www.google.com",
    "google.com",
}
_SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "x.com": "x",
    "www.x.com": "x",
    "twitter.com": "x",
    "www.twitter.com": "x",
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
}
_CONTACT_HINTS = ("contact", "about", "team", "services", "book", "enquiry", "inquiry")
_GENERIC_EMAIL_PREFIXES = {
    "info",
    "hello",
    "contact",
    "sales",
    "support",
    "office",
    "admin",
    "team",
    "business",
    "enquiries",
    "enquiry",
    "help",
}


def _clean_text(value: str, limit: int = 1000) -> str:
    return _SPACE_RE.sub(" ", unescape(str(value or ""))).strip()[:limit]


def normalize_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    if not hostname or "." not in hostname:
        return ""
    return hostname


def canonical_public_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port and parsed.port not in {80, 443} else ""
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme, hostname + port, path, parsed.query, ""))


def _unwrap_search_redirect(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname and "duckduckgo.com" in parsed.hostname:
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return url


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 20) -> list[SearchHit]: ...


class DuckDuckGoSearchProvider:
    """Use the open search client with a strict bounded result contract."""

    def __init__(self, *, backend_factory: Callable[[], Any] | None = None) -> None:
        self.backend_factory = backend_factory

    def _backend(self) -> Any:
        if self.backend_factory is not None:
            return self.backend_factory()
        try:
            from ddgs import DDGS
        except ImportError as exc:  # pragma: no cover - dependency is part of release
            raise GovernanceError("ddgs is not installed") from exc
        return DDGS()

    def search(self, query: str, *, max_results: int = 20) -> list[SearchHit]:
        clean_query = _clean_text(query, 300)
        if len(clean_query) < 3:
            raise GovernanceError("Lead discovery query is too short")
        limit = max(1, min(int(max_results), 50))
        try:
            backend = self._backend()
            rows = backend.text(clean_query, max_results=limit)
            results = list(rows)
        except Exception as exc:
            raise GovernanceError("Public search provider failed") from exc
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for row in results:
            if not isinstance(row, dict):
                continue
            url = _unwrap_search_redirect(str(row.get("href") or row.get("url") or ""))
            canonical = canonical_public_url(url)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            hits.append(
                SearchHit(
                    title=_clean_text(str(row.get("title", "")), 300),
                    url=canonical,
                    snippet=_clean_text(str(row.get("body") or row.get("snippet") or ""), 800),
                )
            )
            if len(hits) >= limit:
                break
        return hits


@dataclass(slots=True)
class WebsiteProfile:
    source_url: str
    final_url: str
    domain: str
    company_name: str = ""
    title: str = ""
    description: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    social_urls: dict[str, str] = field(default_factory=dict)
    contact_pages: list[str] = field(default_factory=list)
    has_contact_form: bool = False
    has_viewport: bool = False
    uses_https: bool = False
    word_count: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: str = ""
    content_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RobotsPolicy:
    def __init__(self, fetcher: Callable[..., str] = fetch_public_text) -> None:
        self.fetcher = fetcher
        self._cache: dict[str, RobotFileParser] = {}

    def allowed(self, url: str, user_agent: str = "Amaura-Evidence-Fetcher") -> bool:
        parsed = urlsplit(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._cache.get(root)
        if parser is None:
            parser = RobotFileParser()
            parser.set_url(root + "/robots.txt")
            try:
                text = self.fetcher(root + "/robots.txt", max_length=200_000)
                parser.parse(text.splitlines())
            except Exception:
                # Fail closed.  RobotFileParser.parse([]) means "allow all",
                # which contradicted the policy comment and silently converted
                # network failures into crawl permission.
                parser.__dict__["disallow_all"] = True
            self._cache[root] = parser
        return parser.can_fetch(user_agent, url)


class WebsiteEnricher:
    """Extract minimum public business facts from a small, bounded page set."""

    def __init__(
        self,
        *,
        fetcher: Callable[..., str] = fetch_public_text,
        robots: RobotsPolicy | None = None,
        max_pages: int = 3,
    ) -> None:
        self.fetcher = fetcher
        self.robots = robots or RobotsPolicy(fetcher)
        self.max_pages = max(1, min(int(max_pages), 5))

    @staticmethod
    def _safe_email(value: str, domain: str) -> bool:
        email = value.lower().strip(".,;:()[]{}<>\"'")
        if len(email) > 254 or ".." in email:
            return False
        local, _, host = email.partition("@")
        if not local or not host or host.endswith(("example.com", "sentry.io")):
            return False
        # Prefer role/business addresses; retain same-domain public addresses.
        return local.split("+", 1)[0] in _GENERIC_EMAIL_PREFIXES or normalize_domain(host) == domain

    @staticmethod
    def _extract_company_name(soup: BeautifulSoup, domain: str) -> str:
        candidates: list[str] = []
        og = soup.find("meta", attrs={"property": "og:site_name"})
        if og and og.get("content"):
            candidates.append(str(og.get("content")))
        title = soup.title.string if soup.title and soup.title.string else ""
        if title:
            candidates.extend(re.split(r"[|–—-]", title, maxsplit=1)[:1])
        for candidate in candidates:
            cleaned = _clean_text(candidate, 160)
            if len(cleaned) >= 2:
                return cleaned
        return domain.split(".")[0].replace("-", " ").title()

    def _fetch(self, url: str) -> tuple[str, str]:
        validate_public_url(url, resolve=True)
        if not self.robots.allowed(url):
            raise GovernanceError("robots.txt does not allow this evidence fetch")
        return self.fetcher(url, max_length=750_000), url

    def enrich(self, url: str) -> WebsiteProfile:
        canonical = canonical_public_url(url)
        domain = normalize_domain(canonical)
        if not canonical or not domain:
            raise GovernanceError("A valid public company website URL is required")
        if urlsplit(canonical).hostname in _RESTRICTED_HOSTS:
            raise GovernanceError("Restricted platform pages are not scraped")

        html, final_url = self._fetch(canonical)
        digest = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()
        soup = BeautifulSoup(html, "html.parser")
        profile = WebsiteProfile(
            source_url=canonical,
            final_url=final_url,
            domain=domain,
            company_name=self._extract_company_name(soup, domain),
            title=_clean_text(soup.title.string if soup.title and soup.title.string else "", 300),
            uses_https=urlsplit(canonical).scheme == "https",
            fetched_at=datetime.now(UTC).isoformat(),
            content_sha256=digest,
        )
        description = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        if description and description.get("content"):
            profile.description = _clean_text(str(description.get("content")), 700)
        profile.has_viewport = bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}))
        text = _clean_text(soup.get_text(" ", strip=True), 200_000)
        profile.word_count = len(text.split())

        pages: list[tuple[str, BeautifulSoup, str]] = [(canonical, soup, text)]
        candidate_links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(canonical, str(anchor.get("href", "")))
            parsed = urlsplit(href)
            host = (parsed.hostname or "").lower()
            label = _clean_text(anchor.get_text(" ", strip=True), 120).lower()
            if host in _SOCIAL_HOSTS:
                profile.social_urls.setdefault(_SOCIAL_HOSTS[host], href.split("#", 1)[0])
                continue
            if normalize_domain(host) != domain:
                continue
            normalized = canonical_public_url(href)
            if normalized and any(hint in (parsed.path.lower() + " " + label) for hint in _CONTACT_HINTS):
                if normalized not in candidate_links and normalized != canonical:
                    candidate_links.append(normalized)

        for page_url in candidate_links[: self.max_pages - 1]:
            try:
                page_html, _ = self._fetch(page_url)
            except Exception:
                continue
            page_soup = BeautifulSoup(page_html, "html.parser")
            page_text = _clean_text(page_soup.get_text(" ", strip=True), 100_000)
            pages.append((page_url, page_soup, page_text))
            profile.contact_pages.append(page_url)

        emails: set[str] = set()
        phones: set[str] = set()
        for page_url, page_soup, page_text in pages:
            for email in _EMAIL_RE.findall(page_text):
                cleaned = email.lower().strip(".,;:()[]{}<>\"'")
                if self._safe_email(cleaned, domain):
                    emails.add(cleaned)
            for anchor in page_soup.find_all("a", href=True):
                href = str(anchor.get("href", ""))
                if href.lower().startswith("mailto:"):
                    address = href[7:].split("?", 1)[0].strip().lower()
                    if self._safe_email(address, domain):
                        emails.add(address)
                if href.lower().startswith("tel:"):
                    number = re.sub(r"[^+\d]", "", href[4:])
                    if 8 <= len(re.sub(r"\D", "", number)) <= 15:
                        phones.add(number)
            for match in _PHONE_RE.findall(page_text):
                number = re.sub(r"[^+\d]", "", match)
                digits = re.sub(r"\D", "", number)
                if 8 <= len(digits) <= 15:
                    phones.add(number)
            if page_soup.find("form"):
                profile.has_contact_form = True
            profile.observations.append(
                {
                    "claim_type": "public_page",
                    "claim": f"Public business page reviewed: {page_url}",
                    "source_url": page_url,
                    "source_excerpt": page_text[:500],
                    "confidence": 0.95,
                }
            )

        profile.emails = sorted(emails)[:5]
        profile.phones = sorted(phones)[:5]
        if not profile.has_contact_form:
            profile.observations.append(
                {
                    "claim_type": "conversion_gap",
                    "claim": "No HTML contact form was found on the reviewed pages.",
                    "source_url": canonical,
                    "source_excerpt": profile.title or profile.description or domain,
                    "confidence": 0.75,
                }
            )
        if not profile.has_viewport:
            profile.observations.append(
                {
                    "claim_type": "mobile_gap",
                    "claim": "The homepage does not declare a viewport meta tag.",
                    "source_url": canonical,
                    "source_excerpt": 'No <meta name="viewport"> detected in the retrieved HTML.',
                    "confidence": 0.9,
                }
            )
        if not profile.emails and not profile.phones:
            profile.observations.append(
                {
                    "claim_type": "contact_gap",
                    "claim": "No public business email or phone number was found on the reviewed pages.",
                    "source_url": canonical,
                    "source_excerpt": profile.description or profile.title or domain,
                    "confidence": 0.7,
                }
            )
        return profile


@dataclass(frozen=True, slots=True)
class DiscoveredBusiness:
    company_name: str
    domain: str
    website: str
    source_url: str
    source_title: str
    source_snippet: str
    social_urls: dict[str, str]
    emails: tuple[str, ...]
    phones: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    profile: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["emails"] = list(self.emails)
        data["phones"] = list(self.phones)
        data["observations"] = list(self.observations)
        return data


class FreeLeadDiscoveryService:
    """Find and enrich a small set of public businesses without paid APIs."""

    def __init__(
        self,
        *,
        search_provider: SearchProvider | None = None,
        enricher: WebsiteEnricher | None = None,
    ) -> None:
        self.search_provider = search_provider or DuckDuckGoSearchProvider()
        self.enricher = enricher or WebsiteEnricher()

    @staticmethod
    def _candidate_website(hit: SearchHit) -> bool:
        host = (urlsplit(hit.url).hostname or "").lower()
        if host in _RESTRICTED_HOSTS:
            return False
        if host.endswith((".pdf", ".jpg", ".png")):
            return False
        return bool(normalize_domain(host))

    def discover(self, query: str, *, max_results: int = 10) -> list[DiscoveredBusiness]:
        limit = max(1, min(int(max_results), 25))
        # Ask for extra search results because directories and social profiles are
        # retained only as source hints and are not directly crawled.
        hits = self.search_provider.search(query, max_results=min(50, limit * 4))
        businesses: list[DiscoveredBusiness] = []
        seen_domains: set[str] = set()
        for hit in hits:
            if not self._candidate_website(hit):
                continue
            domain = normalize_domain(hit.url)
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            try:
                profile = self.enricher.enrich(hit.url)
            except Exception:
                continue
            businesses.append(
                DiscoveredBusiness(
                    company_name=profile.company_name,
                    domain=profile.domain,
                    website=profile.final_url,
                    source_url=hit.url,
                    source_title=hit.title,
                    source_snippet=hit.snippet,
                    social_urls=dict(profile.social_urls),
                    emails=tuple(profile.emails),
                    phones=tuple(profile.phones),
                    observations=tuple(profile.observations),
                    profile=profile.to_dict(),
                )
            )
            if len(businesses) >= limit:
                break
        return businesses


class AcquisitionDiscoveryRunner:
    """Persist discovered businesses into the governed acquisition pipeline."""

    def __init__(self, pipeline: Any, service: FreeLeadDiscoveryService | None = None) -> None:
        self.pipeline = pipeline
        self.service = service or FreeLeadDiscoveryService()

    def run(
        self, *, campaign_id: str, query: str, max_results: int = 10, country: str = "", industry: str = ""
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for business in self.service.discover(query, max_results=max_results):
            primary_contact = business.emails[0] if business.emails else (business.phones[0] if business.phones else "")
            lead = self.pipeline.discover_lead(
                campaign_id=campaign_id,
                company_name=business.company_name,
                domain=business.domain,
                source_url=business.source_url,
                country=country,
                industry=industry,
                metadata={
                    "website": business.website,
                    "social_urls": business.social_urls,
                    "emails": list(business.emails),
                    "phones": list(business.phones),
                    "profile": business.profile,
                },
            )
            if lead.get("duplicate"):
                results.append({"lead": lead, "duplicate": True})
                continue
            if primary_contact:
                self.pipeline.store.update_lead(
                    lead["id"],
                    public_contact=primary_contact,
                    contact_source_url=business.website,
                    linkedin_url=business.social_urls.get("linkedin", ""),
                )
            try:
                self.pipeline.transition(
                    lead["id"], "researching", actor="lead_scout", reason="Public website enrichment started"
                )
            except Exception:
                pass
            accepted = 0
            for observation in business.observations[:12]:
                try:
                    self.pipeline.add_evidence(
                        lead["id"],
                        claim_type=str(observation.get("claim_type", "public_fact")),
                        claim=str(observation.get("claim", "Public business fact")),
                        source_url=str(observation.get("source_url") or business.website),
                        source_excerpt=str(
                            observation.get("source_excerpt") or business.source_snippet or business.source_title
                        ),
                        confidence=float(observation.get("confidence", 0.7)),
                        actor="public_source_enricher",
                    )
                    accepted += 1
                except Exception:
                    continue
            try:
                self.pipeline.transition(
                    lead["id"],
                    "researched",
                    actor="public_source_enricher",
                    reason="Bounded public-source enrichment completed",
                )
            except Exception:
                pass
            components = {
                "campaign_fit": 18,
                "visible_need": min(25, 12 + accepted * 3),
                "ability_to_pay": 12,
                "contactability": 15 if primary_contact else 4,
                "portfolio_match": 12,
            }
            scored = (
                self.pipeline.score_lead(lead["id"], components, actor="free_first_qualification")
                if accepted
                else self.pipeline.store.get_lead(lead["id"])
            )
            results.append({"lead": scored, "business": business.to_dict(), "evidence_accepted": accepted})
        return results


__all__ = [
    "AcquisitionDiscoveryRunner",
    "DiscoveredBusiness",
    "DuckDuckGoSearchProvider",
    "FreeLeadDiscoveryService",
    "RobotsPolicy",
    "SearchHit",
    "SearchProvider",
    "WebsiteEnricher",
    "WebsiteProfile",
    "canonical_public_url",
    "normalize_domain",
]
