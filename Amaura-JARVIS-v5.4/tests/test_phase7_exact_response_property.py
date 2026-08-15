"""Phase 7 Test Suite 5: Exact Response Property Testing (2,000+ Cases & 500+ Non-Literal Controls)."""

import random
import string
import pytest
from jarvis.amaura.direct_action import (
    ExactResponseParser,
    RequestPreprocessor,
    ActionType,
    ResponseMode,
)


def _random_token(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_exact_literal_cases(count: int = 2100):
    """Generate explicit-literal grammar cases with diverse prefix and suffix constraints."""
    prefixes = [
        "reply exactly",
        "only reply",
        "return only",
        "just return",
        "just say",
        "just echo",
        "echo:",
        "echo",
        "repeat:",
        "repeat",
        "give back",
        "send back",
        "strictly return",
        "verbatim return",
        "your response must be",
        "the reply should be",
        "output only",
        "the following string:",
        "and nothing more:",
    ]

    suffixes = [
        "",
        " and nothing else",
        " with nothing else",
        " with no other text",
        " with no other words",
        " without explanation",
        " without commentary",
        " verbatim",
        " strictly",
        "; add nothing",
        ", add nothing",
        " only",
    ]

    cases = []
    for i in range(count):
        payload = f"TOKEN_{_random_token(10)}_{i}"
        pfx = random.choice(prefixes)
        sfx = random.choice(suffixes)
        use_quotes = random.choice([True, False])

        formatted_payload = f'"{payload}"' if use_quotes else payload
        connector = " " if not pfx.endswith(":") else ""

        prompt = f"{pfx}{connector}{formatted_payload}{sfx}"
        cases.append((prompt, payload))
    return cases


def generate_non_literal_exact_controls(count: int = 550):
    """Generate requests requiring exact formatting on tool results (must NOT route to exact echo)."""
    cases = []

    # Category 1: Read file exactly
    for i in range(150):
        p = f"/tmp/data_{i}.txt"
        prompt = random.choice([
            f"read {p} and return exactly its contents",
            f"give me raw contents of {p}",
            f"cat {p} verbatim without line numbers",
            f"whole reply must be file text of {p}",
        ])
        cases.append((prompt, ActionType.FILE_READ, ResponseMode.EXACT_RAW))

    # Category 2: Arithmetic workflow exact result
    for i in range(150):
        p1 = f"/tmp/in_a_{i}.num"
        p2 = f"/tmp/in_b_{i}.num"
        p_out = f"/tmp/out_{i}.num"
        prompt = f"take the number in {p1} away from {p2} and save only numeric result into {p_out}"
        cases.append((prompt, ActionType.STRUCTURED_WORKFLOW, ResponseMode.NORMAL))

    # Category 3: Browser extraction exact result
    for i in range(130):
        url = f"https://example_{i}.com/page"
        prompt = f"extract content from {url} and return only the text"
        cases.append((prompt, ActionType.BROWSER_ACTION, ResponseMode.NORMAL))

    # Category 4: Memory recall exact result
    for i in range(120):
        prompt = f"what was the value of secret_key_{i}? Give only the value without commentary"
        cases.append((prompt, ActionType.MEMORY_ACTION, ResponseMode.NORMAL))

    return cases[:count]


def test_exact_literal_generated_2000_cases():
    """Verify >= 2,000 explicit-literal grammar cases extract exact payload with zero leakage."""
    cases = generate_exact_literal_cases(2100)
    assert len(cases) >= 2000

    success_count = 0
    for prompt, expected_payload in cases:
        res = ExactResponseParser.parse(prompt)
        assert res is not None, f"Failed exact echo parse for: {prompt}"
        assert res.success is True
        assert res.output == expected_payload, f"Payload mismatch: got {repr(res.output)} vs {repr(expected_payload)} in {prompt}"
        success_count += 1

    assert success_count >= 2000


def test_non_literal_exact_controls_500_cases():
    """Verify >= 500 non-literal exact-format controls do NOT route to exact-literal echo."""
    controls = generate_non_literal_exact_controls(550)
    assert len(controls) >= 500

    non_echo_count = 0
    for prompt, expected_action, expected_mode in controls:
        # 1. ExactResponseParser MUST return None
        echo_res = ExactResponseParser.parse(prompt)
        assert echo_res is None, f"Non-literal control incorrectly captured by exact echo fast path: {prompt}"

        # 2. RequestPreprocessor must identify correct underlying action
        parsed = RequestPreprocessor.process(prompt)
        assert parsed.primary_action is not None, f"No action parsed for: {prompt}"
        assert parsed.primary_action.action_type == expected_action, f"Wrong action for {prompt}: got {parsed.primary_action.action_type} vs {expected_action}"

        non_echo_count += 1

    assert non_echo_count >= 500
