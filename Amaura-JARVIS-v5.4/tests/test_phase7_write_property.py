"""Phase 7 Test Suite 4: Write Parser Property Testing (1,500+ Generated Cases)."""

import json
import random
import string
import pytest
from jarvis.amaura.direct_action import WriteActionParser, WriteAction


def _random_identifier(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def generate_write_cases(count: int = 1600):
    """Generate comprehensive variations of write requests with expected payloads."""
    cases = []

    for i in range(count):
        cat = i % 8
        tgt = f"/tmp/{_random_identifier(6)}_{i}.txt"

        # Cat 0: Quoted payload with target after
        if cat == 0:
            payload = f"Payload content {i} with unicode: 🚀 — {_random_identifier(10)}"
            prompt = random.choice([
                f'write "{payload}" to {tgt}',
                f'save the text "{payload}" in {tgt}',
                f'put "{payload}" into {tgt}',
                f'record "{payload}" at {tgt}',
            ])
            cases.append((prompt, tgt, payload, False, False))

        # Cat 1: Target first with semicolon / period
        elif cat == 1:
            payload = f"Clause content {i} with numbers 42 and symbols %$#@!"
            prompt = random.choice([
                f"create {tgt}; contents must be {payload}",
                f"create {tgt}. Its body should be {payload}",
                f"write to {tgt}; set content to {payload}",
                f"at {tgt}, store {payload}",
            ])
            cases.append((prompt, tgt, payload, False, False))

        # Cat 2: Balanced JSON Object payload
        elif cat == 2:
            json_dict = {
                "id": f"item_{i}",
                "count": i * 10,
                "nested": {"active": True, "score": 99.5},
                "tags": ["alpha", "beta", str(i)],
            }
            json_str = json.dumps(json_dict)
            tgt_json = f"/tmp/json_store_{i}.json"
            prompt = random.choice([
                f"store this JSON text in {tgt_json}: {json_str}",
                f"save to {tgt_json} the following json: {json_str}",
                f"write {json_str} into {tgt_json}",
            ])
            cases.append((prompt, tgt_json, json_str, False, False))

        # Cat 3: Balanced JSON Array payload
        elif cat == 3:
            json_arr = [f"elem_{i}", i, {"k": f"v_{i}"}, [1, 2, 3]]
            json_str = json.dumps(json_arr)
            tgt_json = f"/tmp/arr_store_{i}.json"
            prompt = f"save the array {json_str} to {tgt_json}"
            cases.append((prompt, tgt_json, json_str, False, False))

        # Cat 4: Multiline Block with separators (:, ->, ==)
        elif cat == 4:
            lines = [f"LINE_1_{i}", f"LINE_2_{i}", f"LINE_3_{i} - footer"]
            payload = "\n".join(lines)
            sep = random.choice([":", "->", "=="])
            prompt = f"write to {tgt} the following {sep}\n{payload}"
            cases.append((prompt, tgt, payload, False, False))

        # Cat 5: Explicit Empty File
        elif cat == 5:
            prompt = random.choice([
                f"create an empty file at {tgt}",
                f"make 0-byte file in {tgt}",
                f"put nothing inside {tgt}",
                f"save a blank file to {tgt}",
            ])
            cases.append((prompt, tgt, "", True, False))

        # Cat 6: Directives with 'only', 'verbatim', 'strictly'
        elif cat == 6:
            payload = f"Strict token: auth_{_random_identifier(12)}_{i}"
            prompt = random.choice([
                f'write verbatim "{payload}" to {tgt}',
                f'save only the quoted text "{payload}" in {tgt}',
                f'strictly output "{payload}" into {tgt}',
                f'store exactly "{payload}" at {tgt}',
            ])
            cases.append((prompt, tgt, payload, False, False))

        # Cat 7: Ambiguous Requests (MUST FAIL CLOSED)
        elif cat == 7:
            prompt = f'write to {tgt} either "first_option_{i}" or "second_option_{i}"'
            cases.append((prompt, tgt, None, False, True))

    return cases


def test_write_parser_property_1500_cases():
    """Verify >= 1,500 generated write cases match exact expected payload or fail closed on ambiguity."""
    cases = generate_write_cases(1600)
    assert len(cases) >= 1500

    success_count = 0
    fail_closed_count = 0

    for prompt, expected_tgt, expected_payload, is_empty, is_ambiguous in cases:
        action = WriteActionParser.parse(prompt)
        assert action is not None, f"Failed to parse write action for: {prompt}"

        if is_ambiguous:
            assert action.is_invalid is True, f"Ambiguous prompt did not fail closed: {prompt}"
            fail_closed_count += 1
        elif is_empty:
            assert action.explicit_empty is True, f"Failed explicit empty for: {prompt}"
            assert action.content == "", f"Non-empty content for empty file: {action.content}"
            assert action.is_invalid is False
            success_count += 1
        else:
            assert action.is_invalid is False, f"Valid prompt rejected as invalid: {action.invalid_reason} ({prompt})"
            assert action.target_path == expected_tgt, f"Target mismatch: got {action.target_path} vs {expected_tgt}"
            assert action.content == expected_payload, f"Payload mismatch: got {repr(action.content)} vs {repr(expected_payload)}"
            success_count += 1

    assert success_count >= 1300
    assert fail_closed_count >= 150
