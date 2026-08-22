"""Regression tests for the Antigravity result-contract extractor.

Phase 2 of the final qualification pass.

ACCEPT cases — _extract_contract finds a candidate:
  - Full valid contract with schema field
  - Valid contract with schema field OMITTED (compatibility fallback)
  - Contract nested under wrapper keys

REJECT-BY-EXTRACTOR — _extract_contract raises GovernanceError because no
contract shape can be found in the output:
  - success=False / success="true" / success=1
  - Missing changed_files AND missing schema (can't match either path)
  - Empty string, malformed JSON, arbitrary JSON
  - summary too short in the fallback path

REJECT-BY-MODEL — model_validate raises after extraction because the dict
fails structural constraints:
  - empty changed_files list
  - changed_files not a list
  - empty verification_commands list
  - verification_commands not a list
  - missing changed_files (extractor finds it via schema path, validator rejects)
  - missing verification_commands
  - inline python -c
  - path traversal
  - absolute path
  - remaining_failures present
"""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter, AntigravityResultContract
from jarvis.amaura.models import GovernanceError


def _make_valid() -> dict:
    return {
        "schema": "amaura.antigravity-result.v1",
        "success": True,
        "summary": "Fixed the greeting function.",
        "changed_files": ["src/greet.py"],
        "verification_commands": ["python -m unittest tests/test_greet.py"],
    }


class TestExtractContractAccept(unittest.TestCase):
    """_extract_contract should find and return a candidate dict."""

    def _extract(self, payload: str) -> dict:
        return AntigravityDeliveryAdapter._extract_contract(payload)

    def test_full_valid_contract_with_schema(self):
        result = self._extract(json.dumps(_make_valid()))
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")
        self.assertIs(result["success"], True)

    def test_schema_omission_compatibility_fallback(self):
        """Gemini sometimes omits the const schema field — normalise it."""
        d = _make_valid()
        del d["schema"]
        result = self._extract(json.dumps(d))
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")
        self.assertIs(result["success"], True)

    def test_contract_nested_in_structured_output(self):
        result = self._extract(json.dumps({"structured_output": _make_valid()}))
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")

    def test_contract_nested_in_result_key(self):
        result = self._extract(json.dumps({"result": _make_valid()}))
        self.assertIs(result["success"], True)

    def test_contract_as_last_json_line(self):
        noise = '{"event":"step_update","step_index":1}\n'
        result = self._extract(noise + json.dumps(_make_valid()) + "\n")
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")

    def test_stream_envelope_fields_are_not_treated_as_contract_fields(self):
        payload = _make_valid() | {"toolAction": "Finishing task", "toolSummary": "Complete task"}
        result = self._extract(json.dumps(payload))
        self.assertNotIn("toolAction", result)
        AntigravityResultContract.model_validate(result)

    def test_schema_omission_with_result_as_summary_fallback(self):
        d = _make_valid()
        del d["schema"]
        del d["summary"]
        d["result"] = "Fixed greeting."
        result = self._extract(json.dumps(d))
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")

    def test_schema_omission_with_message_as_summary_fallback(self):
        d = _make_valid()
        del d["schema"]
        del d["summary"]
        d["message"] = "Greeting fixed."
        result = self._extract(json.dumps(d))
        self.assertEqual(result["schema"], "amaura.antigravity-result.v1")


class TestExtractContractRejectByExtractor(unittest.TestCase):
    """These payloads must cause _extract_contract to raise GovernanceError
    because no valid contract candidate can be found at all."""

    def _should_raise(self, payload: str) -> None:
        with self.assertRaises(GovernanceError):
            AntigravityDeliveryAdapter._extract_contract(payload)

    def test_empty_string(self):
        self._should_raise("")

    def test_malformed_json_only(self):
        self._should_raise("{not valid json at all}")

    def test_empty_json_object(self):
        self._should_raise("{}")

    def test_arbitrary_json_no_contract_keys(self):
        self._should_raise('{"status": "ok", "data": 42}')

    def test_success_false(self):
        """success=False means the fallback can't match; schema path won't fire."""
        d = _make_valid()
        d["success"] = False
        self._should_raise(json.dumps(d))

    def test_success_string_true(self):
        """String 'true' is not `is True`, fallback rejects; schema path rejects."""
        d = _make_valid()
        d["success"] = "true"
        self._should_raise(json.dumps(d))

    def test_success_integer_one(self):
        """Truthy int 1 is not `is True`, fallback rejects."""
        d = _make_valid()
        d["success"] = 1
        self._should_raise(json.dumps(d))

    def test_summary_too_short_in_fallback(self):
        """Without schema, fallback checks len(summary) >= 3; 2-char summary rejects."""
        d = _make_valid()
        del d["schema"]
        d["summary"] = "ab"  # 2 chars
        self._should_raise(json.dumps(d))

    def test_permission_bypass_keys_do_not_match(self):
        payload = json.dumps({"allow": "*", "unsandboxed": True, "bypass": True})
        self._should_raise(payload)

    def test_missing_changed_files_and_no_schema(self):
        """No schema field, no changed_files → fallback can't match → reject."""
        d = _make_valid()
        del d["schema"]
        del d["changed_files"]
        self._should_raise(json.dumps(d))

    def test_missing_verification_commands_and_no_schema(self):
        d = _make_valid()
        del d["schema"]
        del d["verification_commands"]
        self._should_raise(json.dumps(d))


class TestExtractContractRejectByModelValidate(unittest.TestCase):
    """These payloads are found by the extractor but rejected by model_validate.
    When a full schema: field is present, the extractor returns the raw dict
    trusting model_validate to enforce structure.
    """

    def _full_validate(self, d: dict) -> None:
        """Extract then model_validate — the combined pipeline that production uses."""
        extracted = AntigravityDeliveryAdapter._extract_contract(json.dumps(d))
        AntigravityResultContract.model_validate(extracted)

    def test_inline_python_c_rejected(self):
        d = _make_valid()
        d["verification_commands"] = ['python3 -c "import greet"']
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_path_traversal_in_changed_files_rejected(self):
        d = _make_valid()
        d["changed_files"] = ["../../../etc/passwd"]
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_absolute_path_in_changed_files_rejected(self):
        d = _make_valid()
        d["changed_files"] = ["/usr/local/bin/secret"]
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_remaining_failures_blocks_success(self):
        d = _make_valid()
        d["remaining_failures"] = ["test_foo still fails"]
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_missing_changed_files_with_schema_present(self):
        """Extractor finds it via schema path, model_validate rejects missing field."""
        d = _make_valid()
        del d["changed_files"]
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_empty_changed_files_with_schema_present(self):
        d = _make_valid()
        d["changed_files"] = []
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_changed_files_string_not_list_with_schema(self):
        d = _make_valid()
        d["changed_files"] = "src/greet.py"
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_missing_verification_commands_with_schema_present(self):
        d = _make_valid()
        del d["verification_commands"]
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_empty_verification_commands_with_schema_present(self):
        d = _make_valid()
        d["verification_commands"] = []
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_verification_commands_string_not_list_with_schema(self):
        d = _make_valid()
        d["verification_commands"] = "python -m unittest"
        with self.assertRaises((ValidationError, GovernanceError, ValueError)):
            self._full_validate(d)

    def test_schema_omission_normalised_passes_model_validate(self):
        """The schema-omission normalised form must round-trip through model_validate."""
        d = _make_valid()
        del d["schema"]
        extracted = AntigravityDeliveryAdapter._extract_contract(json.dumps(d))
        contract = AntigravityResultContract.model_validate(extracted)
        self.assertIs(contract.success, True)
        self.assertEqual(contract.changed_files, ["src/greet.py"])


if __name__ == "__main__":
    unittest.main()
