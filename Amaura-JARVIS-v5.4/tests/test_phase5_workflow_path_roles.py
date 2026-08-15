"""Phase 5 Tests: Workflow Path Role Extraction and Delimited Table Generalization (Phases 12, 13, 14)."""

import json
import tempfile
from pathlib import Path
import pytest

from jarvis.amaura.direct_action import DirectActionRouter


def test_workflow_csv_to_json():
    """Convert comma-separated table to JSON array with type inference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        csv_file = ws / "users.csv"
        json_file = ws / "users.json"
        
        csv_file.write_text("name,age,active,score\nAlice,30,true,95.5\nBob,25,false,88.0\n")
        
        prompt = f"Read table {csv_file} and save transformed JSON in {json_file}"
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        
        assert res is not None
        assert res.success is True
        assert json_file.exists()
        
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0] == {"name": "Alice", "age": 30, "active": True, "score": 95.5}
        assert data[1] == {"name": "Bob", "age": 25, "active": False, "score": 88.0}


def test_workflow_tsv_to_json():
    """Convert tab-separated table to JSON array."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        tsv_file = ws / "products.tsv"
        json_file = ws / "products.json"
        
        tsv_file.write_text("id\titem\tqty\tprice\n101\tWidget\t5\t19.99\n102\tGadget\t10\t49.5\n")
        
        prompt = f"Read table {tsv_file} and save transformed JSON in {json_file}"
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        
        assert res is not None
        assert res.success is True
        assert json_file.exists()
        
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["id"] == 101
        assert data[0]["qty"] == 5
        assert data[0]["price"] == 19.99


def test_workflow_pipe_delimited_markdown_to_json():
    """Convert pipe-delimited markdown table to JSON array."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        pipe_file = ws / "table.txt"
        json_file = ws / "out.json"
        
        pipe_file.write_text("| city | pop | coastal |\n|---|---|---|\n| Seattle | 750000 | true |\n| Denver | 715000 | false |\n")
        
        prompt = f"Read table {pipe_file} and convert to JSON at {json_file}"
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        
        assert res is not None
        assert res.success is True
        assert json_file.exists()
        
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["city"] == "Seattle"
        assert data[0]["pop"] == 750000
        assert data[0]["coastal"] is True


def test_workflow_semicolon_to_json():
    """Convert semicolon-delimited file to JSON array."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        semi_file = ws / "config.txt"
        json_file = ws / "config.json"
        
        semi_file.write_text("server;port;ssl\nalpha;8080;true\nbeta;9090;false\n")
        
        prompt = f"Read semicolon table from {semi_file} and save to {json_file}"
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        
        assert res is not None
        assert res.success is True
        assert json_file.exists()
        
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["port"] == 8080
        assert data[0]["ssl"] is True


def test_workflow_destination_first_path_ordering():
    """Ensure path roles are correctly assigned even when destination is mentioned before source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        src_file = ws / "data_input.csv"
        dest_file = ws / "data_output.json"
        
        src_file.write_text("metric,value\ncpu,45\nmem,60\n")
        
        # Destination path occurs before source path in prompt
        prompt = f"Save transformed JSON in {dest_file} after reading table {src_file}"
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        
        assert res is not None
        assert res.success is True
        assert dest_file.exists()
        
        data = json.loads(dest_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["metric"] == "cpu"
        assert data[0]["value"] == 45
