import pytest
import sqlite3
import threading
from jarvis.amaura.store import CompanyStore

def test_company_store_nested_savepoints(tmp_path):
    store = CompanyStore(tmp_path / "amaura.db")
    
    with store.atomic_block():
        store.insert_work_item({"id": "task1", "item_type": "task", "workflow_id": "wf1", "step_key": "step1", "owner_id": "owner1", "state": "assigned", "priority": "normal", "risk": "low", "title": "t1"})
        
        try:
            with store.atomic_block():
                store.insert_work_item({"id": "task2", "item_type": "task", "workflow_id": "wf1", "step_key": "step1", "owner_id": "owner1", "state": "assigned", "priority": "normal", "risk": "low", "title": "t2"})
                raise ValueError("Nested failure")
        except ValueError:
            pass
            
    # task1 should exist, task2 should be rolled back
    rows = store._connection.execute("SELECT id FROM work_items").fetchall()
    ids = [row[0] for row in rows]
    
    assert "task1" in ids
    assert "task2" not in ids
