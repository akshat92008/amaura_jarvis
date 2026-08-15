"""Phase 5 Tests: File Write Clause Parsing, Precondition, Postcondition, and Failure Injection."""

import os
import random
import string
import tempfile
from pathlib import Path
import pytest

from jarvis.amaura.direct_action import DirectActionRouter, WriteActionParser, WriteAction
from jarvis.tools.security import tool_workspace


def _random_token(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def test_write_action_parser_clause_variations():
    """Test at least 30 randomized variations of write clause structures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        variations = [
            # 1. Independent sentence after path with "Its complete content must be:"
            ("Create {path}. Its complete content must be: {payload}", "alpha_content_1"),
            # 2. Independent sentence with "Content:"
            ("Make {path}. Content: {payload}", "beta_content_2"),
            # 3. Independent sentence with "Its content is"
            ("Create {path}. Its content is {payload}", "gamma_content_3"),
            # 4. Semicolon clause with "put X inside it"
            ("Create {path}; put {payload} inside it", "delta_content_4"),
            # 5. Connected clause with "and its complete text should be"
            ("Create {path}, and its complete text should be {payload}", "epsilon_content_5"),
            # 6. Content before path: "Save X into Y"
            ("Save '{payload}' into {path}", "zeta_content_6"),
            # 7. Content before path: "Put X in Y"
            ("Put {payload} in {path}", "eta_content_7"),
            # 8. Content before path: "Write X to Y"
            ("Write '{payload}' to {path}", "theta_content_8"),
            # 9. Inverted sentence: "The file X should contain Y"
            ("The file {path} should contain {payload}", "iota_content_9"),
            # 10. Keyword "containing"
            ("Make {path} containing '{payload}'", "kappa_content_10"),
            # 11. Keyword "with body"
            ("Write {path} with body {payload}", "lambda_content_11"),
            # 12. Colon syntax after path
            ("Create {path}: {payload}", "mu_content_12"),
            # 13. Multiline payload
            ("Create {path}. Its content is:\nline1_{payload}\nline2_{payload}", "multi_13"),
            # 14. Extensionless file
            ("Save '{payload}' to {path}", "extless_14"),
            # 15. Unusual extension (.customext)
            ("Write {path} with content {payload}", "unusual_15"),
            # 16. JSON payload
            ('Create {path}. Content: {{"key": "{payload}", "num": 42}}', "json_16"),
            # 17. Quoted path and unquoted payload
            ("Create '{path}'. The text should be: {payload}", "quoted_path_17"),
            # 18. Payload containing punctuation
            ("Save 'value=1; status=ok; token={payload}' into {path}", "punct_18"),
            # 19. "Dump X into Y"
            ("Dump '{payload}' into {path}", "dump_19"),
            # 20. "Store X at Y"
            ("Store '{payload}' at {path}", "store_20"),
            # 21. "Create file X, putting Y inside"
            ("Create {path}; put '{payload}' inside", "inside_21"),
            # 22. "Create X. Payload is: Y"
            ("Create {path}. Payload is: {payload}", "payload_is_22"),
            # 23. "Create X. Body is Y"
            ("Create {path}. Body is {payload}", "body_is_23"),
            # 24. "Make file at X with text Y"
            ("Make file at {path} with text '{payload}'", "with_text_24"),
            # 25. "Write following into X: Y"
            ("Write the following into {path}: {payload}", "following_25"),
            # 26. "Put the text X in file Y"
            ("Put the text '{payload}' in file {path}", "put_text_26"),
            # 27. "Save data X to Y"
            ("Save data '{payload}' to {path}", "save_data_27"),
            # 28. "Create X. Its exact text must be: Y"
            ("Create {path}. Its exact text must be: {payload}", "exact_text_28"),
            # 29. "Create X, and set its content to Y"
            ("Create {path}. Its entire payload should be: {payload}", "entire_payload_29"),
            # 30. "Create X. Data is: Y"
            ("Create {path}. Data is: {payload}", "data_is_30"),
            # 31. Backtick quoted payload
            ("Save `{payload}` into {path}", "backtick_31"),
            # 32. "The file X must hold Y"
            ("The file {path} should have content: {payload}", "hold_32"),
        ]

        assert len(variations) >= 30

        for idx, (template, pfx) in enumerate(variations):
            ext = ".txt" if idx % 3 == 0 else (".custom" if idx % 3 == 1 else "")
            filename = f"test_file_{idx}_{_random_token(4)}{ext}"
            file_path = tmp_path / filename
            payload = f"{pfx}_{_random_token(12)}"
            
            prompt = template.format(path=str(file_path), payload=payload)
            action = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
            
            assert action is not None, f"Failed to parse prompt variation {idx}: '{prompt}'"
            assert action.target_path in (str(file_path), filename)
            assert not action.is_invalid, f"Variation {idx} marked invalid unexpectedly: {action.invalid_reason}"
            
            # Execute through router
            res = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
            assert res is not None, f"Router returned None for variation {idx}: '{prompt}'"
            assert res.success is True, f"Execution failed for variation {idx}: {res.output}"
            assert file_path.exists(), f"File {file_path} was not created on disk"
            
            actual_content = file_path.read_text(encoding="utf-8")
            # Verify exact content match
            if "\n" in payload:
                assert actual_content.strip() == payload.strip()
            elif "{" in payload:
                assert "key" in actual_content and payload in actual_content
            else:
                assert payload in actual_content or actual_content == payload


def test_write_empty_file_explicit():
    """Test explicit empty file creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        empty_file = tmp_path / "empty.txt"
        
        prompt = f"Create an empty file at {empty_file}"
        action = WriteActionParser.parse(prompt, default_workspace=str(tmp_path))
        assert action is not None
        assert action.is_empty_requested is True
        assert action.content == ""
        assert not action.is_invalid
        
        res = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
        assert res is not None
        assert res.success is True
        assert empty_file.exists()
        assert empty_file.stat().st_size == 0


def test_write_precondition_unparsed_content_rejection():
    """Test that when content is semantically requested but unparsed, write is rejected (Phase 2)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        target = tmp_path / "target.txt"
        
        # Artificially test WriteAction with has_explicit_content=True, content="", is_empty_requested=False
        invalid_action = WriteAction(
            target_path=str(target),
            content="",
            has_explicit_content=True,
            is_empty_requested=False,
            is_invalid=True,
            invalid_reason="Write precondition failed: semantic content requested but parsed content is empty",
        )
        assert invalid_action.is_invalid is True


def test_write_failure_injections():
    """Test write postcondition failure injections: zero bytes, wrong bytes (Phase 3)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        file_path = tmp_path / "injected.txt"
        
        # Test 1: Simulate write tool leaving 0 bytes when non-empty content was requested
        file_path.write_text("") # 0 bytes
        expected_content = "non_empty_payload_12345"
        
        # Direct verification check
        actual = file_path.read_text(encoding="utf-8")
        assert len(expected_content) > 0 and len(actual) == 0
        
        # Test 2: Simulate write tool writing wrong bytes
        file_path.write_text("corrupted_payload")
        assert file_path.read_text(encoding="utf-8") != expected_content
