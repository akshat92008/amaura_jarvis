"""Phase 7 Test Suite 1: Structural Request Preprocessing & Semantic Span Masking."""

import json

from jarvis.amaura.direct_action import (
    ActionType,
    RequestPreprocessor,
    ResponseMode,
    SpanType,
)


def test_balanced_json_extraction():
    """Verify balanced JSON object and array scanning with nested brackets and quotes."""
    text1 = 'store this JSON config: {"name": "jarvis", "meta": {"active": true, "tags": ["a", "b"]}} in /tmp/conf.json'
    parsed1 = RequestPreprocessor.process(text1)
    assert len(parsed1.structured_literals) == 1
    assert parsed1.structured_literals[0].span_type == SpanType.JSON_OBJECT
    extracted_json = json.loads(parsed1.structured_literals[0].raw_text)
    assert extracted_json["name"] == "jarvis"
    assert extracted_json["meta"]["tags"] == ["a", "b"]

    text2 = 'save the array: [1, 2, {"k": "v"}, [4, 5]] to /tmp/arr.json'
    parsed2 = RequestPreprocessor.process(text2)
    assert len(parsed2.structured_literals) == 1
    assert parsed2.structured_literals[0].span_type == SpanType.JSON_ARRAY
    extracted_arr = json.loads(parsed2.structured_literals[0].raw_text)
    assert len(extracted_arr) == 4
    assert extracted_arr[2]["k"] == "v"


def test_fenced_and_inline_code_extraction():
    """Verify code block and inline code extraction."""
    text1 = "write to /tmp/script.py:\n```python\ndef hello():\n    return 42\n```"
    parsed1 = RequestPreprocessor.process(text1)
    assert len(parsed1.code_blocks) == 1
    assert parsed1.code_blocks[0].span_type == SpanType.CODE_BLOCK
    assert "def hello():" in parsed1.code_blocks[0].metadata["inner"]

    text2 = "set file /tmp/cmd.sh content to `echo 'test'`"
    parsed2 = RequestPreprocessor.process(text2)
    assert len(parsed2.code_blocks) == 1
    assert parsed2.code_blocks[0].span_type == SpanType.INLINE_CODE
    assert parsed2.code_blocks[0].metadata["inner"] == "echo 'test'"


def test_span_masking_classifier_view():
    """Verify that non-intent tokens in paths and quoted literals are masked."""
    # 1. Desktop in path
    text1 = 'Take the number in "/Users/test/Desktop/right.num" away from "/Users/test/Desktop/left.num" and save to "/tmp/out.num"'
    parsed1 = RequestPreprocessor.process(text1)
    assert "<PATH>" in parsed1.masked_classifier_view
    assert "Desktop" not in parsed1.masked_classifier_view
    assert parsed1.primary_action is not None
    assert parsed1.primary_action.action_type == ActionType.STRUCTURED_WORKFLOW

    # 2. Screenshot in quoted literal
    text2 = 'write the word "screenshot" into /tmp/file.txt'
    parsed2 = RequestPreprocessor.process(text2)
    assert "<QUOTED_LITERAL>" in parsed2.masked_classifier_view
    assert "<PATH>" in parsed2.masked_classifier_view
    assert parsed1.primary_action is not None
    assert parsed2.primary_action.action_type == ActionType.FILE_WRITE


def test_clause_segmentation_and_negation():
    """Verify clause segmentation and negation scoping."""
    text1 = "write 'hello' to /tmp/a.txt; do not take a screenshot"
    parsed1 = RequestPreprocessor.process(text1)
    assert len(parsed1.clauses) == 2
    assert not parsed1.clauses[0].is_negated
    assert parsed1.clauses[1].is_negated
    assert (
        "screenshot" in parsed1.clauses[1].masked_text.lower() or "<QUOTED_LITERAL>" in parsed1.clauses[1].masked_text
    )

    # Screenshot action must be blocked as negated
    screenshot_cands = [c for c in parsed1.candidate_actions if c.action_type == ActionType.SCREENSHOT_CAPTURE]
    assert len(screenshot_cands) > 0
    assert screenshot_cands[0].is_blocked_as_negated is True
    assert screenshot_cands[0].confidence == 0.0


def test_response_mode_detection():
    """Verify response format constraints are separated into ResponseMode."""
    # Normal read
    parsed_norm = RequestPreprocessor.process("read /tmp/data.txt")
    assert parsed_norm.response_mode == ResponseMode.NORMAL

    # Exact raw read
    parsed_raw1 = RequestPreprocessor.process("read /tmp/data.txt and return exactly its contents")
    assert parsed_raw1.response_mode == ResponseMode.EXACT_RAW

    parsed_raw2 = RequestPreprocessor.process("give me raw contents of /tmp/data.txt without line numbers")
    assert parsed_raw2.response_mode == ResponseMode.EXACT_RAW

    parsed_raw3 = RequestPreprocessor.process("whole reply must be file text of /tmp/data.txt")
    assert parsed_raw3.response_mode == ResponseMode.EXACT_RAW
