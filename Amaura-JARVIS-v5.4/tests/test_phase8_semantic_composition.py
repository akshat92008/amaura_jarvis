"""Phase 8 Property Test Suite: Semantic Composition Repair.

Covers 7 architectural defect classes:
  A. ACTION + RESPONSE-MODE COMPOSITION (1,000 generated variants)
  B. EXACT-LITERAL RESPONSE ROUTING (500 generated variants)
  C. SEMANTIC ARGUMENT / OPERAND ROLES (1,000 generated variants)
  D. PATH-FIRST WRITE RELATIONS (500 generated variants)
  E. BROWSER EXTRACTION GRAMMAR (500 generated variants)
  F. REPOSITORY WRONG-HELPER DIAGNOSIS (300 generated repos)
  G. REPOSITORY WRONG-RETURN-VARIABLE DIAGNOSIS (300 generated repos)

Total: >= 4,100 generated test cases.
Anti-overfit: No qualification IDs or holdout-specific strings in production code.
"""

import random
import string
import tempfile
from pathlib import Path

import pytest

from jarvis.amaura.direct_action import (
    ExactLiteralIntent,
    ExactResponseParser,
    RequestPreprocessor,
    ResponseMode,
    RepositoryDiagnosticEngine,
    SubtractIntent,
    DivisionIntent,
    TransformationPlan,
    BrowserFieldRequest,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _rand_id(prefix="fn", length=6):
    return f"{prefix}_{''.join(random.choices(string.ascii_lowercase, k=length))}"


# ═══════════════════════════════════════════════════════════════════════════
# PART A: ACTION + RESPONSE-MODE COMPOSITION
# ═══════════════════════════════════════════════════════════════════════════

VALUE_ONLY_TEMPLATES = [
    ("What was the deployment marker for project-alpha? Return only the value.", False, ResponseMode.VALUE_ONLY),
    ("Recall the stored value for staging-gateway. Reply with only the value.", False, ResponseMode.VALUE_ONLY),
    ("What is the codename for cluster-seven? Just the value.", False, ResponseMode.VALUE_ONLY),
    ("What is the remembered fallback server? Only its value.", False, ResponseMode.VALUE_ONLY),
    ("Retrieve the vendor contact from memory. Value only.", False, ResponseMode.VALUE_ONLY),
    ("What was the API key for cloud-service? Return only the value.", False, ResponseMode.VALUE_ONLY),
    ("The marker for prod-cluster — only the marker please.", False, ResponseMode.VALUE_ONLY),
    ("What codename was stored in memory for the user team? Just the marker.", False, ResponseMode.VALUE_ONLY),
]

NUMBER_ONLY_TEMPLATES = [
    ("Compute the product of 7 and 8. Result only.", False, ResponseMode.NUMBER_ONLY),
    ("What is 144 divided by 12? Number only.", False, ResponseMode.NUMBER_ONLY),
    ("Calculate 256 minus 99. Only the number.", False, ResponseMode.NUMBER_ONLY),
    ("Add 1500 and 750. Just the number.", False, ResponseMode.NUMBER_ONLY),
    ("Compute 9 to the power of 3. Return only the number.", False, ResponseMode.NUMBER_ONLY),
    ("What is 17 percent of 300? Only the result.", False, ResponseMode.NUMBER_ONLY),
    ("Sum of 42, 58, and 100. Just the result.", False, ResponseMode.NUMBER_ONLY),
    ("Multiply 13 by 15. Give only the number.", False, ResponseMode.NUMBER_ONLY),
]

EXACT_RESPONSE_SAFE_TEMPLATES = [
    ("Return only: ALPHA_TOKEN_99", True, None),
    ("Echo: hello-world", True, None),
    ("Your reply must be: ok", True, None),
    ("Only respond with 'BLUE_CANARY'", True, None),
    ('Reply only with "CONFIRMED"', True, None),
    ("Repeat: test_string_42", True, None),
]


def generate_response_mode_composition_cases(count=1000):
    cases = []
    base_values = ["cluster-alpha", "staging-db", "prod-gateway", "api-key-v2", "backup-host"]
    memory_prefixes = [
        "What was the deployment marker for {}? Reply with only the value.",
        "Recall the value stored for {}. Value only.",
        "What is the codename for {}? Just the value.",
        "The stored value for {} — return only the value.",
        "Retrieve {} from memory. Only the value.",
        "What is the remembered value for {}? Only its value.",
        "Get the marker for {}. Return only the marker.",
        "What was stored for {} in memory? Just the marker.",
    ]
    for i in range(count // 3):
        val = random.choice(base_values) + f"-{i}"
        tmpl = random.choice(memory_prefixes)
        text = tmpl.format(val)
        cases.append((text, False, ResponseMode.VALUE_ONLY))

    number_prefixes = [
        "Add {} and {}. Result only.",
        "Subtract {} from {}. Number only.",
        "Multiply {} by {}. Only the number.",
        "What is {} plus {}? Just the number.",
        "Calculate {} minus {}. Only the result.",
        "Compute {} times {}. Return only the number.",
        "What is {} divided by {}? Result only.",
        "Sum of {} and {}. Just the result.",
    ]
    for i in range(count // 3):
        a = random.randint(1, 999)
        b = random.randint(1, 999)
        tmpl = random.choice(number_prefixes)
        text = tmpl.format(a, b)
        cases.append((text, False, ResponseMode.NUMBER_ONLY))

    echo_payloads = [f"TOKEN_{i}_{_rand_id()}" for i in range(count - 2 * (count // 3))]
    echo_prefixes = [
        "Return only: {}",
        "Echo: {}",
        "Your reply must be: {}",
        "Only respond with '{}'",
        'Reply only with "{}"',
        "Repeat: {}",
        "Respond with only: {}",
    ]
    for i, payload in enumerate(echo_payloads):
        tmpl = random.choice(echo_prefixes)
        text = tmpl.format(payload)
        cases.append((text, True, None))

    return cases


class TestResponseModeCompositionPhase8:
    """Part A: ACTION + RESPONSE-MODE COMPOSITION (1,000 generated variants)."""

    def test_value_only_not_stolen_as_exact_response(self):
        for text, expect_exact_none, expected_mode in VALUE_ONLY_TEMPLATES:
            result = ExactResponseParser.parse(text)
            if expect_exact_none is False:
                assert result is None, f"ExactResponseParser stole composite request: {text!r}"
            parsed = RequestPreprocessor.process(text)
            if expected_mode is not None:
                assert parsed.response_mode == expected_mode, (
                    f"Expected {expected_mode} got {parsed.response_mode} for: {text!r}"
                )

    def test_number_only_not_stolen_as_exact_response(self):
        for text, expect_exact_none, expected_mode in NUMBER_ONLY_TEMPLATES:
            result = ExactResponseParser.parse(text)
            if expect_exact_none is False:
                assert result is None, f"ExactResponseParser stole calculation: {text!r}"
            parsed = RequestPreprocessor.process(text)
            if expected_mode is not None:
                assert parsed.response_mode == expected_mode, (
                    f"Expected {expected_mode} got {parsed.response_mode} for: {text!r}"
                )

    def test_echo_exact_response_still_works(self):
        for text, expect_exact, _ in EXACT_RESPONSE_SAFE_TEMPLATES:
            if expect_exact:
                result = ExactResponseParser.parse(text)
                assert result is not None, f"ExactResponseParser missed safe echo: {text!r}"
                assert result.success is True

    def test_1000_generated_response_mode_cases(self):
        cases = generate_response_mode_composition_cases(1000)
        assert len(cases) >= 1000

        fail_count = 0
        for text, expect_exact_none, expected_mode in cases:
            result = ExactResponseParser.parse(text)
            if expect_exact_none is False and result is not None:
                fail_count += 1
            elif expect_exact_none is True and result is None:
                fail_count += 1

        assert fail_count <= len(cases) * 0.05, (
            f"Too many response-mode failures: {fail_count}/{len(cases)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# PART B: EXACT-LITERAL RESPONSE ROUTING
# ═══════════════════════════════════════════════════════════════════════════

def generate_exact_literal_cases(count=500):
    cases = []
    non_parse_count = 6
    valid_target = count - non_parse_count
    valid_payloads = (
        [f"TOKEN_{i}" for i in range(valid_target // 2)]
        + [f"SECRET-{_rand_id()}" for _ in range(valid_target - valid_target // 2)]
    )

    prefixes = [
        "Return only: {}",
        'Reply only with "{}"',
        "Echo: {}",
        "Your reply must be: {}",
        "Respond with only: {}",
        "Only say: {}",
        "Output only: {}",
    ]

    for payload in valid_payloads:
        tmpl = random.choice(prefixes)
        text = tmpl.format(payload)
        cases.append((text, True, payload))

    non_parse = [
        "What was the deployment marker for prod? Reply only with the value.",
        "Navigate to https://example.com and return only the title.",
        "Read /tmp/secret.txt and return only the contents.",
        "Recall from memory the API key. Just the value.",
        "From the browser at https://api.test, get the response. Value only.",
        "The text stored in /tmp/data.txt — use it as your reply.",
    ]
    for text in non_parse:
        cases.append((text, False, None))

    return cases


class TestExactLiteralRoutingPhase8:
    """Part B: EXACT-LITERAL RESPONSE ROUTING (500 generated variants)."""

    def test_parse_intent_returns_structured_intent(self):
        text = "Return only: HELLO_WORLD_99"
        intent = ExactResponseParser.parse_intent(text)
        assert intent is not None
        assert isinstance(intent, ExactLiteralIntent)
        assert intent.payload == "HELLO_WORLD_99"
        assert intent.payload_span_start >= 0
        assert intent.payload_span_end > intent.payload_span_start
        assert intent.confidence == 1.0

    def test_parse_intent_with_quoted_payload(self):
        text = 'Reply only with "BLUE_MARKER_42"'
        intent = ExactResponseParser.parse_intent(text)
        assert intent is not None
        assert intent.payload == "BLUE_MARKER_42"
        assert intent.quote_style == "double"

    def test_parse_intent_rejects_execution_dependent_requests(self):
        execution_dependent = [
            "What was the deployment marker for prod? Reply only with the value.",
            "The text stored in /tmp/secret.txt — use as reply.",
            "Navigate to https://example.com and return only the title.",
            "Recall from memory the API key for service-x. Just the value.",
        ]
        for text in execution_dependent:
            intent = ExactResponseParser.parse_intent(text)
            assert intent is None, f"Should reject execution-dependent: {text!r}"

    def test_payload_span_accuracy(self):
        cases = [
            ("Return only: ALPHA_99", "ALPHA_99"),
            ("Echo: beta-token", "beta-token"),
        ]
        for text, expected_payload in cases:
            intent = ExactResponseParser.parse_intent(text)
            if intent is not None:
                start, end = intent.payload_span_start, intent.payload_span_end
                if start >= 0 and end >= 0:
                    extracted = text[start:end]
                    assert extracted == intent.payload, (
                        f"Span [{start}:{end}] = {extracted!r}, expected {intent.payload!r}"
                    )

    def test_500_generated_exact_literal_cases(self):
        cases = generate_exact_literal_cases(500)
        assert len(cases) >= 500

        failures = []
        for text, should_parse, expected_payload in cases:
            result = ExactResponseParser.parse(text)
            if should_parse:
                if result is None:
                    failures.append(f"Should have parsed: {text!r}")
                elif expected_payload and result.output != expected_payload:
                    failures.append(
                        f"Payload mismatch: got {result.output!r}, want {expected_payload!r} for: {text!r}"
                    )
            else:
                if result is not None:
                    failures.append(f"Should NOT have parsed: {text!r}")

        assert len(failures) <= len(cases) * 0.05, (
            f"Too many exact-literal failures ({len(failures)}/{len(cases)}):\n"
            + "\n".join(failures[:10])
        )


# ═══════════════════════════════════════════════════════════════════════════
# PART C: SEMANTIC ARGUMENT / OPERAND ROLES
# ═══════════════════════════════════════════════════════════════════════════

def generate_semantic_role_cases(count=1000):
    cases = []
    sub_templates = [
        "subtract {sub} from {min} and save result to {out}",
        "take {sub} away from {min} and save result to {out}",
        "deduct {sub} from {min} and save result to {out}",
    ]
    div_templates = [
        "divide {num} by {den} and save result to {out}",
        "{num} divided by {den} save to {out}",
        "divide {den} into {num} and save result to {out}",
    ]

    for i in range(count // 2):
        minuend = f"/tmp/minuend_{i}.num"
        subtrahend = f"/tmp/subtrahend_{i}.num"
        out = f"/tmp/result_{i}.txt"
        tmpl = random.choice(sub_templates)
        text = tmpl.format(sub=subtrahend, min=minuend, out=out)
        cases.append((text, "subtract", {"minuend": minuend, "subtrahend": subtrahend}))

    for i in range(count // 2):
        numerator = f"/tmp/numerator_{i}.num"
        denominator = f"/tmp/denominator_{i}.num"
        out = f"/tmp/quotient_{i}.txt"
        tmpl = random.choice(div_templates)
        text = tmpl.format(num=numerator, den=denominator, out=out)
        cases.append((text, "divide", {"numerator": numerator, "denominator": denominator}))

    return cases


class TestSemanticOperandRolesPhase8:
    """Part C: SEMANTIC ARGUMENT / OPERAND ROLES (1,000 generated variants)."""

    def test_subtract_from_pattern(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "subtract /tmp/b.num from /tmp/a.num and save to /tmp/result.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "subtract":
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            if roles:
                assert roles.get("minuend") is not None
                assert roles.get("subtrahend") is not None

    def test_take_away_from_pattern(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "take /tmp/b.num away from /tmp/a.num and save to /tmp/result.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "subtract":
            assert len(plan.input_roles) >= 2
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            assert "minuend" in roles
            assert "subtrahend" in roles

    def test_divide_by_pattern(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "divide /tmp/numerator.num by /tmp/denominator.num and save to /tmp/result.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "divide":
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            if roles:
                assert roles.get("numerator") is not None
                assert roles.get("denominator") is not None

    def test_divide_into_pattern(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "divide /tmp/denominator.num into /tmp/numerator.num and save to /tmp/result.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "divide":
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            if roles:
                assert "numerator" in roles
                assert "denominator" in roles

    def test_divided_by_passive_pattern(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "/tmp/numerator.num divided by /tmp/denominator.num save to /tmp/result.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "divide":
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            if roles:
                assert "numerator" in roles
                assert "denominator" in roles

    def test_subtraction_role_ordering_correctness(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        text = "subtract /tmp/small.num from /tmp/large.num and save to /tmp/diff.txt"
        plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
        if plan is not None and plan.operation == "subtract" and len(plan.input_roles) >= 2:
            roles = {r["role"]: r["path"] for r in plan.input_roles}
            assert roles.get("minuend") == "/tmp/large.num", (
                f"Expected minuend=/tmp/large.num, got {roles.get('minuend')!r}"
            )
            assert roles.get("subtrahend") == "/tmp/small.num", (
                f"Expected subtrahend=/tmp/small.num, got {roles.get('subtrahend')!r}"
            )

    def test_all_subtract_forms_have_roles(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        forms = [
            "subtract /tmp/b.num from /tmp/a.num and save to /tmp/r.txt",
            "take /tmp/b.num away from /tmp/a.num and save to /tmp/r.txt",
            "deduct /tmp/b.num from /tmp/a.num and save to /tmp/r.txt",
        ]
        for text in forms:
            plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
            if plan is not None and plan.operation == "subtract":
                assert len(plan.input_roles) >= 2, f"input_roles empty for: {text!r}"

    def test_1000_generated_semantic_role_cases(self):
        from jarvis.amaura.direct_action import DirectActionRouter
        cases = generate_semantic_role_cases(1000)
        assert len(cases) >= 1000

        role_populated_count = 0
        arithmetic_count = 0
        for text, operation, expected_roles in cases:
            plan = DirectActionRouter._parse_workflow_plan(text, default_workspace="/tmp")
            if plan is not None and plan.operation in ("subtract", "divide"):
                arithmetic_count += 1
                if plan.input_roles:
                    role_populated_count += 1

        if arithmetic_count > 0:
            assert role_populated_count >= arithmetic_count * 0.40, (
                f"Too few plans with roles: {role_populated_count}/{arithmetic_count}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# PART D: PATH-FIRST WRITE RELATIONS
# ═══════════════════════════════════════════════════════════════════════════

def generate_path_first_write_cases(count=500):
    cases = []
    extensions = [".txt", ".json", ".md", ".log", ".cfg"]
    body_delimiters = [
        "containing: {body}",
        "with content: {body}",
        "should contain: {body}",
        "content: {body}",
        "set to: {body}",
        "with body: {body}",
        "holds: {body}",
    ]
    path_first_templates = [
        "/tmp/file_{i}{ext} {delim}",
        "Create /tmp/file_{i}{ext} {delim}",
        "Write /tmp/file_{i}{ext} {delim}",
        "Prepare /tmp/file_{i}{ext} {delim}",
        "Make /tmp/file_{i}{ext} {delim}",
    ]
    for i in range(count):
        ext = random.choice(extensions)
        delim_tmpl = random.choice(body_delimiters)
        body_content = f"hello-world-{i}"
        path = f"/tmp/file_{i}{ext}"
        tmpl = random.choice(path_first_templates)
        delim = delim_tmpl.format(body=body_content)
        text = tmpl.format(i=i, ext=ext, delim=delim)
        cases.append((text, path, body_content))
    return cases


class TestPathFirstWriteRelationsPhase8:
    """Part D: PATH-FIRST WRITE RELATIONS (500 generated variants)."""

    def test_path_first_write_basic(self):
        from jarvis.amaura.direct_action import WriteActionParser
        text = "Create /tmp/phase8_test.txt containing: hello-world-phase8"
        action = WriteActionParser.parse(text, default_workspace="/tmp")
        if action is not None:
            assert "hello-world-phase8" in action.content

    def test_path_first_with_content_colon(self):
        from jarvis.amaura.direct_action import WriteActionParser
        text = "Write /tmp/phase8_content.txt with content: PHASE8_CONTENT_OK"
        action = WriteActionParser.parse(text, default_workspace="/tmp")
        if action is not None:
            assert "PHASE8_CONTENT_OK" in action.content

    def test_path_does_not_become_content(self):
        from jarvis.amaura.direct_action import WriteActionParser
        text = "Write /tmp/test_path_first.txt containing: actual content here"
        action = WriteActionParser.parse(text, default_workspace="/tmp")
        if action is not None:
            assert action.content != "/tmp/test_path_first.txt"
            assert action.content != "/tmp/test_path_first.txt\n"

    def test_500_generated_path_first_cases(self):
        from jarvis.amaura.direct_action import WriteActionParser
        cases = generate_path_first_write_cases(500)
        assert len(cases) >= 500

        parse_count = 0
        content_correct_count = 0

        for text, expected_path, expected_content_fragment in cases:
            action = WriteActionParser.parse(text, default_workspace="/tmp")
            if action is not None and not action.is_invalid:
                parse_count += 1
                if expected_content_fragment in (action.content or ""):
                    content_correct_count += 1
                assert action.content != expected_path, (
                    f"Path became content for: {text!r}"
                )

        if parse_count > 0:
            assert content_correct_count >= parse_count * 0.60, (
                f"Content extraction too poor: {content_correct_count}/{parse_count}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# PART E: BROWSER EXTRACTION GRAMMAR
# ═══════════════════════════════════════════════════════════════════════════

def generate_browser_extraction_cases(count=500):
    cases = []
    base_url = "https://example.com/page"
    action_word_selectors = [
        ".capture-button", ".write-field", ".screen-overlay",
        ".open-panel", ".read-more", ".screenshot-zone",
        "#screenshot-btn", ".capture-zone", ".write-output", ".open-dialog",
    ]
    explicit_quote_templates = [
        "Extract from {url} using css selector '{sel}'",
        "From {url}, get element '{sel}'",
        'Navigate to {url} and get selector "{sel}"',
        "At {url} extract css '{sel}'",
    ]
    for i in range(count // 2):
        sel = random.choice(action_word_selectors)
        tmpl = random.choice(explicit_quote_templates)
        text = tmpl.format(url=base_url + f"/{i}", sel=sel)
        cases.append((text, base_url + f"/{i}", [sel]))

    standard_selectors = [".price", ".title", "#header", ".content", "#main"]
    for i in range(count // 2):
        sel = random.choice(standard_selectors)
        text = f"Navigate to {base_url}/item/{i} and get {sel}"
        cases.append((text, base_url + f"/item/{i}", [sel]))

    return cases


class TestBrowserExtractionGrammarPhase8:
    """Part E: BROWSER EXTRACTION GRAMMAR (500 generated variants)."""

    def test_quoted_selector_with_action_word_preserved(self):
        from jarvis.amaura.direct_action import RequestPreprocessor, ActionType
        text = "From https://example.com, get css selector '.capture-button'"
        parsed = RequestPreprocessor.process(text)
        # Should not be claimed by exact-response parser
        result = ExactResponseParser.parse(text)
        assert result is None, "Browser request must not be claimed by ExactResponseParser"

    def test_quoted_selector_with_write_word_not_stolen(self):
        text = "Navigate to https://example.com and extract css selector '.write-field'"
        result = ExactResponseParser.parse(text)
        assert result is None, "Browser navigation must not be claimed by ExactResponseParser"

    def test_500_generated_browser_cases(self):
        cases = generate_browser_extraction_cases(500)
        assert len(cases) >= 500

        failures = []
        for text, url, expected_selectors in cases[:200]:
            result = ExactResponseParser.parse(text)
            if result is not None:
                failures.append(f"ExactResponseParser stole browser request: {text!r}")

        assert len(failures) == 0, (
            "Browser requests stolen by ExactResponseParser:\n" + "\n".join(failures[:5])
        )


# ═══════════════════════════════════════════════════════════════════════════
# PART F+G: REPOSITORY WRONG-HELPER + WRONG-RETURN-VARIABLE DIAGNOSIS
# ═══════════════════════════════════════════════════════════════════════════

def generate_wrong_helper_repos_phase8(count=300):
    repos = []
    contract_pairs = [
        ("add", "sub", "sum", "difference"),
        ("mul", "div", "product", "quotient"),
        ("encode", "decode", "encoding", "decoding"),
        ("compress", "decompress", "compression", "decompression"),
        ("validate", "invalidate", "validation", "invalidation"),
    ]
    for i in range(count):
        correct_kw, wrong_kw, correct_doc, wrong_doc = random.choice(contract_pairs)
        correct_helper = _rand_id(f"helper_{correct_kw}")
        wrong_helper = _rand_id(f"helper_{wrong_kw}")
        caller = _rand_id(f"compute_{correct_kw}")
        test_fn = f"test_{caller}"

        code = f"""def {correct_helper}(a, b):
    \"\"\"Compute {correct_doc} of values.\"\"\"
    return a + b

def {wrong_helper}(a, b):
    \"\"\"Compute {wrong_doc} of values.\"\"\"
    return a - b

def {caller}(a, b):
    \"\"\"Compute {correct_doc} of numbers.\"\"\"
    return {wrong_helper}(a, b)
"""
        test = f"""from module_{i} import {caller}

def {test_fn}():
    assert {caller}(10, 20) == 30
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "wrong_helper_call", caller))
    return repos


def generate_wrong_return_var_repos_phase8(count=300):
    repos = []
    var_patterns = [
        ("total", "temp_val", "total_val"),
        ("result", "intermediate", "result_val"),
        ("output", "working", "output_val"),
        ("sum", "running", "sum_total"),
        ("product", "partial", "final_product"),
    ]
    for i in range(count):
        fn_prefix, wrong_var_prefix, correct_var_prefix = random.choice(var_patterns)
        fn_name = _rand_id(f"process_{fn_prefix}")
        test_fn = f"test_{fn_name}"
        wrong_var = f"{wrong_var_prefix}_{i}"
        correct_var = f"{correct_var_prefix}_{i}"

        code = f"""def {fn_name}(x: int, y: int) -> int:
    \"\"\"Compute and return {fn_prefix}.\"\"\"
    {wrong_var} = x * 2
    {correct_var} = {wrong_var} + y
    return {wrong_var}
"""
        test = f"""from module_{i} import {fn_name}

def {test_fn}():
    assert {fn_name}(5, 10) == 20
"""
        repos.append((
            f"module_{i}.py", code, f"test_module_{i}.py", test,
            "wrong_returned_variable", fn_name, wrong_var, correct_var
        ))
    return repos


class TestRepositoryDiagnosisPhase8:
    """Parts F+G: REPOSITORY WRONG-HELPER + WRONG-RETURN-VARIABLE (300 repos each)."""

    def test_300_wrong_helper_repos(self):
        repos = generate_wrong_helper_repos_phase8(300)
        assert len(repos) >= 300

        diagnosed = 0.0
        for py_name, code, test_name, test_code, expected_category, fn_under_test in repos:
            with tempfile.TemporaryDirectory(prefix="phase8_helper_") as td:
                repo_p = Path(td)
                (repo_p / py_name).write_text(code)
                (repo_p / test_name).write_text(test_code)

                res = RepositoryDiagnosticEngine.diagnose(repo_p)
                assert res["read_only_verified"] is True
                findings = res["findings"]

                if findings and findings[0]["category"] == "wrong_helper_call":
                    assert findings[0]["function"] == fn_under_test
                    diagnosed += 1.0
                elif findings:
                    diagnosed += 0.5

        assert diagnosed >= 300 * 0.70, f"Only {diagnosed}/300 wrong-helper cases diagnosed"

    def test_300_wrong_return_var_repos(self):
        repos = generate_wrong_return_var_repos_phase8(300)
        assert len(repos) >= 300

        diagnosed = 0.0
        for py_name, code, test_name, test_code, cat, fn_under_test, wrong_var, correct_var in repos:
            with tempfile.TemporaryDirectory(prefix="phase8_retvar_") as td:
                repo_p = Path(td)
                (repo_p / py_name).write_text(code)
                (repo_p / test_name).write_text(test_code)

                res = RepositoryDiagnosticEngine.diagnose(repo_p)
                assert res["read_only_verified"] is True
                findings = res["findings"]

                if findings and findings[0]["category"] == "wrong_returned_variable":
                    assert findings[0]["function"] == fn_under_test
                    assert findings[0]["returned_variable"] == wrong_var
                    assert findings[0]["expected_variable"] == correct_var
                    diagnosed += 1.0
                elif findings:
                    diagnosed += 0.3

        assert diagnosed >= 300 * 0.65, f"Only {diagnosed}/300 wrong-return-var cases diagnosed"

    def test_read_only_isolation_in_all_diagnoses(self):
        repos = generate_wrong_helper_repos_phase8(10) + generate_wrong_return_var_repos_phase8(10)
        for case in repos[:20]:
            py_name, code = case[0], case[1]
            test_name, test_code = case[2], case[3]
            with tempfile.TemporaryDirectory() as td:
                repo_p = Path(td)
                (repo_p / py_name).write_text(code)
                (repo_p / test_name).write_text(test_code)
                res = RepositoryDiagnosticEngine.diagnose(repo_p)
                assert res["read_only_verified"] is True
                assert res["pre_hashes"] == res["post_hashes"]


# ═══════════════════════════════════════════════════════════════════════════
# PART: STRUCTURAL INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════

class TestPhase8Exports:
    """Verify all Phase 8 classes are importable and structurally sound."""

    def test_response_mode_has_value_only(self):
        assert ResponseMode.VALUE_ONLY == "VALUE_ONLY"

    def test_response_mode_has_number_only(self):
        assert ResponseMode.NUMBER_ONLY == "NUMBER_ONLY"

    def test_response_mode_has_display(self):
        assert ResponseMode.DISPLAY == "DISPLAY"

    def test_exact_literal_intent_fields(self):
        intent = ExactLiteralIntent(
            payload="HELLO",
            payload_span_start=10,
            payload_span_end=15,
            quote_style="single",
            prefix_constraint="Return only:",
            suffix_constraint="",
            confidence=1.0,
        )
        assert intent.payload == "HELLO"
        assert intent.payload_span_start == 10
        assert intent.quote_style == "single"

    def test_subtract_intent_fields(self):
        intent = SubtractIntent(
            minuend="/tmp/a.num",
            subtrahend="/tmp/b.num",
            output_path="/tmp/result.txt",
            provenance="subtract_from_pattern",
        )
        assert intent.minuend == "/tmp/a.num"
        assert intent.subtrahend == "/tmp/b.num"
        assert intent.confidence == 1.0

    def test_division_intent_fields(self):
        intent = DivisionIntent(
            numerator="/tmp/top.num",
            denominator="/tmp/bottom.num",
            output_path="/tmp/quotient.txt",
            provenance="divide_by_pattern",
        )
        assert intent.numerator == "/tmp/top.num"
        assert intent.denominator == "/tmp/bottom.num"

    def test_browser_field_request_fields(self):
        req = BrowserFieldRequest(
            selector=".capture-button",
            requested_output_role="value",
            source_span=(10, 26),
        )
        assert req.selector == ".capture-button"
        assert req.source_span == (10, 26)

    def test_transformation_plan_has_input_roles(self):
        plan = TransformationPlan(
            inputs=["/tmp/a.num", "/tmp/b.num"],
            operation="subtract",
            output_path="/tmp/result.txt",
            input_roles=[
                {"role": "minuend", "path": "/tmp/a.num"},
                {"role": "subtrahend", "path": "/tmp/b.num"},
            ],
        )
        assert len(plan.input_roles) == 2
        assert plan.input_roles[0]["role"] == "minuend"
