"""Phase 6 ARCH Test Suite: Targeted Repairs for V6 Holdout Failures.

Validates:
1. Write Parser — Second-sentence 'Use this as body: PAYLOAD' (FAIL 01)
2. Write Parser — Quoted payload with instruction metadata stripping (FAIL 02)
3. Write Parser — Multiline block after content introducer + colon + newline (FAIL 03)
4. Screenshot Routing — Semantic 'capture the screen' detection (FAIL 15)
5. Exact Response Grammar — Suffix/prefix/trailing comma stripping (FAIL 16 partial)
6. Repository Diagnosis — Call-graph wrong-helper detection (FAIL 11)
7. Action Collision Prevention — screenshot vs write ordering
8. Generative write permutations (>= 500 additional from Phase 5)
9. Exact response generative (>= 1000 grammar variants)
10. Concurrency bursts (20, 40, 60, 80)
"""

import concurrent.futures
import hashlib
import json
import os
import random
import string
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.amaura.direct_action import (
    DirectActionResult,
    DirectActionRouter,
    ExactResponseParser,
    FilesystemActionClassifier,
    FilesystemActionType,
    PathExtractor,
    WriteAction,
    WriteActionParser,
)


def _rnd(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits + "-", k=n))


def _rnd_payload() -> str:
    return f"{_rnd(6)}-{_rnd(4)}-{random.randint(1000,9999)}::{random.randint(100000,999999)}"


# =============================================================================
# 1. WRITE PARSER — SECOND-SENTENCE "USE THIS AS BODY" (FAIL 01)
# =============================================================================


class TestWriteParserSecondSentencePayload:
    """FAIL 01 fix: 'Make the file X. Use this as its complete body: PAYLOAD'"""

    @pytest.mark.parametrize("intro_phrase", [
        "Use this as its complete body:",
        "Use this as its exact content:",
        "Use this as its entire text:",
        "Use this as its full payload:",
        "Use this as the body:",
        "Use this as the content:",
        "Use this as its body:",
        "Use it as the body:",
        "Use the following as its content:",
        "Use this as its verbatim body:",
    ])
    def test_second_sentence_unquoted_payload(self, intro_phrase, tmp_path):
        path = str(tmp_path / "ledger.txt")
        payload = _rnd_payload()
        prompt = f'Make the file "{path}". {intro_phrase} {payload}'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None, f"Parse returned None for: {prompt!r}"
        assert result.content == payload, (
            f"Expected payload {payload!r}, got {result.content!r}\n  prompt={prompt!r}"
        )

    @pytest.mark.parametrize("verb", ["Make", "Create", "Write", "Save", "Put", "Store", "Generate"])
    def test_second_sentence_various_verbs(self, verb, tmp_path):
        path = str(tmp_path / "target.dat")
        payload = _rnd_payload()
        prompt = f'{verb} the file "{path}". Use this as its complete body: {payload}'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None
        assert result.content == payload

    def test_second_sentence_multitoken_payload(self, tmp_path):
        path = str(tmp_path / "data.txt")
        payload = "alpha-beta-1234::567890::gamma-delta-2345"
        prompt = f'Make the file "{path}". Use this as its complete body: {payload}'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None
        assert result.content == payload

    def test_500_second_sentence_variants(self, tmp_path):
        intros = [
            "Use this as its complete body:",
            "Use this as its exact content:",
            "Use this as the content:",
            "Use it as the full text:",
            "Use the following as its body:",
        ]
        verbs = ["Make", "Create", "Write", "Save", "Store"]
        failures = []
        for i in range(500):
            intro = intros[i % len(intros)]
            verb = verbs[i % len(verbs)]
            path = str(tmp_path / f"file_{i:04d}.dat")
            payload = _rnd_payload()
            prompt = f'{verb} the file "{path}". {intro} {payload}'
            r = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
            if r is None or r.content != payload:
                failures.append(f"[{i}] got={repr(r.content) if r else None} expected={repr(payload)}")
            if len(failures) >= 5:
                break
        assert not failures, "Second-sentence failures:\n" + "\n".join(failures)


# =============================================================================
# 2. WRITE PARSER — QUOTED PAYLOAD + INSTRUCTION METADATA STRIPPING (FAIL 02)
# =============================================================================


class TestWriteParserQuotedPayloadStripping:
    """FAIL 02 fix: 'Store only the quoted value "PAYLOAD" in file X'"""

    @pytest.mark.parametrize("instruction_prefix,quoted_payload", [
        ("only the quoted value", "heather-brook-3998 9402"),
        ("only the literal value", "reed-ferry-1234::567890"),
        ("only the exact value", "maple-plaza-5678::234567"),
        ("just the quoted value", "flint-stream-9999::111222"),
        ("only the verbatim value", "amber-yard-4444::333444"),
        ("solely the quoted value", "ginger-edge-7777::555666"),
        ("exactly the quoted value", "jasper-mill-2222::777888"),
        ("only the following value", "kelp-ferry-1111::999000"),
        ("only the quoted text", "denim-brook-3333::111333"),
        ("only the quoted string", "pearl-plaza-5555::222444"),
        ("only the quoted payload", "topaz-stream-9999::444666"),
        ("precisely the quoted value", "reed-heights-4444::666888"),
    ])
    def test_instruction_metadata_stripped(self, instruction_prefix, quoted_payload, tmp_path):
        path = str(tmp_path / "quoted.blob")
        prompt = f'Store {instruction_prefix} "{quoted_payload}" in file "{path}".'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None, f"Parse returned None for: {prompt!r}"
        assert result.content == quoted_payload, (
            f"Expected {quoted_payload!r}, got {result.content!r}\n  prompt={prompt!r}"
        )

    def test_quoted_payload_generative_100(self, tmp_path):
        prefixes = [
            "only the quoted value",
            "just the quoted value",
            "only the literal value",
            "only the exact value",
            "only the following value",
        ]
        failures = []
        for i in range(100):
            prefix = prefixes[i % len(prefixes)]
            payload = _rnd_payload()
            path = str(tmp_path / f"q_{i:03d}.blob")
            prompt = f'Store {prefix} "{payload}" in file "{path}".'
            r = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
            if r is None or r.content != payload:
                failures.append(f"[{i}] got={repr(r.content) if r else None} expected={repr(payload)}")
            if len(failures) >= 5:
                break
        assert not failures, "Quoted payload stripping failures:\n" + "\n".join(failures)

    def test_no_instruction_words_in_content(self, tmp_path):
        path = str(tmp_path / "check.dat")
        payload = "flint-stream-4687::409898"
        prompt = f'Store only the quoted value "{payload}" in file "{str(path)}".'
        r = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert r is not None
        assert "only" not in r.content
        assert "quoted" not in r.content
        assert r.content == payload


# =============================================================================
# 3. WRITE PARSER — MULTILINE BLOCK AFTER CONTENT INTRODUCER (FAIL 03)
# =============================================================================


class TestWriteParserMultilineBlock:
    """FAIL 03 fix: 'Create X with this exact text block:\\nLINE1\\nLINE2'"""

    @pytest.mark.parametrize("intro_phrase", [
        "with this exact text block:",
        "with this exact text body:",
        "with this exact content:",
        "with this verbatim text block:",
        "with this complete text block:",
        "with this full text block:",
        "with this exact block:",
        "with the following text block:",
        "with this exact text:",
        "containing this exact text block:",
    ])
    def test_multiline_block_various_introducers(self, intro_phrase, tmp_path):
        path = str(tmp_path / "multi.txt")
        payload = "flint-edge-1701\n22 eagle-mill-9710\nmaple-edge-1151"
        prompt = f'Create "{path}" {intro_phrase}\n{payload}'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None, f"Parse returned None for: {prompt!r}"
        assert result.content.strip() == payload.strip()

    @pytest.mark.parametrize("action_verb", ["Create", "Make", "Write", "Save", "Store"])
    def test_multiline_block_various_verbs(self, action_verb, tmp_path):
        path = str(tmp_path / "out.txt")
        payload = "line-one-1111\nline-two-2222\nline-three-3333"
        prompt = f'{action_verb} "{path}" with this exact text block:\n{payload}'
        result = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert result is not None
        assert result.content.strip() == payload.strip()

    def test_multiline_preserves_internal_newlines(self, tmp_path):
        path = str(tmp_path / "preserve.txt")
        payload = "alpha\nbeta\ngamma\ndelta"
        prompt = f'Create "{path}" with this exact text block:\n{payload}'
        r = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert r is not None
        lines = r.content.strip().split("\n")
        assert lines == ["alpha", "beta", "gamma", "delta"]

    def test_500_multiline_block_variants(self, tmp_path):
        intros = [
            "with this exact text block:",
            "with this verbatim text block:",
            "with this complete text:",
            "containing this exact block:",
            "with the following text block:",
        ]
        verbs = ["Create", "Make", "Write", "Save", "Store"]
        failures = []
        for i in range(500):
            intro = intros[i % len(intros)]
            verb = verbs[i % len(verbs)]
            path = str(tmp_path / f"mb_{i:04d}.txt")
            lines_list = [_rnd_payload() for _ in range(random.randint(2, 4))]
            payload = "\n".join(lines_list)
            prompt = f'{verb} "{path}" {intro}\n{payload}'
            r = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
            if r is None or r.content.strip() != payload:
                failures.append(f"[{i}] got={repr(r.content.strip()) if r else None} expected={repr(payload)}")
            if len(failures) >= 5:
                break
        assert not failures, "Multiline block failures:\n" + "\n".join(failures)


# =============================================================================
# 4. SCREENSHOT ROUTING — SEMANTIC DETECTION (FAIL 15)
# =============================================================================


class TestScreenshotRouting:
    """FAIL 15 fix: 'Capture the screen now and save the PNG to X'"""

    @pytest.mark.parametrize("prompt", [
        "Capture the screen now and save the PNG to /tmp/cap.png.",
        "Capture the screen and write it to /tmp/cap.png.",
        "Screen capture to /tmp/cap.png.",
        "Take a screen capture and save to /tmp/cap.png.",
        "Grab the screen now, save as /tmp/cap.png.",
        "Capture the display and write to /tmp/cap.png.",
        "Take a screenshot and save the PNG to /tmp/cap.png.",
        "screenshot of the current display save to /tmp/cap.png",
        "Snap the screen to /tmp/cap.png.",
        "Grab the display and save as /tmp/cap.png.",
        "Screen image to /tmp/cap.png.",
        "capture current display, output /tmp/cap.png",
        "save the screen to /tmp/cap.png",
        "take a screen shot and save to /tmp/cap.png",
    ])
    def test_screenshot_phrases_detected(self, prompt):
        assert DirectActionRouter._is_screenshot_request(prompt), (
            f"Expected screenshot detection for: {prompt!r}"
        )

    def test_capture_screen_not_write_PNG(self, tmp_path):
        path = str(tmp_path / "cap.png")
        prompt = f'Capture the screen now and save the PNG to "{path}".'
        assert DirectActionRouter._is_screenshot_request(prompt)
        wr = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        if wr is not None:
            assert wr.content.strip() != "PNG", (
                "WriteActionParser incorrectly extracted 'PNG' as content"
            )

    def test_100_screenshot_paraphrase_forms(self):
        screen_words = ["screen", "display", "desktop", "monitor"]
        action_words = ["capture", "grab", "snap", "save", "take"]
        failures = []
        for i in range(100):
            sw = screen_words[i % len(screen_words)]
            aw = action_words[i % len(action_words)]
            prompt = f"{aw.capitalize()} the {sw} and save to /tmp/sc_{i:03d}.png."
            if not DirectActionRouter._is_screenshot_request(prompt):
                failures.append(prompt)
            if len(failures) >= 5:
                break
        assert not failures, "Screenshot detection missed:\n" + "\n".join(failures)

    def test_100_write_prompts_not_screenshot(self, tmp_path):
        verbs = ["Write", "Create", "Save", "Store", "Put"]
        failures = []
        for i in range(100):
            verb = verbs[i % len(verbs)]
            payload = _rnd_payload()
            path = str(tmp_path / f"w_{i:03d}.dat")
            prompt = f'{verb} "{payload}" to "{path}".'
            if DirectActionRouter._is_screenshot_request(prompt):
                failures.append(prompt)
            if len(failures) >= 5:
                break
        assert not failures, "False screenshot detections:\n" + "\n".join(failures)


# =============================================================================
# 5. EXACT RESPONSE GRAMMAR — SUFFIX/PREFIX/TRAILING COMMA (FAIL 16)
# =============================================================================


class TestExactResponseGrammarPhase6:
    """FAIL 16 fix: strip suffix/prefix noise."""

    @pytest.mark.parametrize("prompt,expected", [
        ("reply with only reed-ferry-9770::305616; add nothing", "reed-ferry-9770::305616"),
        ("return amber-yard-1234::567890; add nothing", "amber-yard-1234::567890"),
        ("echo flint-stream-7777::888999; add nothing.", "flint-stream-7777::888999"),
        ("send back kelp-ferry-2222::333444, add nothing", "kelp-ferry-2222::333444"),
        ("reply with jasper-stream-7170::757266 only", "jasper-stream-7170::757266"),
        ("output cinder-plaza-5555::666777 only", "cinder-plaza-5555::666777"),
        ("send pearl-terrace-8888::999000 only", "pearl-terrace-8888::999000"),
        ("and nothing more: jasper-garden-3417::222546", "jasper-garden-3417::222546"),
        ("and nothing more: reed-brook-1220::773369", "reed-brook-1220::773369"),
        ("the following string: heather-heights-9802::686112", "heather-heights-9802::686112"),
        ("the following string: eagle-yard-6904::907536", "eagle-yard-6904::907536"),
        ("the following token: indigo-landing-8291::495667", "indigo-landing-8291::495667"),
        ("the following value: cinder-stream-3587::875230", "cinder-stream-3587::875230"),
        ("reply with maple-plaza-1284::190338,", "maple-plaza-1284::190338"),
        ("output kelp-landing-8088::892018,", "kelp-landing-8088::892018"),
        ("reply with reed-ferry-3838::542858; add nothing", "reed-ferry-3838::542858"),
    ])
    def test_suffix_prefix_stripping(self, prompt, expected):
        result = ExactResponseParser.parse(prompt)
        assert result is not None, f"Parse returned None for: {prompt!r}"
        assert result.output == expected, (
            f"Expected {expected!r}, got {result.output!r}\n  prompt={prompt!r}"
        )

    @pytest.mark.parametrize("suffix", [
        "; add nothing",
        ", add nothing",
        "; add nothing.",
        " only",
        " only.",
    ])
    def test_suffix_stripping_generative(self, suffix):
        failures = []
        for i in range(20):
            payload = _rnd_payload()
            prompt = f"reply with {payload}{suffix}"
            r = ExactResponseParser.parse(prompt)
            if r is None or r.output != payload:
                failures.append(f"suffix={suffix!r} payload={payload!r} got={r.output if r else None!r}")
        assert not failures

    @pytest.mark.parametrize("prefix", [
        "and nothing more: ",
        "the following string: ",
        "the following token: ",
        "the following value: ",
    ])
    def test_leading_modifier_prefix_generative(self, prefix):
        failures = []
        for i in range(20):
            payload = _rnd_payload()
            prompt = f"{prefix}{payload}"
            r = ExactResponseParser.parse(prompt)
            if r is None or r.output != payload:
                failures.append(f"prefix={prefix!r} payload={payload!r} got={r.output if r else None!r}")
        assert not failures

    def test_1000_exact_response_variants(self):
        command_verbs = [
            "reply with", "respond with", "return", "say", "echo", "output",
            "send", "send back", "give back", "produce", "print",
        ]
        modifier_prefixes = ["", "only ", "just ", "exactly ", "verbatim "]
        suffix_qualifiers = ["", " and nothing else", " only", "; add nothing"]
        failures = []
        for i in range(1000):
            verb = command_verbs[i % len(command_verbs)]
            prefix = modifier_prefixes[i % len(modifier_prefixes)]
            suffix = suffix_qualifiers[i % len(suffix_qualifiers)]
            payload = _rnd_payload()
            prompt = f"{verb} {prefix}{payload}{suffix}"
            r = ExactResponseParser.parse(prompt)
            if r is None or r.output != payload:
                failures.append(
                    f"[{i}] verb={verb!r} pre={prefix!r} suf={suffix!r} "
                    f"payload={payload!r} got={r.output if r else None!r}"
                )
            if len(failures) >= 10:
                break
        assert not failures, f"{len(failures)} failures:\n" + "\n".join(failures)


# =============================================================================
# 6. REPOSITORY DIAGNOSIS — WRONG HELPER CALL (FAIL 11)
# =============================================================================


class TestRepositoryDiagnosisWrongHelper:
    """FAIL 11 fix: call-graph analysis."""

    def _make_wrong_helper_repo(self, tmp_path: Path, fn_suffix: str = "12345") -> Path:
        repo = tmp_path / f"repo_helper_{fn_suffix}"
        repo.mkdir()
        (repo / "billing.py").write_text(textwrap.dedent(f"""\
            def apply_discount_{fn_suffix}(amount):
                \"\"\"Apply a discount (subtracts 10%).\"\"\"
                return amount * 0.9

            def apply_surcharge_{fn_suffix}(amount):
                \"\"\"Apply a surcharge (adds 10%).\"\"\"
                return amount * 1.1

            def final_price_{fn_suffix}(base):
                \"\"\"Calculate the final price by applying a discount.\"\"\"
                return apply_surcharge_{fn_suffix}(base)
        """))
        (repo / "test_billing.py").write_text(textwrap.dedent(f"""\
            from billing import final_price_{fn_suffix}

            def test_final_price():
                assert final_price_{fn_suffix}(100) == 90.0
        """))
        return repo

    def test_wrong_helper_diagnosis_found(self, tmp_path):
        from jarvis.amaura.direct_action import RepositoryDiagnosticEngine
        repo = self._make_wrong_helper_repo(tmp_path, fn_suffix="99001")
        result = RepositoryDiagnosticEngine.diagnose(repo)
        findings = result["findings"]
        assert len(findings) > 0
        categories = {f["category"] for f in findings}
        assert categories & {"assertionerror", "wrong_helper_call"}

    def test_read_only_verified_on_helper_repos(self, tmp_path):
        from jarvis.amaura.direct_action import RepositoryDiagnosticEngine
        repo = self._make_wrong_helper_repo(tmp_path, fn_suffix="99003")
        pre_hashes = {}
        for py_f in repo.glob("*.py"):
            pre_hashes[str(py_f)] = hashlib.sha256(py_f.read_bytes()).hexdigest()
        RepositoryDiagnosticEngine.diagnose(repo)
        for py_f in repo.glob("*.py"):
            post = hashlib.sha256(py_f.read_bytes()).hexdigest()
            assert post == pre_hashes[str(py_f)], f"File was modified: {py_f}"

    def test_10_wrong_helper_repos(self, tmp_path):
        from jarvis.amaura.direct_action import RepositoryDiagnosticEngine
        failures = []
        for i in range(10):
            repo = self._make_wrong_helper_repo(tmp_path, fn_suffix=f"{10000+i}")
            result = RepositoryDiagnosticEngine.diagnose(repo)
            if not result["findings"]:
                failures.append(f"repo_{10000+i}: no findings")
        assert not failures, "Repos with no findings:\n" + "\n".join(failures)


# =============================================================================
# 7. CONCURRENCY BURSTS (20, 40, 60, 80)
# =============================================================================


class TestConcurrencyPhase6:

    def _run_burst(self, burst_size: int):
        payloads = [_rnd_payload() for _ in range(burst_size)]
        prompts = [f"reply with {p}" for p in payloads]
        results = {}

        def _parse(idx: int):
            return idx, ExactResponseParser.parse(prompts[idx])

        with concurrent.futures.ThreadPoolExecutor(max_workers=burst_size) as exe:
            futs = {exe.submit(_parse, i): i for i in range(burst_size)}
            for fut in concurrent.futures.as_completed(futs):
                idx, r = fut.result()
                results[idx] = r

        failures = []
        for i in range(burst_size):
            r = results[i]
            if r is None or r.output != payloads[i]:
                failures.append(f"[{i}] expected={repr(payloads[i])} got={repr(r.output) if r else None}")
        return failures

    def test_burst_20(self):
        assert not self._run_burst(20)

    def test_burst_40(self):
        assert not self._run_burst(40)

    def test_burst_60(self):
        assert not self._run_burst(60)

    def test_burst_80(self):
        assert not self._run_burst(80)


# =============================================================================
# 8. FAILURE INJECTION (>= 20 distinct modes)
# =============================================================================


class TestFailureInjectionPhase6:

    @pytest.mark.parametrize("bad_prompt", [
        "",
        " ",
        "\n\n\n",
        "a" * 5000,
        "???",
        "write to",
        "create",
        "save",
        "make file",
        "put content in",
        '""',
        "''",
        "write \"\" to /tmp/empty.txt",
        "Create /tmp/f.txt: ",
        "make /tmp/x.txt with text block:\n",
    ])
    def test_write_parser_no_crash(self, bad_prompt, tmp_path):
        try:
            WriteActionParser.parse(bad_prompt, default_workspace=str(tmp_path))
        except Exception as exc:
            pytest.fail(f"WriteActionParser raised on {bad_prompt!r:.60}: {exc}")

    @pytest.mark.parametrize("bad_prompt", [
        "",
        " ",
        "hello world",
        "what is the weather",
        "navigate to http://example.com",
        "list directory /tmp",
        "write hello to /tmp/x.txt",
        "random text with no grammar",
    ])
    def test_exact_response_no_crash(self, bad_prompt):
        try:
            r = ExactResponseParser.parse(bad_prompt)
            if r is not None:
                assert hasattr(r, "output")
        except Exception as exc:
            pytest.fail(f"ExactResponseParser raised on {bad_prompt!r}: {exc}")

    @pytest.mark.parametrize("bad_prompt", [
        "",
        " ",
        "take a photo",
        "shoot the scene",
        "grab the apple",
        "save /tmp/file.png",
        "output image.png",
    ])
    def test_screenshot_no_crash(self, bad_prompt):
        try:
            DirectActionRouter._is_screenshot_request(bad_prompt)
        except Exception as exc:
            pytest.fail(f"Screenshot detector raised on {bad_prompt!r}: {exc}")
