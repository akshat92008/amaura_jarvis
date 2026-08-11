"""Governed, lazy OSS capability execution for Amaura Company OS.

The capability runtime deliberately keeps heavyweight open-source projects out of
Amaura's core process until a task actually needs them. Every adapter has a
closed operation contract, workspace boundaries, timeouts, memory reservations,
and deterministic health reporting. Missing optional dependencies fail closed
with actionable setup guidance instead of breaking the control plane.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib
import importlib.util
import importlib.metadata
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from jarvis.amaura.browser_egress import BrowserEgressProxy
from jarvis.amaura.mcp_registry import load_server
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_bytes, request_json, validate_public_url
from jarvis.amaura.resource_control import (
    CrossProcessResourceLedger,
    MemoryPolicy,
    child_hard_limit_mb,
    process_tree_rss_mb,
    sample_host_memory,
    terminate_process_tree,
)
from jarvis.tools.security import resolve_workspace_path, workspace_root


class CapabilityUnavailable(GovernanceError):
    """Raised when an optional OSS capability is not installed/configured."""


class CapabilityExecutionError(GovernanceError):
    """Raised when a capability ran but did not produce a trustworthy result."""


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    key: str
    name: str
    category: str
    operations: tuple[str, ...]
    ram_mb: int
    heavy: bool = False
    networked: bool = False
    side_effects: bool = False
    always_on: bool = False
    install_hint: str = ""
    licence: str = ""


@dataclass(slots=True)
class CapabilityResult:
    capability: str
    operation: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    provider: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityAdapter(Protocol):
    descriptor: CapabilityDescriptor

    def available(self) -> tuple[bool, str]: ...
    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult: ...


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _bounded_text(value: Any, limit: int = 200_000) -> str:
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


_RESOURCE_CONTEXT = threading.local()


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    env: dict[str, str] | None = None,
    max_rss_mb: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a child process while enforcing the current capability RSS policy.

    The process is launched as its own session on POSIX so a runaway renderer/model
    can be terminated together with descendants. RSS includes the full child tree.
    """
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise CapabilityExecutionError("Capability subprocess requires a non-empty argv vector")
    timeout = max(1, min(int(timeout), 3600))
    policy = MemoryPolicy.from_env()
    inherited_limit = getattr(_RESOURCE_CONTEXT, "child_hard_limit_mb", None)
    hard_limit = int(max_rss_mb or inherited_limit or policy.absolute_limit_mb)
    hard_limit = max(256, min(hard_limit, policy.absolute_limit_mb))
    heavy = bool(getattr(_RESOURCE_CONTEXT, "heavy", False))
    started = time.monotonic()
    start_host = sample_host_memory(policy)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **popen_kwargs)
    except OSError as exc:
        raise CapabilityExecutionError(f"Capability could not start: {exc}") from exc

    last_host = start_host
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                terminate_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=2)
                raise CapabilityExecutionError(f"Capability timed out after {timeout}s")

            rss_mb = process_tree_rss_mb(proc.pid)
            if rss_mb > hard_limit:
                terminate_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=2)
                raise CapabilityExecutionError(
                    f"Capability process tree exceeded its {hard_limit} MB RSS ceiling (observed {rss_mb} MB)"
                )

            if heavy:
                last_host = sample_host_memory(policy)
                swap_growth = max(0, last_host.swap_used_mb - start_host.swap_used_mb)
                if swap_growth >= policy.swap_growth_abort_mb:
                    terminate_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        proc.wait(timeout=2)
                    raise CapabilityExecutionError(
                        f"Capability stopped because swap grew by {swap_growth} MB under {last_host.pressure} memory pressure"
                    )
                if last_host.pressure == "red":
                    terminate_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        proc.wait(timeout=2)
                    raise CapabilityExecutionError(
                        "Capability stopped because macOS/host memory pressure became red"
                    )

            try:
                stdout, stderr = proc.communicate(timeout=0.25)
                return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            terminate_process_tree(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)
        # Explicitly close pipe handles on every exceptional path. The release
        # verifier treats ResourceWarning as an error, and relying on Popen's
        # destructor would leave these descriptors pending until GC.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()


def _safe_local_input(raw: str) -> Path:
    return resolve_workspace_path(raw, must_exist=True)


def _safe_local_output(raw: str) -> Path:
    path = resolve_workspace_path(raw, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _safe_public_url(raw: str) -> str:
    return validate_public_url(raw, resolve=True).url


def _run_async(factory: Callable[[], Any]) -> Any:
    """Run an async capability from sync tool code, even if a host loop exists."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list[Any] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as exc:  # propagated to the caller below
            error.append(exc)

    thread = threading.Thread(target=_runner, name="amaura-capability-async", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "json") and not callable(getattr(value, "json")):
        return _jsonable(getattr(value, "json"))
    return _bounded_text(value, 50_000)


class _BaseAdapter:
    descriptor: CapabilityDescriptor

    def _check_operation(self, operation: str) -> None:
        if operation not in self.descriptor.operations:
            raise GovernanceError(
                f"Unsupported {self.descriptor.key} operation '{operation}'. "
                f"Allowed: {', '.join(self.descriptor.operations)}"
            )

    def _result(
        self,
        operation: str,
        *,
        started: float,
        output: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        provider: str = "",
    ) -> CapabilityResult:
        return CapabilityResult(
            capability=self.descriptor.key,
            operation=operation,
            ok=True,
            output=output or {},
            artifacts=artifacts or [],
            duration_ms=int((time.monotonic() - started) * 1000),
            provider=provider or self.descriptor.name,
        )


class PlaywrightAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="playwright",
        name="Playwright",
        category="browser",
        operations=("extract", "screenshot"),
        ram_mb=650,
        heavy=True,
        networked=True,
        install_hint="pip install playwright && playwright install chromium",
        licence="Apache-2.0",
    )

    def available(self) -> tuple[bool, str]:
        if not _module_available("playwright"):
            return False, "Python package 'playwright' is not installed"
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            with sync_playwright() as p:
                executable = Path(p.chromium.executable_path)
                if not executable.is_file():
                    return False, "Playwright is installed but Chromium is missing; run: playwright install chromium"
        except Exception as exc:
            return False, f"Playwright Chromium readiness check failed: {_bounded_text(exc, 500)}"
        return True, "installed; Chromium executable present"

    @staticmethod
    def _route_guard(route) -> None:  # noqa: ANN001
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.scheme in {"data", "blob"}:
            route.continue_()
            return
        if parsed.scheme not in {"http", "https"}:
            route.abort("blockedbyclient")
            return
        try:
            validate_public_url(request.url, resolve=True)
        except GovernanceError:
            route.abort("blockedbyclient")
            return
        if getattr(request, "resource_type", "") == "websocket":
            route.abort("blockedbyclient")
            return
        route.continue_()

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        url = _safe_public_url(str(params.get("url", "")))
        if urlsplit(url).scheme != "https":
            raise GovernanceError("Browser execution is HTTPS-only in the hardened profile")
        timeout_ms = max(1_000, min(int(params.get("timeout_ms", 30_000)), 60_000))
        max_response_mb = max(1, min(int(os.environ.get("AMAURA_BROWSER_MAX_RESPONSE_MB", "20")), 100))
        started = time.monotonic()
        from playwright.sync_api import sync_playwright  # type: ignore

        with BrowserEgressProxy.start() as egress, sync_playwright() as p:
            browser = p.chromium.launch(headless=True, proxy={"server": egress.url})
            try:
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    ignore_https_errors=False,
                )
                context.route("**/*", self._route_guard)
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                final_url = str(page.url)
                validate_public_url(final_url, resolve=True)
                if urlsplit(final_url).scheme != "https":
                    raise GovernanceError("Browser final navigation left HTTPS")
                if response is not None:
                    header = response.headers.get("content-length", "").strip()
                    if header.isdigit() and int(header) > max_response_mb * 1024 * 1024:
                        raise CapabilityExecutionError(
                            f"Browser document exceeds {max_response_mb} MB response-size limit"
                        )
                if operation == "extract":
                    selector = str(params.get("selector", "body") or "body")
                    text = page.locator(selector).inner_text(timeout=timeout_ms)
                    title = page.title()
                    return self._result(
                        operation, started=started,
                        output={"url": final_url, "title": title, "text": _bounded_text(text)},
                    )
                output_path = _safe_local_output(str(params.get("output_path", "playwright-screenshot.png")))
                page.screenshot(path=str(output_path), full_page=bool(params.get("full_page", True)))
                return self._result(
                    operation, started=started,
                    output={"url": final_url, "title": page.title(), "path": str(output_path)},
                    artifacts=[_artifact(output_path)],
                )
            finally:
                browser.close()


class Crawl4AIAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="crawl4ai",
        name="Crawl4AI",
        category="research",
        operations=("crawl",),
        ram_mb=850,
        heavy=True,
        networked=True,
        install_hint="pip install crawl4ai && crawl4ai-setup",
        licence="Apache-2.0",
    )

    def available(self) -> tuple[bool, str]:
        if not _module_available("crawl4ai"):
            return False, "Python package 'crawl4ai' is not installed"
        if not _module_available("playwright"):
            return False, "Crawl4AI browser backend needs Playwright"
        return True, "installed; secure proxy compatibility is checked at execution"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        url = _safe_public_url(str(params.get("url", "")))
        if urlsplit(url).scheme != "https":
            raise GovernanceError("Crawl4AI execution is HTTPS-only in the hardened profile")
        started = time.monotonic()

        async def _crawl() -> dict[str, Any]:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig  # type: ignore

            with BrowserEgressProxy.start() as egress:
                parameters = inspect.signature(BrowserConfig).parameters
                if "proxy" not in parameters:
                    raise CapabilityUnavailable(
                        "Installed Crawl4AI does not expose BrowserConfig(proxy=...); refusing insecure browser execution"
                    )
                browser_config = BrowserConfig(headless=True, proxy=egress.url)
                run_config = CrawlerRunConfig()
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    success = bool(getattr(result, "success", True))
                    if not success:
                        raise CapabilityExecutionError(_bounded_text(getattr(result, "error_message", "Crawl failed"), 5_000))
                    final_url = str(getattr(result, "url", url))
                    validate_public_url(final_url, resolve=True)
                    if urlsplit(final_url).scheme != "https":
                        raise GovernanceError("Crawl4AI final navigation left HTTPS")
                    markdown = getattr(result, "markdown", "")
                    if hasattr(markdown, "raw_markdown"):
                        markdown = markdown.raw_markdown
                    return {
                        "url": final_url,
                        "markdown": _bounded_text(markdown),
                        "html": _bounded_text(getattr(result, "cleaned_html", ""), 100_000),
                        "links": _jsonable(getattr(result, "links", {})),
                        "metadata": _jsonable(getattr(result, "metadata", {})),
                    }

        output = _run_async(_crawl)
        return self._result(operation, started=started, output=output)


class BrowserUseAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="browser_use",
        name="Browser Use",
        category="browser_agent",
        operations=("research",),
        ram_mb=1400,
        heavy=True,
        networked=True,
        install_hint="pip install browser-use && playwright install chromium",
        licence="MIT",
    )

    _READ_ONLY_EXCLUDES = [
        "click", "input", "upload_file", "send_keys", "evaluate",
        "switch", "close", "dropdown_options", "select_dropdown",
        "write_file", "read_file", "replace_file",
    ]

    def available(self) -> tuple[bool, str]:
        enabled = os.environ.get("AMAURA_BROWSER_USE_AGENT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return False, "Agentic browser research is disabled by default; set AMAURA_BROWSER_USE_AGENT_ENABLED=1 to opt in"
        if not _module_available("browser_use"):
            return False, "Python package 'browser-use' is not installed"
        try:
            browser_use = importlib.import_module("browser_use")
        except Exception as exc:
            return False, f"Browser Use import failed: {_bounded_text(exc, 500)}"
        required = ("Agent", "Tools", "BrowserProfile", "BrowserSession", "ProxySettings")
        missing = [name for name in required if not hasattr(browser_use, name)]
        if missing:
            return False, f"Installed Browser Use lacks hardened APIs: {', '.join(missing)}"
        free_cloud = any(os.environ.get(key) for key in ("GOOGLE_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY"))
        paid_allowed = os.environ.get("AMAURA_BROWSER_USE_ALLOW_PAID", "0").strip().lower() in {"1", "true", "yes", "on"}
        paid_route = paid_allowed and bool(os.environ.get("OPENROUTER_API_KEY"))
        if not free_cloud and not shutil.which("ollama") and not paid_route:
            return False, "Browser Use needs a configured free cloud route, local Ollama fallback, or explicitly approved paid route"
        return True, "installed; hardened read-only APIs and model route available"

    @staticmethod
    def _llm():
        browser_use = importlib.import_module("browser_use")
        # Prefer remote/free inference on an 8 GB Mac. Local Ollama is an offline/fallback
        # route so browser + local LLM are not selected together unnecessarily.
        if os.environ.get("GROQ_API_KEY") and hasattr(browser_use, "ChatGroq"):
            return browser_use.ChatGroq(model=os.environ.get("AMAURA_BROWSER_USE_MODEL", "meta-llama/llama-4-maverick-17b-128e-instruct"))
        if os.environ.get("CEREBRAS_API_KEY") and hasattr(browser_use, "ChatCerebras"):
            return browser_use.ChatCerebras(model=os.environ.get("AMAURA_BROWSER_USE_MODEL", "llama3.3-70b"))
        if os.environ.get("GOOGLE_API_KEY") and hasattr(browser_use, "ChatGoogle"):
            return browser_use.ChatGoogle(model=os.environ.get("AMAURA_BROWSER_USE_MODEL", "gemini-2.5-flash"))
        if shutil.which("ollama") and hasattr(browser_use, "ChatOllama"):
            return browser_use.ChatOllama(model=os.environ.get("AMAURA_BROWSER_USE_MODEL", "qwen2.5:3b"), num_ctx=8192)
        paid_allowed = os.environ.get("AMAURA_BROWSER_USE_ALLOW_PAID", "0").strip().lower() in {"1", "true", "yes", "on"}
        if paid_allowed and os.environ.get("OPENROUTER_API_KEY") and hasattr(browser_use, "ChatOpenRouter"):
            return browser_use.ChatOpenRouter(model=os.environ.get("AMAURA_BROWSER_USE_MODEL", "google/gemini-2.5-flash"))
        raise CapabilityUnavailable("No supported Browser Use model route is configured")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        task = str(params.get("task", "")).strip()
        if not task:
            raise GovernanceError("Browser Use research requires a task")
        domains = [str(v).strip() for v in params.get("allowed_domains", []) if str(v).strip()]
        if not domains:
            raise GovernanceError("Browser Use research requires an explicit allowed_domains list")
        for domain in domains:
            candidate = domain[2:] if domain.startswith("*.") else domain
            candidate = candidate.removeprefix("https://").split("/", 1)[0]
            _safe_public_url(f"https://{candidate}")
        max_steps = max(1, min(int(params.get("max_steps", 12)), 30))
        started = time.monotonic()

        async def _run_agent() -> dict[str, Any]:
            browser_use = importlib.import_module("browser_use")
            Agent = getattr(browser_use, "Agent", None)
            Tools = getattr(browser_use, "Tools", None)
            BrowserProfile = getattr(browser_use, "BrowserProfile", None)
            BrowserSession = getattr(browser_use, "BrowserSession", None)
            ProxySettings = getattr(browser_use, "ProxySettings", None)
            if None in {Agent, Tools, BrowserProfile, BrowserSession, ProxySettings}:
                raise CapabilityUnavailable("Installed Browser Use is missing hardened security APIs")
            with BrowserEgressProxy.start() as egress:
                tools = Tools(exclude_actions=list(self._READ_ONLY_EXCLUDES))
                profile = BrowserProfile(
                    headless=True,
                    allowed_domains=domains,
                    block_ip_addresses=True,
                    accept_downloads=False,
                    auto_download_pdfs=False,
                    permissions=[],
                    cross_origin_iframes=False,
                    user_data_dir=None,
                    proxy=ProxySettings(server=egress.url),
                )
                session = BrowserSession(browser_profile=profile)
                kwargs: dict[str, Any] = {
                    "task": task,
                    "llm": self._llm(),
                    "tools": tools,
                    "browser_session": session,
                    "use_vision": bool(params.get("use_vision", False)),
                    "max_failures": 2,
                    "validate_output": True,
                    "max_actions_per_step": 1,
                    "extend_system_message": (
                        "READ-ONLY RESEARCH MODE. Only search, navigate, go back, wait, scroll, find text, "
                        "extract content, request screenshots, and finish. Interaction, typing, JavaScript, file "
                        "operations, form controls, uploads, downloads, and state-changing actions are unavailable."
                    ),
                }
                agent = Agent(**kwargs)
                history = await agent.run(max_steps=max_steps)
                final_result = history.final_result() if hasattr(history, "final_result") else str(history)
                successful = history.is_successful() if hasattr(history, "is_successful") else True
                return {
                    "result": _bounded_text(final_result),
                    "successful": bool(successful),
                    "allowed_domains": domains,
                    "read_only_actions": ["search", "navigate", "go_back", "wait", "scroll", "find_text", "extract", "screenshot", "done"],
                }

        output = _run_async(_run_agent)
        if not output["successful"]:
            raise CapabilityExecutionError("Browser Use did not complete the research task successfully")
        return self._result(operation, started=started, output=output)


class SearXNGAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="searxng",
        name="SearXNG",
        category="search",
        operations=("search",),
        ram_mb=250,
        networked=True,
        install_hint="Run a SearXNG instance and set SEARXNG_URL",
        licence="AGPL-3.0-or-later",
    )

    def available(self) -> tuple[bool, str]:
        return (bool(os.environ.get("SEARXNG_URL", "").strip()), "configured" if os.environ.get("SEARXNG_URL", "").strip() else "SEARXNG_URL is not configured")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        query = str(params.get("query", "")).strip()
        if not query:
            raise GovernanceError("SearXNG search requires query")
        limit = max(1, min(int(params.get("limit", 10)), 25))
        base = os.environ["SEARXNG_URL"].rstrip("/") + "/"
        endpoint = urljoin(base, "search")
        # The endpoint itself is founder-controlled configuration. Public endpoints are
        # validated; localhost/private endpoints are allowed only when explicitly set.
        host = (urlsplit(endpoint).hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            _safe_public_url(endpoint)
        started = time.monotonic()
        try:
            response = httpx.get(
                endpoint,
                params={
                    "q": query,
                    "format": "json",
                    "language": str(params.get("language", "auto")),
                    "safesearch": int(params.get("safesearch", 1)),
                },
                timeout=20,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CapabilityExecutionError(f"SearXNG request failed: {exc}") from exc
        results = []
        for item in payload.get("results", [])[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            with contextlib.suppress(Exception):
                _safe_public_url(url)
                results.append({
                    "title": str(item.get("title", "")),
                    "url": url,
                    "content": _bounded_text(item.get("content", ""), 8_000),
                    "engine": str(item.get("engine", "")),
                    "score": item.get("score"),
                })
        return self._result(operation, started=started, output={"query": query, "results": results, "count": len(results)})


class DoclingAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="docling",
        name="Docling",
        category="documents",
        operations=("convert",),
        ram_mb=1800,
        heavy=True,
        install_hint="pip install docling",
        licence="MIT",
    )

    def available(self) -> tuple[bool, str]:
        return (_module_available("docling"), "installed" if _module_available("docling") else "Python package 'docling' is not installed")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        source = _safe_local_input(str(params.get("source_path", "")))
        max_pages = max(1, min(int(params.get("max_pages", 200)), 500))
        max_file_size = max(1_000_000, min(int(params.get("max_file_size", 50_000_000)), 200_000_000))
        if source.stat().st_size > max_file_size:
            raise GovernanceError("Document exceeds configured file-size limit")
        started = time.monotonic()
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        result = converter.convert(str(source), max_num_pages=max_pages, max_file_size=max_file_size)
        markdown = result.document.export_to_markdown()
        output_path_raw = str(params.get("output_path", "")).strip()
        artifacts: list[dict[str, Any]] = []
        output: dict[str, Any] = {"source_path": str(source), "markdown": _bounded_text(markdown)}
        if output_path_raw:
            output_path = _safe_local_output(output_path_raw)
            output_path.write_text(markdown, encoding="utf-8")
            output["output_path"] = str(output_path)
            artifacts.append(_artifact(output_path))
        return self._result(operation, started=started, output=output, artifacts=artifacts)


class PyMuPDFAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="pymupdf",
        name="PyMuPDF",
        category="documents",
        operations=("extract_text", "render_page"),
        ram_mb=300,
        install_hint="pip install PyMuPDF",
        licence="AGPL-3.0/commercial dual licence",
    )

    def available(self) -> tuple[bool, str]:
        return (_module_available("fitz"), "installed" if _module_available("fitz") else "Python package 'PyMuPDF' is not installed")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        source = _safe_local_input(str(params.get("source_path", "")))
        started = time.monotonic()
        import fitz  # type: ignore

        doc = fitz.open(str(source))
        try:
            if operation == "extract_text":
                max_pages = max(1, min(int(params.get("max_pages", 100)), 500))
                pages = [doc[i].get_text("text") for i in range(min(len(doc), max_pages))]
                return self._result(operation, started=started, output={"text": _bounded_text("\n".join(pages)), "pages": min(len(doc), max_pages)})
            page_index = int(params.get("page", 0))
            if page_index < 0 or page_index >= len(doc):
                raise GovernanceError("PDF page index is out of range")
            output_path = _safe_local_output(str(params.get("output_path", f"page-{page_index + 1}.png")))
            scale = max(0.5, min(float(params.get("scale", 1.5)), 4.0))
            pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pix.save(str(output_path))
            return self._result(operation, started=started, output={"output_path": str(output_path), "page": page_index}, artifacts=[_artifact(output_path)])
        finally:
            doc.close()


class PaddleOCRAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="paddleocr",
        name="PaddleOCR",
        category="ocr",
        operations=("ocr",),
        ram_mb=1700,
        heavy=True,
        install_hint="Install PaddlePaddle for your platform, then pip install paddleocr",
        licence="Apache-2.0",
    )

    def available(self) -> tuple[bool, str]:
        return (_module_available("paddleocr"), "installed" if _module_available("paddleocr") else "Python package 'paddleocr' is not installed")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        source = _safe_local_input(str(params.get("source_path", "")))
        started = time.monotonic()
        from paddleocr import PaddleOCR  # type: ignore

        kwargs: dict[str, Any] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "device": str(params.get("device", "cpu")),
            "cpu_threads": max(1, min(int(params.get("cpu_threads", 4)), 8)),
        }
        if params.get("lang"):
            kwargs["lang"] = str(params["lang"])
        if params.get("ocr_version"):
            kwargs["ocr_version"] = str(params["ocr_version"])
        pipeline = PaddleOCR(**kwargs)
        results = list(pipeline.predict(str(source)))
        serialized = [_jsonable(item) for item in results]
        output_path_raw = str(params.get("output_path", "")).strip()
        artifacts: list[dict[str, Any]] = []
        if output_path_raw:
            output_path = _safe_local_output(output_path_raw)
            output_path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            artifacts.append(_artifact(output_path))
        return self._result(operation, started=started, output={"results": serialized, "count": len(serialized)}, artifacts=artifacts)


class FastEmbedQdrantAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="qdrant_fastembed",
        name="Qdrant + FastEmbed",
        category="memory",
        operations=("upsert", "query"),
        ram_mb=650,
        networked=False,
        install_hint="pip install 'qdrant-client[fastembed]'",
        licence="Apache-2.0 / FastEmbed Apache-2.0",
    )

    def available(self) -> tuple[bool, str]:
        ok = _module_available("qdrant_client") and _module_available("fastembed")
        return ok, "installed" if ok else "Install qdrant-client[fastembed]"

    @staticmethod
    def _client():
        from qdrant_client import QdrantClient  # type: ignore

        url = os.environ.get("QDRANT_URL", "").strip()
        api_key = os.environ.get("QDRANT_API_KEY", "").strip() or None
        if url:
            host = (urlsplit(url).hostname or "").lower()
            if host not in {"localhost", "127.0.0.1", "::1"}:
                _safe_public_url(url)
            return QdrantClient(url=url, api_key=api_key)
        path = resolve_workspace_path(os.environ.get("AMAURA_QDRANT_PATH", ".amaura-qdrant"), must_exist=False)
        path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(path))

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        collection = str(params.get("collection", "amaura_company_memory")).strip()
        if not collection or len(collection) > 128:
            raise GovernanceError("Invalid Qdrant collection name")
        started = time.monotonic()
        client = self._client()
        if operation == "upsert":
            documents = [str(v) for v in params.get("documents", []) if str(v).strip()]
            if not documents or len(documents) > 200:
                raise GovernanceError("Qdrant upsert requires 1-200 non-empty documents")
            metadata = params.get("metadata") or [{} for _ in documents]
            if not isinstance(metadata, list) or len(metadata) != len(documents):
                raise GovernanceError("metadata must be a list aligned with documents")
            ids = params.get("ids") or [str(uuid.uuid4()) for _ in documents]
            if len(ids) != len(documents):
                raise GovernanceError("ids must align with documents")
            client.add(collection_name=collection, documents=documents, metadata=metadata, ids=ids)
            return self._result(operation, started=started, output={"collection": collection, "count": len(documents), "ids": [str(v) for v in ids]})
        query = str(params.get("query", "")).strip()
        if not query:
            raise GovernanceError("Qdrant query requires text")
        limit = max(1, min(int(params.get("limit", 8)), 25))
        hits = client.query(collection_name=collection, query_text=query, limit=limit)
        return self._result(operation, started=started, output={"collection": collection, "query": query, "results": _jsonable(hits)})


class LlamaIndexAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="llamaindex",
        name="LlamaIndex Core",
        category="rag",
        operations=("chunk",),
        ram_mb=350,
        install_hint="pip install llama-index-core",
        licence="MIT",
    )

    def available(self) -> tuple[bool, str]:
        ok = _module_available("llama_index.core")
        return ok, "installed" if ok else "Python package 'llama-index-core' is not installed"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        text = str(params.get("text", ""))
        if not text.strip():
            raise GovernanceError("LlamaIndex chunk requires text")
        chunk_size = max(128, min(int(params.get("chunk_size", 768)), 4096))
        overlap = max(0, min(int(params.get("chunk_overlap", 80)), chunk_size // 2))
        started = time.monotonic()
        from llama_index.core import Document  # type: ignore
        from llama_index.core.node_parser import SentenceSplitter  # type: ignore

        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
        nodes = splitter.get_nodes_from_documents([Document(text=text)])
        chunks = [node.get_content() for node in nodes]
        return self._result(operation, started=started, output={"chunks": chunks, "count": len(chunks)})


class FasterWhisperAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="faster_whisper",
        name="faster-whisper",
        category="speech_to_text",
        operations=("transcribe",),
        ram_mb=1600,
        heavy=True,
        install_hint="pip install faster-whisper",
        licence="MIT",
    )

    def available(self) -> tuple[bool, str]:
        return (_module_available("faster_whisper"), "installed" if _module_available("faster_whisper") else "Python package 'faster-whisper' is not installed")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        source = _safe_local_input(str(params.get("source_path", "")))
        model_name = str(params.get("model", os.environ.get("AMAURA_WHISPER_MODEL", "small")))
        started = time.monotonic()
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(
            model_name,
            device=str(params.get("device", "cpu")),
            compute_type=str(params.get("compute_type", "int8")),
            cpu_threads=max(1, min(int(params.get("cpu_threads", 4)), 8)),
            num_workers=1,
        )
        segments_gen, info = model.transcribe(
            str(source),
            beam_size=max(1, min(int(params.get("beam_size", 3)), 5)),
            vad_filter=bool(params.get("vad_filter", True)),
            word_timestamps=bool(params.get("word_timestamps", False)),
            language=str(params.get("language", "")) or None,
        )
        segments = list(segments_gen)
        output_segments = [
            {"start": float(s.start), "end": float(s.end), "text": str(s.text).strip()}
            for s in segments
        ]
        text = " ".join(item["text"] for item in output_segments).strip()
        return self._result(
            operation,
            started=started,
            output={
                "text": text,
                "segments": output_segments,
                "language": str(getattr(info, "language", "")),
                "language_probability": float(getattr(info, "language_probability", 0.0)),
            },
        )


class KokoroAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="kokoro",
        name="Kokoro TTS",
        category="text_to_speech",
        operations=("synthesize",),
        ram_mb=900,
        heavy=True,
        install_hint="pip install kokoro soundfile; install espeak-ng for fallback phonemization",
        licence="Apache-2.0 weights/library",
    )

    def available(self) -> tuple[bool, str]:
        ok = _module_available("kokoro") and _module_available("soundfile")
        return ok, "installed" if ok else "Install kokoro and soundfile"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        text = str(params.get("text", "")).strip()
        if not text or len(text) > 30_000:
            raise GovernanceError("Kokoro text must contain 1-30000 characters")
        output_path = _safe_local_output(str(params.get("output_path", "amaura-voice.wav")))
        started = time.monotonic()
        import numpy as np
        import soundfile as sf  # type: ignore
        from kokoro import KPipeline  # type: ignore

        pipeline = KPipeline(lang_code=str(params.get("lang_code", "a")))
        generator = pipeline(text, voice=str(params.get("voice", "af_heart")), speed=float(params.get("speed", 1.0)))
        chunks = [np.asarray(audio, dtype=np.float32) for _, _, audio in generator]
        if not chunks:
            raise CapabilityExecutionError("Kokoro produced no audio")
        audio = np.concatenate(chunks)
        sf.write(str(output_path), audio, 24000)
        return self._result(operation, started=started, output={"output_path": str(output_path), "sample_rate": 24000}, artifacts=[_artifact(output_path)])


class FFmpegAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="ffmpeg",
        name="FFmpeg",
        category="media",
        operations=("probe", "transcode", "burn_subtitles", "concat", "mux_audio"),
        ram_mb=650,
        install_hint="brew install ffmpeg",
        licence="LGPL/GPL depending on build",
    )

    def available(self) -> tuple[bool, str]:
        ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        return ok, "installed" if ok else "ffmpeg/ffprobe executables are not installed"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        started = time.monotonic()
        if operation == "probe":
            source = _safe_local_input(str(params.get("source_path", "")))
            proc = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)], timeout=60)
            if proc.returncode != 0:
                raise CapabilityExecutionError(_bounded_text(proc.stderr, 8_000))
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise CapabilityExecutionError("ffprobe returned invalid JSON") from exc
            return self._result(operation, started=started, output=payload)
        if operation == "transcode":
            source = _safe_local_input(str(params.get("source_path", "")))
            output = _safe_local_output(str(params.get("output_path", "output.mp4")))
            argv = ["ffmpeg", "-y", "-nostdin", "-i", str(source)]
            if params.get("video_codec"):
                argv += ["-c:v", str(params["video_codec"])]
            if params.get("audio_codec"):
                argv += ["-c:a", str(params["audio_codec"])]
            if params.get("width") or params.get("height"):
                width = int(params.get("width", -2))
                height = int(params.get("height", -2))
                if width != -2 and not 64 <= width <= 7680:
                    raise GovernanceError("Invalid output width")
                if height != -2 and not 64 <= height <= 4320:
                    raise GovernanceError("Invalid output height")
                argv += ["-vf", f"scale={width}:{height}"]
            argv.append(str(output))
        elif operation == "burn_subtitles":
            source = _safe_local_input(str(params.get("source_path", "")))
            subtitles = _safe_local_input(str(params.get("subtitle_path", "")))
            output = _safe_local_output(str(params.get("output_path", "subtitled.mp4")))
            # Path is controlled by workspace validation; quote characters are escaped for ffmpeg filter parser.
            escaped = str(subtitles).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            argv = ["ffmpeg", "-y", "-nostdin", "-i", str(source), "-vf", f"subtitles='{escaped}'", str(output)]
        elif operation == "concat":
            sources = [_safe_local_input(str(v)) for v in params.get("source_paths", [])]
            if not 1 <= len(sources) <= 100:
                raise GovernanceError("FFmpeg concat requires 1-100 source paths")
            output = _safe_local_output(str(params.get("output_path", "concatenated.mp4")))
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=str(workspace_root()), encoding="utf-8") as handle:
                concat_file = Path(handle.name)
                for source in sources:
                    safe = str(source).replace("'", "'\\''")
                    handle.write(f"file '{safe}'\n")
            try:
                argv = ["ffmpeg", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output)]
                proc = _run(argv, timeout=int(params.get("timeout", 900)))
            finally:
                concat_file.unlink(missing_ok=True)
            if proc.returncode != 0:
                raise CapabilityExecutionError(_bounded_text(proc.stderr, 12_000))
            return self._result(operation, started=started, output={"output_path": str(output)}, artifacts=[_artifact(output)])
        else:
            source = _safe_local_input(str(params.get("source_path", "")))
            audio = _safe_local_input(str(params.get("audio_path", "")))
            output = _safe_local_output(str(params.get("output_path", "muxed.mp4")))
            argv = [
                "ffmpeg", "-y", "-nostdin", "-i", str(source), "-i", str(audio),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", str(params.get("audio_codec", "aac")), "-shortest", str(output),
            ]
        proc = _run(argv, timeout=int(params.get("timeout", 900)))
        if proc.returncode != 0:
            raise CapabilityExecutionError(_bounded_text(proc.stderr, 12_000))
        return self._result(operation, started=started, output={"output_path": str(output)}, artifacts=[_artifact(output)])


class RemotionAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="remotion",
        name="Remotion",
        category="video_render",
        operations=("bootstrap_project", "lock_project", "render"),
        ram_mb=1800,
        heavy=True,
        install_hint="Bootstrap the Amaura template, lock dependencies, run npm ci --ignore-scripts, then render",
        licence="Free for individuals and eligible small teams; review Remotion licence as the company grows",
    )

    def available(self) -> tuple[bool, str]:
        ok = bool(shutil.which("node") and shutil.which("npm"))
        return ok, "Node.js and npm are available" if ok else "Node.js plus npm is required"

    @staticmethod
    def _template_files(version: str) -> dict[str, str]:
        package = {
            "name": "amaura-remotion-template",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "studio": "remotion studio src/index.tsx",
                "render:reel": "remotion render src/index.tsx AmauraReel30 out/reel.mp4",
                "render:short": "remotion render src/index.tsx AmauraShort60 out/short.mp4",
                "render:landscape": "remotion render src/index.tsx AmauraLandscape60 out/landscape.mp4",
            },
            "dependencies": {
                "@remotion/cli": version,
                "react": "19.0.0",
                "react-dom": "19.0.0",
                "remotion": version,
            },
            "devDependencies": {"typescript": "5.7.3"},
        }
        return {
            "package.json": json.dumps(package, indent=2) + "\n",
            "tsconfig.json": json.dumps({
                "compilerOptions": {
                    "target": "ES2022", "lib": ["DOM", "ES2022"], "jsx": "react-jsx",
                    "module": "ESNext", "moduleResolution": "Bundler", "strict": True,
                    "skipLibCheck": True, "noEmit": True,
                },
                "include": ["src"],
            }, indent=2) + "\n",
            "src/index.tsx": """import {registerRoot} from 'remotion';
import {Root} from './Root';
registerRoot(Root);
""",
            "src/Root.tsx": """import React from 'react';
import {Composition} from 'remotion';
import {AmauraVideo, defaultVideoProps} from './AmauraVideo';

export const Root: React.FC = () => (
  <>
    <Composition id="AmauraReel30" component={AmauraVideo} durationInFrames={900} fps={30} width={1080} height={1920} defaultProps={defaultVideoProps} />
    <Composition id="AmauraShort60" component={AmauraVideo} durationInFrames={1800} fps={30} width={1080} height={1920} defaultProps={defaultVideoProps} />
    <Composition id="AmauraLandscape60" component={AmauraVideo} durationInFrames={1800} fps={30} width={1920} height={1080} defaultProps={defaultVideoProps} />
  </>
);
""",
            "src/AmauraVideo.tsx": """import React from 'react';
import {AbsoluteFill, Img, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

type Scene = {headline?: string; body?: string; imageUrl?: string; background?: string};
type Props = {title: string; subtitle?: string; scenes?: Scene[]};

export const defaultVideoProps: Props = {
  title: 'Amaura',
  subtitle: 'Founder-controlled AI execution',
  scenes: [
    {headline: 'Research', body: 'Discover and understand the opportunity.'},
    {headline: 'Create', body: 'Turn approved ideas into production assets.'},
    {headline: 'Execute', body: 'Ship with governance, evidence, and review.'},
  ],
};

const SceneCard: React.FC<{scene: Scene; index: number}> = ({scene, index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 18, stiffness: 110}});
  const opacity = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{
      background: scene.background || '#0b0d12', color: 'white', justifyContent: 'center',
      alignItems: 'center', padding: '8%', fontFamily: 'Inter, Arial, sans-serif', overflow: 'hidden',
    }}>
      {scene.imageUrl ? <Img src={scene.imageUrl} style={{position: 'absolute', width: '100%', height: '100%', objectFit: 'cover', opacity: 0.28}} /> : null}
      <div style={{position: 'relative', width: '100%', transform: `translateY(${(1-enter)*70}px) scale(${0.96+enter*0.04})`, opacity}}>
        <div style={{fontSize: 26, opacity: 0.55, marginBottom: 18}}>0{index + 1}</div>
        <div style={{fontSize: 78, fontWeight: 750, lineHeight: 1.03, letterSpacing: -2}}>{scene.headline || 'Amaura'}</div>
        {scene.body ? <div style={{fontSize: 34, lineHeight: 1.35, opacity: 0.78, marginTop: 28, maxWidth: 1000}}>{scene.body}</div> : null}
      </div>
    </AbsoluteFill>
  );
};

export const AmauraVideo: React.FC<Props> = ({title, subtitle, scenes = []}) => {
  const {durationInFrames} = useVideoConfig();
  const normalized = scenes.length ? scenes : [{headline: title, body: subtitle}];
  const perScene = Math.max(1, Math.floor(durationInFrames / normalized.length));
  return (
    <AbsoluteFill style={{background: '#0b0d12'}}>
      {normalized.map((scene, index) => (
        <Sequence key={`${index}-${scene.headline || ''}`} from={index * perScene} durationInFrames={index === normalized.length - 1 ? durationInFrames - index * perScene : perScene}>
          <SceneCard scene={scene} index={index} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
""",
        }

    _TEMPLATE_ID = "amaura-remotion-v1"
    _COMPOSITIONS = {"AmauraReel30", "AmauraShort60", "AmauraLandscape60"}

    @classmethod
    def _manifest_payload(cls, project: Path, version: str, package_lock_sha256: str = "") -> dict[str, Any]:
        files = cls._template_files(version)
        hashes = {relative: _sha256(project / relative) for relative in sorted(files)}
        return {
            "template_id": cls._TEMPLATE_ID,
            "remotion_version": version,
            "source_hashes": hashes,
            "package_lock_sha256": package_lock_sha256,
        }

    @classmethod
    def _write_manifest(cls, project: Path, version: str, package_lock_sha256: str = "") -> Path:
        path = project / ".amaura-template.json"
        payload = cls._manifest_payload(project, version, package_lock_sha256)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    @classmethod
    def _verify_project(cls, project: Path, *, require_lock: bool) -> dict[str, Any]:
        manifest_path = project / ".amaura-template.json"
        if not manifest_path.is_file():
            raise GovernanceError("Remotion render requires an Amaura-owned verified template manifest")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GovernanceError("Remotion template manifest is invalid") from exc
        if manifest.get("template_id") != cls._TEMPLATE_ID:
            raise GovernanceError("Remotion template_id is not approved")
        version = str(manifest.get("remotion_version", "")).strip()
        expected = cls._template_files(version)
        stored = manifest.get("source_hashes")
        if not isinstance(stored, dict):
            raise GovernanceError("Remotion source hashes are missing")
        for relative in sorted(expected):
            path = project / relative
            if not path.is_file() or stored.get(relative) != _sha256(path):
                raise GovernanceError(f"Remotion template source changed after approval: {relative}")
        if require_lock:
            lock_path = project / "package-lock.json"
            expected_lock = str(manifest.get("package_lock_sha256", "")).strip()
            if not lock_path.is_file() or len(expected_lock) != 64 or _sha256(lock_path) != expected_lock:
                raise GovernanceError("Remotion package-lock.json is missing or changed; run lock_project again")
            for package_name in ("remotion", "@remotion/cli"):
                package_json = project / "node_modules" / package_name / "package.json"
                if not package_json.is_file():
                    raise CapabilityUnavailable("Remotion node_modules is not installed; run npm ci --ignore-scripts in the verified project")
                try:
                    installed = json.loads(package_json.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise GovernanceError(f"Invalid installed package metadata for {package_name}") from exc
                if str(installed.get("version", "")) != version:
                    raise GovernanceError(f"Installed {package_name} version does not match locked Remotion version {version}")
        return manifest

    @staticmethod
    def _validate_props(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise GovernanceError("Remotion props must be an object")
        allowed = {"title", "subtitle", "scenes"}
        if set(raw) - allowed:
            raise GovernanceError("Remotion props contain unsupported fields")
        output: dict[str, Any] = {}
        for key in ("title", "subtitle"):
            if key in raw:
                value = str(raw[key])
                if len(value) > 500:
                    raise GovernanceError(f"Remotion {key} is too long")
                output[key] = value
        if "scenes" in raw:
            scenes = raw["scenes"]
            if not isinstance(scenes, list) or len(scenes) > 30:
                raise GovernanceError("Remotion scenes must be a list of at most 30 objects")
            clean_scenes = []
            for scene in scenes:
                if not isinstance(scene, dict) or set(scene) - {"headline", "body", "imageUrl", "background"}:
                    raise GovernanceError("Remotion scene has unsupported fields")
                clean: dict[str, str] = {}
                for key, value in scene.items():
                    text = str(value)
                    if len(text) > (5000 if key == "body" else 1000):
                        raise GovernanceError(f"Remotion scene field is too long: {key}")
                    if key == "imageUrl" and text:
                        parsed = urlsplit(text)
                        if parsed.scheme in {"http", "https"}:
                            raise GovernanceError("Remote imageUrl is disabled; render from local/embedded approved assets")
                        if parsed.scheme not in {"", "data"}:
                            raise GovernanceError("Unsupported Remotion imageUrl scheme")
                    clean[key] = text
                clean_scenes.append(clean)
            output["scenes"] = clean_scenes
        return output

    @staticmethod
    def _media_sandbox(argv: list[str]) -> list[str]:
        if sys.platform == "darwin":
            sandbox = shutil.which("sandbox-exec")
            if not sandbox:
                raise CapabilityUnavailable("Strict Remotion rendering requires sandbox-exec on macOS")
            return [sandbox, "-p", "(version 1) (allow default) (deny network*)", *argv]
        bwrap = shutil.which("bwrap")
        if bwrap:
            return [bwrap, "--unshare-net", "--die-with-parent", "--new-session", "--bind", "/", "/", *argv]
        strict = os.environ.get("AMAURA_STRICT_MEDIA_SANDBOX", "1").strip().lower() in {"1", "true", "yes", "on"}
        if strict:
            raise CapabilityUnavailable("Strict Remotion rendering requires bwrap on non-macOS hosts")
        return argv

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        started = time.monotonic()
        project = resolve_workspace_path(str(params.get("project_path", "amaura-remotion")), must_exist=False)
        if operation == "bootstrap_project":
            if project.exists() and any(project.iterdir()) and not bool(params.get("overwrite", False)):
                raise GovernanceError("Remotion project directory is not empty; set overwrite=true only for an Amaura-owned template directory")
            project.mkdir(parents=True, exist_ok=True)
            version = str(params.get("version", os.environ.get("AMAURA_REMOTION_VERSION", "4.0.477"))).strip()
            if not version or not all(part.isdigit() for part in version.split(".")):
                raise GovernanceError("Remotion version must be an exact numeric version such as 4.0.477")
            artifacts: list[dict[str, Any]] = []
            for relative, content in self._template_files(version).items():
                destination = project / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
                artifacts.append(_artifact(destination))
            manifest_path = self._write_manifest(project, version)
            artifacts.append(_artifact(manifest_path))
            return self._result(
                operation, started=started,
                output={
                    "project_path": str(project),
                    "template_id": self._TEMPLATE_ID,
                    "remotion_version": version,
                    "next_command": "amaura_execute_capability remotion/lock_project, then npm ci --ignore-scripts",
                    "compositions": ["AmauraReel30", "AmauraShort60", "AmauraLandscape60"],
                },
                artifacts=artifacts,
            )

        if operation == "lock_project":
            project = resolve_workspace_path(str(params.get("project_path", ".")), must_exist=True)
            manifest = self._verify_project(project, require_lock=False)
            npm = shutil.which("npm")
            if not npm:
                raise CapabilityUnavailable("npm is required to create package-lock.json")
            env = {
                key: value for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
                if (value := os.environ.get(key))
            }
            env["npm_config_ignore_scripts"] = "true"
            proc = _run(
                [npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
                cwd=project, timeout=int(params.get("timeout", 600)), env=env, max_rss_mb=800,
            )
            lock_path = project / "package-lock.json"
            if proc.returncode != 0 or not lock_path.is_file():
                raise CapabilityExecutionError(_bounded_text(proc.stderr or proc.stdout, 16_000))
            manifest_path = self._write_manifest(project, str(manifest["remotion_version"]), _sha256(lock_path))
            return self._result(
                operation, started=started,
                output={
                    "project_path": str(project),
                    "package_lock_sha256": _sha256(lock_path),
                    "install_command": "npm ci --ignore-scripts --no-audit --no-fund",
                },
                artifacts=[_artifact(lock_path), _artifact(manifest_path)],
            )

        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        project = resolve_workspace_path(str(params.get("project_path", ".")), must_exist=True)
        if not project.is_dir():
            raise GovernanceError("Remotion project_path must be a directory")
        self._verify_project(project, require_lock=True)
        composition = str(params.get("composition", "")).strip()
        if composition not in self._COMPOSITIONS:
            raise GovernanceError("Remotion composition is not one of the immutable Amaura compositions")
        output = _safe_local_output(str(params.get("output_path", "remotion-output.mp4")))
        props = self._validate_props(params.get("props", {}))
        local_cli = project / "node_modules" / ".bin" / "remotion"
        if not local_cli.is_file():
            raise CapabilityUnavailable("Verified local Remotion CLI is missing; run npm ci --ignore-scripts")
        argv = [
            str(local_cli), "render", "src/index.tsx", composition, str(output),
            "--props", json.dumps(props, separators=(",", ":")),
        ]
        argv = self._media_sandbox(argv)
        env = {
            key: value for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if (value := os.environ.get(key))
        }
        env["NODE_ENV"] = "production"
        proc = _run(argv, cwd=project, timeout=int(params.get("timeout", 1200)), env=env)
        if proc.returncode != 0 or not output.is_file():
            raise CapabilityExecutionError(_bounded_text(proc.stderr or proc.stdout, 16_000))
        return self._result(operation, started=started, output={"output_path": str(output)}, artifacts=[_artifact(output)])


class ImageTransformAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="image_tools",
        name="ImageMagick/libvips",
        category="image_processing",
        operations=("resize", "thumbnail"),
        ram_mb=300,
        install_hint="brew install imagemagick vips",
        licence="ImageMagick licence / LGPL for libvips",
    )

    def available(self) -> tuple[bool, str]:
        if shutil.which("magick"):
            return True, "ImageMagick available"
        if shutil.which("vipsthumbnail"):
            return True, "libvips available"
        return False, "Neither 'magick' nor 'vipsthumbnail' is installed"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        source = _safe_local_input(str(params.get("source_path", "")))
        output = _safe_local_output(str(params.get("output_path", "image-output.webp")))
        width = max(16, min(int(params.get("width", 1280)), 8192))
        height = max(16, min(int(params.get("height", 720)), 8192))
        started = time.monotonic()
        if shutil.which("magick"):
            geometry = f"{width}x{height}{'^' if operation == 'thumbnail' else ''}"
            argv = ["magick", str(source), "-auto-orient", "-resize", geometry]
            if operation == "thumbnail":
                argv += ["-gravity", "center", "-extent", f"{width}x{height}"]
            argv.append(str(output))
        else:
            size = f"{width}x{height}"
            argv = ["vipsthumbnail", str(source), "--size", size, "--output", str(output)]
            if operation == "thumbnail":
                argv += ["--crop", "attention"]
        proc = _run(argv, timeout=120)
        if proc.returncode != 0 or not output.is_file():
            raise CapabilityExecutionError(_bounded_text(proc.stderr or proc.stdout, 8_000))
        return self._result(operation, started=started, output={"output_path": str(output)}, artifacts=[_artifact(output)])


class YtDlpAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="yt_dlp",
        name="yt-dlp",
        category="media_ingest",
        operations=("metadata", "download"),
        ram_mb=250,
        networked=True,
        side_effects=True,
        install_hint="pip install 'yt-dlp[default]'; FFmpeg is recommended",
        licence="Unlicense; extractor/site terms still apply",
    )

    def available(self) -> tuple[bool, str]:
        ok = bool(shutil.which("yt-dlp") or _module_available("yt_dlp"))
        return ok, "installed" if ok else "yt-dlp is not installed"

    @staticmethod
    def _base_argv() -> list[str]:
        executable = shutil.which("yt-dlp")
        if executable:
            return [executable]
        if _module_available("yt_dlp"):
            return [sys.executable, "-m", "yt_dlp"]
        raise CapabilityUnavailable("yt-dlp is not installed")

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        if operation == "download":
            enabled = os.environ.get("AMAURA_MEDIA_DOWNLOADS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
            if not enabled:
                raise GovernanceError(
                    "Media downloads are disabled. Set AMAURA_MEDIA_DOWNLOADS_ENABLED=1 only for media you are authorised to download."
                )
            if not bool(params.get("rights_confirmed", False)):
                raise GovernanceError("yt-dlp download requires rights_confirmed=true")
        url = _safe_public_url(str(params.get("url", "")))
        started = time.monotonic()
        base = self._base_argv()
        if operation == "metadata":
            proc = _run(
                [*base, "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings", url],
                timeout=max(30, min(int(params.get("timeout", 120)), 600)),
            )
            if proc.returncode != 0:
                raise CapabilityExecutionError(_bounded_text(proc.stderr or proc.stdout, 12_000))
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise CapabilityExecutionError("yt-dlp returned invalid metadata JSON") from exc
            # Avoid storing giant comments/formats/manifests in company memory by default.
            compact = {
                key: payload.get(key)
                for key in (
                    "id", "title", "description", "duration", "timestamp", "upload_date",
                    "uploader", "uploader_id", "channel", "channel_id", "webpage_url",
                    "extractor", "availability", "live_status", "view_count", "like_count",
                    "thumbnail", "ext",
                )
                if key in payload
            }
            return self._result(operation, started=started, output={"metadata": _jsonable(compact)})

        output = _safe_local_output(str(params.get("output_path", "media-download.%(ext)s")))
        max_filesize_mb = max(1, min(int(params.get("max_filesize_mb", 500)), 2_000))
        argv = [
            *base, "--no-playlist", "--no-overwrites", "--no-part",
            "--max-filesize", f"{max_filesize_mb}M", "-o", str(output),
        ]
        mode = str(params.get("mode", "video")).strip().lower()
        if mode == "audio":
            argv += ["-x", "--audio-format", str(params.get("audio_format", "wav"))]
        elif mode != "video":
            raise GovernanceError("yt-dlp download mode must be 'video' or 'audio'")
        argv.append(url)
        proc = _run(argv, timeout=max(60, min(int(params.get("timeout", 900)), 3600)))
        if proc.returncode != 0:
            raise CapabilityExecutionError(_bounded_text(proc.stderr or proc.stdout, 16_000))
        # yt-dlp may replace %(ext)s after post-processing, so resolve the resulting file conservatively.
        parent = output.parent
        pattern = output.name.replace("%(ext)s", "*")
        matches = [item for item in parent.glob(pattern) if item.is_file()]
        if not matches and output.is_file():
            matches = [output]
        if not matches:
            raise CapabilityExecutionError("yt-dlp completed without a discoverable output artifact")
        artifacts = [_artifact(item) for item in sorted(matches)[:10]]
        return self._result(
            operation,
            started=started,
            output={"files": [item["path"] for item in artifacts], "mode": mode},
            artifacts=artifacts,
        )


class ComfyUIAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="comfyui",
        name="ComfyUI",
        category="image_generation",
        operations=("queue_workflow", "history", "run_workflow"),
        ram_mb=200,
        heavy=False,
        networked=True,
        install_hint="Run ComfyUI separately and set COMFYUI_URL; remote/on-demand is preferred on an 8 GB Mac",
        licence="GPL-3.0 code; model licences vary",
    )

    def available(self) -> tuple[bool, str]:
        url = os.environ.get("COMFYUI_URL", "").strip()
        if not url:
            return False, "COMFYUI_URL is not configured"
        host = (urlsplit(url).hostname or "").lower()
        local = host in {"localhost", "127.0.0.1", "::1"}
        allow_local = os.environ.get("AMAURA_ALLOW_LOCAL_COMFYUI", "0").strip().lower() in {"1", "true", "yes", "on"}
        if local and not allow_local:
            return False, "Local ComfyUI is disabled by default on the 8 GB Mac profile; use a remote endpoint or set AMAURA_ALLOW_LOCAL_COMFYUI=1"
        if not local:
            try:
                validate_public_url(url, resolve=True)
            except GovernanceError as exc:
                return False, f"COMFYUI_URL is not a safe public endpoint: {exc}"
        return True, "configured"

    def _base(self) -> tuple[str, bool]:
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        base = os.environ.get("COMFYUI_URL", "").rstrip("/")
        host = (urlsplit(base).hostname or "").lower()
        local = host in {"localhost", "127.0.0.1", "::1"}
        return base, local

    @staticmethod
    def _headers() -> dict[str, str]:
        token = os.environ.get("COMFYUI_API_TOKEN", "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _json(self, base: str, local: bool, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        url = f"{base}{path}"
        headers = self._headers()
        if not local:
            status, data, _ = request_json(url, method=method, payload=payload, headers=headers, timeout=timeout)
            if not 200 <= status < 300:
                raise CapabilityExecutionError(f"ComfyUI returned HTTP {status}")
            return data
        try:
            response = httpx.request(method, url, json=payload, headers=headers, timeout=timeout, follow_redirects=False)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CapabilityExecutionError(f"ComfyUI request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise CapabilityExecutionError("ComfyUI returned a non-object JSON response")
        return data

    def _bytes(self, base: str, local: bool, path: str, *, max_bytes: int = 25_000_000) -> bytes:
        url = f"{base}{path}"
        headers = self._headers()
        if not local:
            status, data, _ = request_bytes(url, method="GET", headers=headers, timeout=30, max_response_bytes=max_bytes)
            if not 200 <= status < 300:
                raise CapabilityExecutionError(f"ComfyUI artifact returned HTTP {status}")
            return data
        try:
            response = httpx.get(url, headers=headers, timeout=30, follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CapabilityExecutionError(f"ComfyUI artifact download failed: {exc}") from exc
        if len(response.content) > max_bytes:
            raise GovernanceError("ComfyUI artifact exceeds configured byte limit")
        return bytes(response.content)

    @staticmethod
    def _validate_image_bytes(data: bytes) -> str:
        signatures = {
            b"\x89PNG\r\n\x1a\n": ".png",
            b"\xff\xd8\xff": ".jpg",
            b"RIFF": ".webp",
        }
        for prefix, suffix in signatures.items():
            if data.startswith(prefix):
                if suffix == ".webp" and (len(data) < 12 or data[8:12] != b"WEBP"):
                    continue
                return suffix
        raise GovernanceError("ComfyUI returned bytes that are not a supported image")

    @staticmethod
    def _image_descriptors(history: dict[str, Any], prompt_id: str) -> list[dict[str, str]]:
        record = history.get(prompt_id, history)
        outputs = record.get("outputs", {}) if isinstance(record, dict) else {}
        found: list[dict[str, str]] = []
        if not isinstance(outputs, dict):
            return found
        for node in outputs.values():
            if not isinstance(node, dict):
                continue
            images = node.get("images", [])
            if not isinstance(images, list):
                continue
            for image in images:
                if not isinstance(image, dict):
                    continue
                filename = Path(str(image.get("filename", ""))).name
                if not filename:
                    continue
                found.append({
                    "filename": filename,
                    "subfolder": str(image.get("subfolder", "")),
                    "type": str(image.get("type", "output")),
                })
        return found

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        started = time.monotonic()
        base, local = self._base()
        if operation in {"queue_workflow", "run_workflow"}:
            workflow = params.get("workflow")
            if not isinstance(workflow, dict) or not workflow:
                raise GovernanceError("ComfyUI workflow operation requires an API-format workflow object")
            client_id = str(params.get("client_id", uuid.uuid4()))
            payload = self._json(base, local, "/prompt", method="POST", payload={"prompt": workflow, "client_id": client_id}, timeout=30)
            prompt_id = str(payload.get("prompt_id", "")).strip()
            if not prompt_id:
                raise CapabilityExecutionError("ComfyUI returned no prompt_id")
            if operation == "queue_workflow":
                return self._result(operation, started=started, output={"prompt_id": prompt_id, "client_id": client_id})

            timeout = max(5.0, min(float(params.get("timeout", 300.0)), 1800.0))
            poll = max(0.25, min(float(params.get("poll_interval", 1.0)), 10.0))
            deadline = time.monotonic() + timeout
            history: dict[str, Any] = {}
            images: list[dict[str, str]] = []
            while time.monotonic() < deadline:
                history = self._json(base, local, f"/history/{prompt_id}", timeout=20)
                images = self._image_descriptors(history, prompt_id)
                if images:
                    break
                time.sleep(poll)
            if not images:
                raise CapabilityExecutionError("ComfyUI workflow timed out before producing image artifacts")

            output_dir = resolve_workspace_path(str(params.get("output_dir", "comfyui-output")), must_exist=False)
            output_dir.mkdir(parents=True, exist_ok=True)
            max_artifacts = max(1, min(int(params.get("max_artifacts", 8)), 32))
            artifacts: list[dict[str, Any]] = []
            downloaded: list[str] = []
            for index, item in enumerate(images[:max_artifacts], start=1):
                query = urlencode({"filename": item["filename"], "subfolder": item["subfolder"], "type": item["type"]})
                data = self._bytes(base, local, f"/view?{query}")
                suffix = self._validate_image_bytes(data)
                stem = Path(item["filename"]).stem[:120] or f"comfy-{index}"
                destination = output_dir / f"{stem}-{index}{suffix}"
                destination.write_bytes(data)
                artifacts.append(_artifact(destination))
                downloaded.append(str(destination))
            return self._result(
                operation, started=started,
                output={
                    "prompt_id": prompt_id,
                    "client_id": client_id,
                    "downloaded": downloaded,
                    "artifact_count": len(downloaded),
                    "history": _jsonable(history),
                },
                artifacts=artifacts,
            )

        prompt_id = str(params.get("prompt_id", "")).strip()
        if not prompt_id:
            raise GovernanceError("ComfyUI history requires prompt_id")
        history = self._json(base, local, f"/history/{prompt_id}", timeout=20)
        return self._result(operation, started=started, output={"history": history})


class MCPAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="mcp",
        name="Model Context Protocol",
        category="integration_protocol",
        operations=("list_tools", "call_tool"),
        ram_mb=250,
        side_effects=True,
        install_hint="pip install mcp; configure ~/.config/amaura/mcp_servers.json",
        licence="MIT",
    )

    def available(self) -> tuple[bool, str]:
        if not _module_available("mcp"):
            return False, "Python package 'mcp' is not installed"
        return True, "installed; approved server registry is checked per request"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        if operation == "call_tool":
            enabled = os.environ.get("AMAURA_MCP_TOOL_CALLS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
            if not enabled:
                raise GovernanceError("MCP tool calls are disabled; set AMAURA_MCP_TOOL_CALLS_ENABLED=1 only for a founder-approved integration")
            if not bool(params.get("founder_approved", False)):
                raise GovernanceError("MCP tool calls require founder_approved=true")
        server_id = str(params.get("server_id", "")).strip()
        if not server_id:
            raise GovernanceError("MCP requests require founder-approved server_id")
        spec = load_server(server_id, for_ai_list=(operation == "list_tools"))
        if operation == "call_tool" and not spec.allow_tool_calls:
            raise GovernanceError(f"MCP server '{server_id}' is registered read-only")
        started = time.monotonic()

        async def _session_call() -> dict[str, Any]:
            from mcp import ClientSession, StdioServerParameters  # type: ignore
            from mcp.client.stdio import stdio_client  # type: ignore

            command, args, cleanup = spec.command_argv()
            try:
                server = StdioServerParameters(command=command, args=args, env=spec.child_env())
                async with stdio_client(server) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await asyncio.wait_for(session.initialize(), timeout=spec.timeout_seconds)
                        if operation == "list_tools":
                            tools = await asyncio.wait_for(session.list_tools(), timeout=spec.timeout_seconds)
                            return {"server_id": server_id, "tools": _jsonable(tools)}
                        tool_name = str(params.get("tool_name", "")).strip()
                        if not tool_name:
                            raise GovernanceError("MCP call_tool requires tool_name")
                        if spec.allowed_tools and tool_name not in spec.allowed_tools:
                            raise GovernanceError(f"MCP tool is not in founder registry allowlist: {tool_name}")
                        arguments = params.get("arguments") or {}
                        if not isinstance(arguments, dict):
                            raise GovernanceError("MCP arguments must be an object")
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments=arguments), timeout=spec.timeout_seconds
                        )
                        return {"server_id": server_id, "tool_name": tool_name, "result": _jsonable(result)}
            finally:
                for path in cleanup:
                    path.unlink(missing_ok=True)

        return self._result(operation, started=started, output=_run_async(_session_call))


class LangfuseAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="langfuse",
        name="Langfuse",
        category="observability",
        operations=("health", "event"),
        ram_mb=120,
        networked=True,
        install_hint="pip install langfuse and configure LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY/LANGFUSE_BASE_URL",
        licence="MIT client; server core open source",
    )

    def available(self) -> tuple[bool, str]:
        ok = _module_available("langfuse") and bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
        return ok, "configured" if ok else "Langfuse SDK/credentials are not configured"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        started = time.monotonic()
        from langfuse import get_client  # type: ignore

        client = get_client()
        if operation == "health":
            return self._result(operation, started=started, output={"authenticated": bool(client.auth_check())})
        name = str(params.get("name", "amaura.capability.event")).strip()
        payload = params.get("metadata") or {}
        if not isinstance(payload, dict):
            raise GovernanceError("Langfuse metadata must be an object")
        # v4's observation context is fail-soft and OTEL-backed.
        with client.start_as_current_observation(as_type="span", name=name) as span:
            if hasattr(span, "update"):
                span.update(metadata=payload)
        with contextlib.suppress(Exception):
            client.flush()
        return self._result(operation, started=started, output={"recorded": True, "name": name})


class AntigravityAdapter(_BaseAdapter):
    descriptor = CapabilityDescriptor(
        key="antigravity",
        name="Google Antigravity",
        category="engineering",
        operations=("prepare_handoff",),
        ram_mb=0,
        side_effects=False,
        install_hint="Legacy founder handoff: set AMAURA_ANTIGRAVITY_ENABLED=1. JARVIS v5.4 autonomous coding uses the official agy CLI via AntigravityDeliveryAdapter.",
        licence="External subscription/service",
    )

    def available(self) -> tuple[bool, str]:
        enabled = os.environ.get("AMAURA_ANTIGRAVITY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        return enabled, "founder handoff enabled" if enabled else "AMAURA_ANTIGRAVITY_ENABLED is not enabled"

    def execute(self, operation: str, params: dict[str, Any]) -> CapabilityResult:
        self._check_operation(operation)
        available, reason = self.available()
        if not available:
            raise CapabilityUnavailable(reason)
        repo = resolve_workspace_path(str(params.get("repo_path", ".")), must_exist=True)
        objective = str(params.get("objective", "")).strip()
        if not objective:
            raise GovernanceError("Antigravity handoff requires objective")
        started = time.monotonic()
        packet = {
            "objective": objective,
            "repository": str(repo),
            "constraints": [str(v) for v in params.get("constraints", [])],
            "acceptance_criteria": [str(v) for v in params.get("acceptance_criteria", [])],
            "test_commands": [str(v) for v in params.get("test_commands", [])],
            "context": params.get("context") or {},
            "founder_review_required": True,
            "execution_mode": "manual_founder_handoff",
        }
        output_path = _safe_local_output(str(params.get("output_path", ".amaura-antigravity-handoff.json")))
        output_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        return self._result(operation, started=started, output={"packet": packet, "output_path": str(output_path)}, artifacts=[_artifact(output_path)])


ADAPTER_TYPES: tuple[type[_BaseAdapter], ...] = (
    PlaywrightAdapter,
    Crawl4AIAdapter,
    BrowserUseAdapter,
    SearXNGAdapter,
    DoclingAdapter,
    PyMuPDFAdapter,
    PaddleOCRAdapter,
    LlamaIndexAdapter,
    FastEmbedQdrantAdapter,
    FasterWhisperAdapter,
    KokoroAdapter,
    FFmpegAdapter,
    RemotionAdapter,
    ImageTransformAdapter,
    YtDlpAdapter,
    ComfyUIAdapter,
    MCPAdapter,
    LangfuseAdapter,
    AntigravityAdapter,
)


CAPABILITY_OPERATION_CONTRACTS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "playwright": {
        "extract": {"required": ("url",), "optional": ("selector", "timeout_ms")},
        "screenshot": {"required": ("url", "output_path"), "optional": ("full_page", "timeout_ms")},
    },
    "crawl4ai": {"crawl": {"required": ("url",), "optional": ()}},
    "browser_use": {
        "research": {"required": ("task", "allowed_domains"), "optional": ("max_steps", "use_vision")},
    },
    "searxng": {"search": {"required": ("query",), "optional": ("limit", "language", "safesearch")}},
    "docling": {
        "convert": {"required": ("source_path",), "optional": ("output_path", "max_pages", "max_file_size")},
    },
    "pymupdf": {
        "extract_text": {"required": ("source_path",), "optional": ("max_pages",)},
        "render_page": {"required": ("source_path", "output_path"), "optional": ("page", "scale")},
    },
    "paddleocr": {
        "ocr": {"required": ("source_path",), "optional": ("output_path", "lang", "device", "cpu_threads", "ocr_version")},
    },
    "llamaindex": {
        "chunk": {"required": ("text",), "optional": ("chunk_size", "chunk_overlap")},
    },
    "qdrant_fastembed": {
        "upsert": {"required": ("documents",), "optional": ("collection", "metadata", "ids")},
        "query": {"required": ("query",), "optional": ("collection", "limit")},
    },
    "faster_whisper": {
        "transcribe": {"required": ("source_path",), "optional": ("model", "device", "compute_type", "cpu_threads", "beam_size", "vad_filter", "word_timestamps", "language")},
    },
    "kokoro": {
        "synthesize": {"required": ("text", "output_path"), "optional": ("lang_code", "voice", "speed")},
    },
    "ffmpeg": {
        "probe": {"required": ("source_path",), "optional": ()},
        "transcode": {"required": ("source_path", "output_path"), "optional": ("video_codec", "audio_codec", "width", "height", "timeout")},
        "burn_subtitles": {"required": ("source_path", "subtitle_path", "output_path"), "optional": ("timeout",)},
        "concat": {"required": ("source_paths", "output_path"), "optional": ("timeout",)},
        "mux_audio": {"required": ("source_path", "audio_path", "output_path"), "optional": ("audio_codec", "timeout")},
    },
    "remotion": {
        "bootstrap_project": {"required": (), "optional": ("project_path", "version", "overwrite")},
        "lock_project": {"required": ("project_path",), "optional": ("timeout",)},
        "render": {"required": ("project_path", "composition", "output_path"), "optional": ("props", "timeout")},
    },
    "image_tools": {
        "resize": {"required": ("source_path", "output_path"), "optional": ("width", "height")},
        "thumbnail": {"required": ("source_path", "output_path"), "optional": ("width", "height")},
    },
    "yt_dlp": {
        "metadata": {"required": ("url",), "optional": ("timeout",)},
        "download": {"required": ("url", "output_path", "rights_confirmed"), "optional": ("mode", "audio_format", "max_filesize_mb", "timeout")},
    },
    "comfyui": {
        "queue_workflow": {"required": ("workflow",), "optional": ("client_id",)},
        "history": {"required": ("prompt_id",), "optional": ()},
        "run_workflow": {"required": ("workflow", "output_dir"), "optional": ("client_id", "timeout", "poll_interval", "max_artifacts")},
    },
    "mcp": {
        "list_tools": {"required": ("server_id",), "optional": ()},
        "call_tool": {"required": ("server_id", "tool_name"), "optional": ("arguments", "founder_approved")},
    },
    "langfuse": {
        "health": {"required": (), "optional": ()},
        "event": {"required": ("name",), "optional": ("metadata",)},
    },
    "antigravity": {
        "prepare_handoff": {"required": ("repo_path", "objective", "output_path"), "optional": ("constraints", "acceptance_criteria", "test_commands", "context")},
    },
}


ISOLATED_PYTHON_CAPABILITIES = frozenset({
    "playwright", "crawl4ai", "browser_use", "docling", "paddleocr",
    "qdrant_fastembed", "faster_whisper", "kokoro"
})

_BASE_WORKER_ENV = frozenset({
    "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE", "XDG_CACHE_HOME",
})

CAPABILITY_ENV_ALLOWLIST: dict[str, frozenset[str]] = {
    "playwright": frozenset({"PLAYWRIGHT_BROWSERS_PATH", "AMAURA_BROWSER_MAX_RESPONSE_MB"}),
    "crawl4ai": frozenset({"PLAYWRIGHT_BROWSERS_PATH", "AMAURA_BROWSER_MAX_RESPONSE_MB"}),
    "browser_use": frozenset({
        "AMAURA_BROWSER_USE_AGENT_ENABLED", "AMAURA_BROWSER_USE_MODEL",
        "AMAURA_BROWSER_USE_ALLOW_PAID", "GOOGLE_API_KEY", "GROQ_API_KEY",
        "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_HOST",
        "PLAYWRIGHT_BROWSERS_PATH",
    }),
    "docling": frozenset({"DOCLING_ARTIFACTS_PATH", "DOCLING_CACHE_DIR"}),
    "paddleocr": frozenset({"PADDLE_HOME", "PADDLE_PDX_CACHE_HOME"}),
    "qdrant_fastembed": frozenset({"QDRANT_URL", "QDRANT_API_KEY", "AMAURA_QDRANT_PATH", "FASTEMBED_CACHE_PATH"}),
    "faster_whisper": frozenset({"AMAURA_WHISPER_MODEL", "HF_TOKEN"}),
    "kokoro": frozenset({"KOKORO_MODEL_PATH", "KOKORO_VOICE_PATH"}),
    "antigravity": frozenset({"AMAURA_ANTIGRAVITY_ENABLED"}),
}


def _capability_worker_env(key: str, root: Path) -> dict[str, str]:
    allowed = _BASE_WORKER_ENV | CAPABILITY_ENV_ALLOWLIST.get(key, frozenset())
    env = {name: value for name in allowed if (value := os.environ.get(name))}
    env["AMAURA_CAPABILITY_WORKER"] = "1"
    env["JARVIS_WORKSPACE_ROOT"] = str(root)
    package_root = str(Path(__file__).resolve().parents[2])
    # Never inherit a caller-controlled PYTHONPATH; the worker gets only Amaura's package root.
    env["PYTHONPATH"] = package_root
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _heavy_lock_path() -> Path:
    raw = os.environ.get("AMAURA_CAPABILITY_HEAVY_LOCK", "").strip()
    path = Path(raw).expanduser() if raw else workspace_root() / ".amaura-data" / "capability-heavy.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


@contextlib.contextmanager
def _cross_process_heavy_lock(timeout: float):
    """Serialize heavy capability jobs across Amaura worker processes on POSIX."""
    if os.name != "posix":
        yield
        return
    try:
        import fcntl
    except ImportError:
        yield
        return
    path = _heavy_lock_path()
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + max(0.1, timeout)
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CapabilityExecutionError(
                        "Another heavy Amaura capability is already running; retry after it completes"
                    )
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)



class CapabilityScheduler:
    """Cross-process pressure-aware scheduler for the 8 GB Mac profile.

    v3.6.1 no longer treats one 5.6 GB estimate as a memory ceiling. The
    scheduler uses a durable host-wide reservation ledger, live memory/swap
    pressure, and a 1.5 GB normal / 2.5 GB burst / 3 GB absolute policy.
    """

    def __init__(self, budget_mb: int | None = None):
        self.policy = MemoryPolicy.from_env()
        # Backward-compatible constructor: an explicit test/operator budget maps
        # to the burst ceiling while never raising the absolute safety ceiling.
        if budget_mb is not None:
            requested = max(512, int(budget_mb))
            self.policy = MemoryPolicy(
                normal_target_mb=min(self.policy.normal_target_mb, requested),
                burst_limit_mb=min(requested, self.policy.burst_limit_mb),
                absolute_limit_mb=self.policy.absolute_limit_mb,
                pressure_limit_mb=min(self.policy.pressure_limit_mb, requested),
                yellow_available_mb=self.policy.yellow_available_mb,
                red_available_mb=self.policy.red_available_mb,
                yellow_used_percent=self.policy.yellow_used_percent,
                red_used_percent=self.policy.red_used_percent,
                yellow_swap_percent=self.policy.yellow_swap_percent,
                red_swap_percent=self.policy.red_swap_percent,
                swap_growth_abort_mb=self.policy.swap_growth_abort_mb,
                stale_reservation_seconds=self.policy.stale_reservation_seconds,
            )
        self.ledger = CrossProcessResourceLedger(self.policy)
        self._local_lock = threading.RLock()
        self._local_reservations: set[str] = set()

    @contextlib.contextmanager
    def reserve(self, descriptor: CapabilityDescriptor, timeout: float = 5.0):
        deadline = time.monotonic() + max(0.1, timeout)
        reservation_id: str | None = None
        last_reason = "resource admission unavailable"
        last_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            reservation_id, last_reason, last_state = self.ledger.try_reserve(
                capability=descriptor.key, ram_mb=descriptor.ram_mb, heavy=descriptor.heavy
            )
            if reservation_id:
                break
            time.sleep(min(0.15, max(0.01, deadline - time.monotonic())))
        if not reservation_id:
            raise CapabilityExecutionError(
                f"Resource scheduler refused {descriptor.key}: {last_reason}; state={json.dumps(last_state, sort_keys=True, default=str)}"
            )

        with self._local_lock:
            self._local_reservations.add(reservation_id)
        previous_limit = getattr(_RESOURCE_CONTEXT, "child_hard_limit_mb", None)
        previous_heavy = getattr(_RESOURCE_CONTEXT, "heavy", False)
        _RESOURCE_CONTEXT.child_hard_limit_mb = child_hard_limit_mb(descriptor.ram_mb, self.policy)
        _RESOURCE_CONTEXT.heavy = bool(descriptor.heavy)
        try:
            yield
        finally:
            _RESOURCE_CONTEXT.child_hard_limit_mb = previous_limit
            _RESOURCE_CONTEXT.heavy = previous_heavy
            self.ledger.release(reservation_id)
            with self._local_lock:
                self._local_reservations.discard(reservation_id)

    def status(self) -> dict[str, Any]:
        ledger = self.ledger.snapshot()
        host = sample_host_memory(self.policy)
        return {
            "mode": "pressure" if host.pressure == "red" else "guarded" if host.pressure == "yellow" else "normal",
            "pressure": host.pressure,
            "normal_target_mb": self.policy.normal_target_mb,
            "burst_limit_mb": self.policy.burst_limit_mb,
            "absolute_limit_mb": self.policy.absolute_limit_mb,
            "pressure_limit_mb": self.policy.pressure_limit_mb,
            "active_mb": int(ledger["reserved_mb"]),
            "active_heavy_jobs": int(ledger["active_heavy_jobs"]),
            "active_jobs": int(ledger["active_jobs"]),
            "process_tree_rss_mb": process_tree_rss_mb(os.getpid()),
            "host": host.to_dict(),
        }


_MODULE_BY_CAPABILITY = {
    "playwright": "playwright", "crawl4ai": "crawl4ai", "browser_use": "browser_use",
    "docling": "docling", "pymupdf": "fitz", "paddleocr": "paddleocr",
    "llamaindex": "llama_index.core", "qdrant_fastembed": "qdrant_client",
    "faster_whisper": "faster_whisper", "kokoro": "kokoro", "mcp": "mcp",
    "langfuse": "langfuse",
}

_PACKAGE_BY_CAPABILITY = {
    "playwright": "playwright", "crawl4ai": "crawl4ai", "browser_use": "browser-use",
    "docling": "docling", "pymupdf": "PyMuPDF", "paddleocr": "paddleocr",
    "llamaindex": "llama-index-core", "qdrant_fastembed": "qdrant-client",
    "faster_whisper": "faster-whisper", "kokoro": "kokoro", "mcp": "mcp",
    "langfuse": "langfuse",
}

_EXECUTABLE_BY_CAPABILITY = {
    "ffmpeg": "ffmpeg", "remotion": "node", "yt_dlp": "yt-dlp",
}


def _package_version(key: str) -> str:
    package = _PACKAGE_BY_CAPABILITY.get(key)
    if not package:
        return ""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _installed_state(key: str) -> bool:
    module = _MODULE_BY_CAPABILITY.get(key)
    if module:
        return _module_available(module)
    executable = _EXECUTABLE_BY_CAPABILITY.get(key)
    if executable:
        return bool(shutil.which(executable))
    if key == "image_tools":
        return bool(shutil.which("magick") or shutil.which("vipsthumbnail"))
    if key in {"searxng", "comfyui", "antigravity"}:
        return True
    return False


def _cheap_execution_ready(key: str, available: bool) -> bool:
    # These adapters' ordinary availability checks are sufficient to establish
    # executable readiness without downloading models or touching the network.
    return bool(available and key in {"pymupdf", "ffmpeg", "image_tools", "llamaindex", "antigravity"})


def _deep_probe(key: str, adapter: CapabilityAdapter) -> tuple[bool, str]:
    """Run a non-destructive smoke probe. Never download a model implicitly."""
    available, reason = adapter.available()
    if not available:
        return False, reason
    try:
        if key == "playwright":
            from playwright.sync_api import sync_playwright  # type: ignore
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True, "Chromium launched and exited successfully"
        if key == "pymupdf":
            import fitz  # type: ignore
            document = fitz.open()
            document.close()
            return True, "PyMuPDF opened an in-memory document"
        if key == "ffmpeg":
            executable = shutil.which("ffmpeg")
            if not executable:
                return False, "ffmpeg executable is missing"
            proc = _run([executable, "-version"], timeout=10, max_rss_mb=256)
            return proc.returncode == 0, "ffmpeg -version succeeded" if proc.returncode == 0 else _bounded_text(proc.stderr, 500)
        if key == "image_tools":
            executable = shutil.which("magick") or shutil.which("vipsthumbnail")
            if not executable:
                return False, "image executable is missing"
            proc = _run([executable, "-version"], timeout=10, max_rss_mb=256)
            return proc.returncode == 0, "image tool version probe succeeded" if proc.returncode == 0 else _bounded_text(proc.stderr, 500)
        if key == "llamaindex":
            from llama_index.core import Document  # type: ignore
            from llama_index.core.node_parser import SentenceSplitter  # type: ignore
            nodes = SentenceSplitter(chunk_size=128, chunk_overlap=0).get_nodes_from_documents([Document(text="Amaura probe sentence.")])
            return bool(nodes), "LlamaIndex chunk smoke succeeded"
        if key == "comfyui":
            base, local = adapter._base()  # type: ignore[attr-defined]
            adapter._json(base, local, "/system_stats", timeout=10)  # type: ignore[attr-defined]
            return True, "ComfyUI /system_stats succeeded"
        if key in {"crawl4ai", "browser_use", "searxng", "qdrant_fastembed", "faster_whisper", "kokoro", "paddleocr", "docling", "remotion", "mcp", "langfuse"}:
            return False, "Installed/configured, but execution readiness requires an explicit fixture/service/model-specific smoke job"
        if key == "antigravity":
            return True, "Structured handoff adapter is ready"
        return False, "No deep probe is defined"
    except Exception as exc:
        return False, _bounded_text(exc, 1000)


class CapabilityRuntime:
    """Registry, health, routing and execution surface for optional OSS tools."""

    def __init__(self, *, scheduler: CapabilityScheduler | None = None):
        self.adapters: dict[str, CapabilityAdapter] = {adapter.descriptor.key: adapter() for adapter in ADAPTER_TYPES}
        self.scheduler = scheduler or CapabilityScheduler()

    def _health_row(self, key: str, *, deep: bool = False) -> dict[str, Any]:
        adapter = self.adapters[key]
        available, reason = adapter.available()
        installed = _installed_state(key)
        healthy: bool | None = None
        verification = "not execution-verified"
        execution_ready = _cheap_execution_ready(key, bool(available))
        if deep:
            healthy, verification = _deep_probe(key, adapter)
            execution_ready = bool(healthy)
        row = asdict(adapter.descriptor)
        row.update({
            "installed": bool(installed),
            "configured": bool(available),
            "healthy": healthy,
            "execution_ready": bool(execution_ready),
            "verified_at": time.time() if deep else None,
            "version": _package_version(key),
            # Backward-compatible field, now explicitly means configured/admissible prerequisites.
            "available": bool(available),
            "reason": reason,
            "verification": verification,
        })
        return row

    def inventory(self, *, deep: bool = False) -> list[dict[str, Any]]:
        return [self._health_row(key, deep=deep) for key in sorted(self.adapters)]

    def health(self, key: str = "", *, deep: bool = False) -> dict[str, Any]:
        if key:
            if key not in self.adapters:
                raise GovernanceError(f"Unknown capability: {key}")
            row = self._health_row(key, deep=deep)
            return {
                "capability": key,
                **row,
                "descriptor": asdict(self.adapters[key].descriptor),
                "contracts": CAPABILITY_OPERATION_CONTRACTS.get(key, {}),
                "scheduler": self.scheduler.status(),
            }
        return {"capabilities": self.inventory(deep=deep), "scheduler": self.scheduler.status()}

    def plan(self, intent: str) -> dict[str, Any]:
        key = intent.strip().lower().replace("-", "_").replace(" ", "_")
        pipelines: dict[str, list[tuple[str, str, str]]] = {
            "web_research": [
                ("searxng", "search", "Search broadly when a configured metasearch instance is available."),
                ("crawl4ai", "crawl", "Extract structured Markdown from selected public pages."),
                ("playwright", "extract", "Validate dynamic pages or capture rendered content."),
                ("browser_use", "research", "Use only as a bounded read-only fallback for interactive sites."),
            ],
            "lead_research": [
                ("searxng", "search", "Discover candidate public business pages."),
                ("crawl4ai", "crawl", "Extract business facts and contact evidence."),
                ("playwright", "extract", "Handle JavaScript-rendered public pages when necessary."),
            ],
            "document_ingest": [
                ("pymupdf", "extract_text", "Fast path for ordinary PDFs."),
                ("docling", "convert", "Rich structure/tables/documents when the fast path is insufficient."),
                ("paddleocr", "ocr", "OCR fallback for scans or image-heavy documents."),
                ("llamaindex", "chunk", "Chunk normalized text for retrieval."),
                ("qdrant_fastembed", "upsert", "Store lightweight local semantic memory."),
            ],
            "knowledge_query": [
                ("qdrant_fastembed", "query", "Retrieve semantically relevant company knowledge."),
            ],
            "transcription": [
                ("faster_whisper", "transcribe", "Generate transcript and timestamps using an int8 CPU profile."),
            ],
            "voiceover": [
                ("kokoro", "synthesize", "Generate lightweight local narration."),
                ("ffmpeg", "probe", "Validate produced audio before use."),
            ],
            "reel": [
                ("kokoro", "synthesize", "Generate approved narration when required."),
                ("image_tools", "thumbnail", "Prepare deterministic visual assets cheaply."),
                ("remotion", "render", "Render the vertical composition from a pinned local template."),
                ("ffmpeg", "mux_audio", "Mux approved narration into the rendered video when voiceover is separate."),
                ("ffmpeg", "probe", "Validate the final render and codecs."),
            ],
            "youtube_video": [
                ("kokoro", "synthesize", "Generate narration where appropriate."),
                ("image_tools", "resize", "Normalize assets without generative compute."),
                ("remotion", "render", "Render the approved long-form composition from a pinned local template."),
                ("ffmpeg", "mux_audio", "Mux approved narration into the master when voiceover is separate."),
                ("ffmpeg", "probe", "Validate the master video."),
            ],
            "generate_image": [
                ("comfyui", "queue_workflow", "Optional heavy generative path; prefer remote/on-demand on 8 GB Macs."),
                ("image_tools", "resize", "Normalize final generated asset."),
            ],
            "engineering": [
                ("antigravity", "prepare_handoff", "Create the founder-reviewed engineering packet for Antigravity."),
            ],
            "observability": [
                ("langfuse", "event", "Mirror non-authoritative execution telemetry while Amaura audit remains source of truth."),
            ],
        }
        aliases = {
            "research": "web_research", "browser_research": "web_research", "lead": "lead_research",
            "pdf": "document_ingest", "documents": "document_ingest", "rag": "document_ingest",
            "memory": "knowledge_query", "audio": "voiceover", "short": "reel", "shorts": "reel",
            "video": "youtube_video", "image": "generate_image", "coding": "engineering",
        }
        key = aliases.get(key, key)
        if key not in pipelines:
            raise GovernanceError(f"Unknown capability intent '{intent}'")
        steps = []
        for capability, operation, purpose in pipelines[key]:
            adapter = self.adapters[capability]
            available, reason = adapter.available()
            steps.append({
                "capability": capability, "operation": operation, "purpose": purpose,
                "available": available, "availability_reason": reason,
                "ram_mb": adapter.descriptor.ram_mb, "heavy": adapter.descriptor.heavy,
                "contract": CAPABILITY_OPERATION_CONTRACTS.get(capability, {}).get(operation, {}),
            })
        return {
            "intent": key,
            "steps": steps,
            "execution_policy": "Use available lightweight steps first; start heavy workers only on demand; founder approval remains required for consequential external actions.",
            "scheduler": self.scheduler.status(),
        }

    def _execute_isolated(self, key: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        root = workspace_root()
        root.mkdir(parents=True, exist_ok=True)
        runtime_dir = root / ".amaura-data" / "capability-workers"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        request_fd, request_name = tempfile.mkstemp(prefix="request-", suffix=".json", dir=str(runtime_dir))
        response_fd, response_name = tempfile.mkstemp(prefix="response-", suffix=".json", dir=str(runtime_dir))
        os.close(request_fd)
        os.close(response_fd)
        request_path = Path(request_name)
        response_path = Path(response_name)
        try:
            request_path.chmod(0o600)
            response_path.chmod(0o600)
            request_path.write_text(
                json.dumps({"capability": key, "operation": operation, "params": params}, ensure_ascii=False),
                encoding="utf-8",
            )
            env = _capability_worker_env(key, root)
            timeout = max(30, min(int(params.get("timeout", 1800)), 3600))
            proc = _run(
                [
                    sys.executable, "-m", "jarvis.amaura.capability_worker",
                    "--request", str(request_path), "--response", str(response_path),
                ],
                cwd=root,
                timeout=timeout,
                env=env,
            )
            if proc.returncode != 0 and not response_path.stat().st_size:
                raise CapabilityExecutionError(
                    _bounded_text(proc.stderr or proc.stdout or f"isolated worker exited {proc.returncode}", 12_000)
                )
            try:
                payload = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CapabilityExecutionError("Isolated capability worker returned invalid evidence") from exc
            if not payload.get("ok", False):
                message = str(payload.get("error", "isolated capability failed"))
                error_type = str(payload.get("error_type", ""))
                if error_type == "CapabilityUnavailable":
                    raise CapabilityUnavailable(message)
                if error_type in {"GovernanceError", "PermissionError", "FileNotFoundError"}:
                    raise GovernanceError(message)
                raise CapabilityExecutionError(message)
            result = payload.get("result")
            if not isinstance(result, dict):
                raise CapabilityExecutionError("Isolated capability worker returned malformed result")
            return result
        finally:
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)

    def execute(self, key: str, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        adapter = self.adapters.get(key)
        if adapter is None:
            raise GovernanceError(f"Unknown capability: {key}")
        params = params or {}
        if not isinstance(params, dict):
            raise GovernanceError("Capability params must be an object")
        contract = CAPABILITY_OPERATION_CONTRACTS.get(key, {}).get(operation)
        if contract is None:
            raise GovernanceError(f"Unsupported capability operation: {key}/{operation}")
        missing = [name for name in contract.get("required", ()) if name not in params or params.get(name) in (None, "")]
        if missing:
            raise GovernanceError(f"{key}/{operation} is missing required params: {', '.join(missing)}")
        wait_seconds = max(0.1, min(float(params.get("scheduler_wait_seconds", 120.0)), 300.0))
        with self.scheduler.reserve(adapter.descriptor, timeout=wait_seconds):
            try:
                isolate = (
                    key in ISOLATED_PYTHON_CAPABILITIES
                    and os.environ.get("AMAURA_CAPABILITY_WORKER", "0") != "1"
                )
                if isolate:
                    return self._execute_isolated(key, operation, params)
                return adapter.execute(operation, params).to_dict()
            except (GovernanceError, PermissionError, FileNotFoundError):
                raise
            except Exception as exc:
                raise CapabilityExecutionError(f"{key}/{operation} failed: {exc}") from exc


_RUNTIME: CapabilityRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_capability_runtime() -> CapabilityRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        with _RUNTIME_LOCK:
            if _RUNTIME is None:
                _RUNTIME = CapabilityRuntime()
    return _RUNTIME


__all__ = [
    "ADAPTER_TYPES",
    "CAPABILITY_OPERATION_CONTRACTS",
    "CapabilityDescriptor",
    "CapabilityExecutionError",
    "CapabilityResult",
    "CapabilityRuntime",
    "CapabilityScheduler",
    "CapabilityUnavailable",
    "ISOLATED_PYTHON_CAPABILITIES",
    "get_capability_runtime",
]
