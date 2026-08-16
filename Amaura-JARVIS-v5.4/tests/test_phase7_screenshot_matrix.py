"""Phase 7 Test Suite 3: Screenshot Positive / Negative Matrix (250+ Positives, 250+ Negative Controls)."""

import random

from jarvis.amaura.direct_action import (
    DirectActionRouter,
)


def generate_positive_screenshot_cases(count: int = 300) -> list[str]:
    """Generate positive screenshot requests requiring CAPTURE_VERB + SCREEN_OBJECT."""
    verbs = ["take", "capture", "grab", "snap"]
    screen_nouns = [
        "screenshot",
        "screen shot",
        "the screen",
        "current screen",
        "the display",
        "current display",
        "the desktop",
    ]
    targets = ["screenshot.png", "capture.png", "display.png", "/tmp/shot.png", "/Users/operator/screen.png"]
    connectors = ["and save to", "and write to", "saving in", "to", "into", "stored at"]

    cases = []
    for _ in range(count):
        v = random.choice(verbs)
        n = random.choice(screen_nouns)
        c = random.choice(connectors)
        t = random.choice(targets)
        r = random.randint(0, 3)
        if r == 0:
            cases.append(f"{v} {n} {c} {t}")
        elif r == 1:
            cases.append(f"please {v} {n} {c} {t}")
        elif r == 2:
            cases.append(f"{v} {n}")
        else:
            cases.append(f"{v} {n}; output file should be {t}")
    return cases


def generate_negative_screenshot_controls(count: int = 300) -> list[str]:
    """Generate negative controls that must NOT route to screenshot execution."""
    cases = []

    # Category 1: Quoted literal mentions of 'screenshot'
    for i in range(60):
        cases.append(f'write "screenshot" to /tmp/log_{i}.txt')
        cases.append(f'create file /tmp/data_{i}.txt with body "take a screenshot"')

    # Category 2: Negation
    for i in range(60):
        cases.append(f"do not take a screenshot {i}")
        cases.append(f"don't capture the screen {i}")
        cases.append(f"never take screenshots {i}")
        cases.append(f"read /tmp/file_{i}.txt without taking a screenshot")

    # Category 3: Path contamination (Desktop / screen in path)
    for i in range(60):
        cases.append(f"cat /Users/operator/Desktop/report_{i}.txt")
        cases.append(f"read /Users/operator/screen_logs/log_{i}.json")
        cases.append(f"list directory /Users/operator/Desktop/folder_{i}")

    # Category 4: Arithmetic 'take'
    for i in range(60):
        cases.append(
            f"take the number in /Users/operator/Desktop/a_{i}.num away from /Users/operator/Desktop/b_{i}.num and save to /tmp/res_{i}.num"
        )
        cases.append(f"take 15 away from 40 and store in /tmp/math_{i}.txt")

    # Category 5: Discussion / conversational questions
    for _ in range(60):
        cases.append("what is a screenshot and how does it work in macOS?")
        cases.append("how do I capture the display using native shortcuts?")
        cases.append("explain the difference between desktop capture and window capture")

    return cases[:count]


def test_screenshot_positive_matrix():
    """Verify >= 250 positive screenshot requests route accurately to SCREENSHOT_CAPTURE."""
    positives = generate_positive_screenshot_cases(300)
    assert len(positives) >= 250

    wrong_count = 0
    for prompt in positives:
        is_screenshot = DirectActionRouter._is_screenshot_request(prompt)
        if not is_screenshot:
            wrong_count += 1
        assert is_screenshot, f"Failed positive screenshot routing for: {prompt}"

    assert wrong_count == 0


def test_screenshot_negative_controls_matrix():
    """Verify >= 250 negative controls NEVER route to SCREENSHOT_CAPTURE."""
    negatives = generate_negative_screenshot_controls(300)
    assert len(negatives) >= 250

    wrong_execution_count = 0
    for prompt in negatives:
        is_screenshot = DirectActionRouter._is_screenshot_request(prompt)
        if is_screenshot:
            wrong_execution_count += 1
        assert not is_screenshot, f"Negative control erroneously classified as screenshot: {prompt}"

    assert wrong_execution_count == 0
