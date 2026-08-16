"""Phase 7 Test Suite 2: General Router Property Testing (1,000+ Action Routing Cases)."""

import random

from jarvis.amaura.direct_action import (
    ActionType,
    DirectActionRouter,
    RequestPreprocessor,
    ResponseMode,
)

MISLEADING_PATH_COMPONENTS = [
    "Desktop",
    "screen",
    "browser",
    "memory",
    "repo",
    "image",
    "video",
    "write",
    "read",
    "screenshot_data",
]

MISLEADING_QUOTED_TOKENS = [
    "screenshot",
    "delete",
    "browser",
    "memory",
    "capture",
    "open",
    "write",
    "read",
    "take screenshot",
]

FILE_EXTENSIONS = [".txt", ".json", ".py", ".md", ".csv", ".num", ".log", ".dat"]


def _random_path(misleading: str | None = None) -> str:
    parts = [
        "Users",
        "operator",
        misleading or random.choice(MISLEADING_PATH_COMPONENTS),
        f"file_{random.randint(100, 999)}",
    ]
    ext = random.choice(FILE_EXTENSIONS)
    return "/" + "/".join(parts) + ext


def generate_action_cases(count: int = 1200):
    """Generate randomized action classification cases with misleading non-intent tokens."""
    cases = []

    for i in range(count):
        cat = i % 5

        # Category 0: Write action with misleading quoted literal or path
        if cat == 0:
            target_path = _random_path(misleading=random.choice(MISLEADING_PATH_COMPONENTS))
            quoted_text = random.choice(MISLEADING_QUOTED_TOKENS)
            pattern = random.choice(
                [
                    f'write "{quoted_text}" to {target_path}',
                    f'create file {target_path} containing "{quoted_text}"',
                    f'save the text "{quoted_text}" in {target_path}',
                    f'Put "{quoted_text}" into {target_path}',
                    f'At {target_path}, store "{quoted_text}"',
                ]
            )
            cases.append((pattern, ActionType.FILE_WRITE, "write"))

        # Category 1: Structured Workflow (arithmetic) with paths containing 'Desktop'/'take'
        elif cat == 1:
            p1 = _random_path(misleading="Desktop")
            p2 = _random_path(misleading="screen")
            p_out = _random_path(misleading="result")
            pattern = random.choice(
                [
                    f"take the number in {p1} away from {p2} and save to {p_out}",
                    f"read {p1} and {p2}, compute difference and save into {p_out}",
                    f"calculate sum of {p1} and {p2} and store in {p_out}",
                    f"add {p1} and {p2} and output to {p_out}",
                    f"multiply {p1} by {p2} and write to {p_out}",
                ]
            )
            cases.append((pattern, ActionType.STRUCTURED_WORKFLOW, "workflow"))

        # Category 2: File Read with format constraints
        elif cat == 2:
            p_read = _random_path(misleading=random.choice(MISLEADING_PATH_COMPONENTS))
            is_exact = random.choice([True, False])
            if is_exact:
                pattern = random.choice(
                    [
                        f"read {p_read} and return exactly its contents",
                        f"give me raw contents of {p_read}",
                        f"cat {p_read} verbatim without line numbers",
                        f"whole reply must be file text of {p_read}",
                    ]
                )
            else:
                pattern = random.choice(
                    [
                        f"read file {p_read}",
                        f"cat {p_read}",
                        f"show content of {p_read}",
                        f"open and display {p_read}",
                    ]
                )
            cases.append((pattern, ActionType.FILE_READ, "read_exact" if is_exact else "read_normal"))

        # Category 3: Screenshot Positive Command
        elif cat == 3:
            p_shot = f"/tmp/screenshot_{random.randint(1000, 9999)}.png"
            pattern = random.choice(
                [
                    f"take a screenshot and save it to {p_shot}",
                    f"capture the screen to {p_shot}",
                    f"grab the display and store in {p_shot}",
                    f"snap the desktop to {p_shot}",
                    f"capture current display and save {p_shot}",
                ]
            )
            cases.append((pattern, ActionType.SCREENSHOT_CAPTURE, "screenshot"))

        # Category 4: Negated Actions (must NOT execute)
        elif cat == 4:
            p_any = _random_path()
            pattern = random.choice(
                [
                    "do not take a screenshot",
                    "don't capture the screen",
                    "never take screenshots",
                    f"read {p_any}; without taking any screenshot",
                    f'write "screenshot" to {p_any}; do not capture screen',
                ]
            )
            cases.append((pattern, None, "negated_or_non_screenshot"))

    return cases


def test_action_classification_property_1000_cases():
    """Verify >= 1,000 randomized action routing cases remain robust against misleading tokens."""
    cases = generate_action_cases(1200)
    assert len(cases) >= 1000

    wrong_action_count = 0
    passed_count = 0

    for prompt, _expected_action, category in cases:
        parsed = RequestPreprocessor.process(prompt)
        primary_action = parsed.primary_action.action_type if parsed.primary_action else None

        if category == "write":
            assert primary_action == ActionType.FILE_WRITE, f"Failed for write prompt: {prompt} -> got {primary_action}"
            # Critical invariant: must NEVER classify as screenshot
            assert not DirectActionRouter._is_screenshot_request(prompt), f"Write prompt routed as screenshot: {prompt}"

        elif category == "workflow":
            assert primary_action == ActionType.STRUCTURED_WORKFLOW, (
                f"Failed for workflow prompt: {prompt} -> got {primary_action}"
            )
            assert not DirectActionRouter._is_screenshot_request(prompt), (
                f"Workflow prompt routed as screenshot: {prompt}"
            )

        elif category.startswith("read"):
            assert primary_action == ActionType.FILE_READ, f"Failed for read prompt: {prompt} -> got {primary_action}"
            if category == "read_exact":
                assert parsed.response_mode == ResponseMode.EXACT_RAW, f"Failed exact response mode for: {prompt}"
            assert not DirectActionRouter._is_screenshot_request(prompt), f"Read prompt routed as screenshot: {prompt}"

        elif category == "screenshot":
            assert primary_action == ActionType.SCREENSHOT_CAPTURE, (
                f"Failed for screenshot prompt: {prompt} -> got {primary_action}"
            )
            assert DirectActionRouter._is_screenshot_request(prompt) is True

        elif category == "negated_or_non_screenshot":
            # Must NEVER route screenshot
            assert DirectActionRouter._is_screenshot_request(prompt) is False, (
                f"Negated/controlled prompt routed as screenshot: {prompt}"
            )

        passed_count += 1

    assert passed_count >= 1000
    assert wrong_action_count == 0
