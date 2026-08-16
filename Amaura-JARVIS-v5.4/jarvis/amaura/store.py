"""Durable SQLite ledger for Amaura work, evidence, approvals, and audit history."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import threading
import uuid
import weakref
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

from jarvis.amaura.operation_policy import requires_reconciliation_after_lease_expiry
from jarvis.paths import get_data_dir


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _compact_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        if isinstance(value, dict):
            return {"_truncated": True, "keys": list(value.keys())[:20]}
        if isinstance(value, list):
            return {"_truncated": True, "count": len(value)}
    if isinstance(value, str):
        return value if len(value) <= 4000 else value[:4000] + "\n...[truncated]"
    if isinstance(value, list):
        compacted_list = [_compact_json_value(item, depth=depth + 1) for item in value[:25]]
        if len(value) > 25:
            compacted_list.append({"_truncated": True, "remaining": len(value) - 25})
        return compacted_list
    if isinstance(value, dict):
        items = list(value.items())
        compacted_dict = {str(key): _compact_json_value(item, depth=depth + 1) for key, item in items[:40]}
        if len(items) > 40:
            compacted_dict["_truncated_keys"] = len(items) - 40
        return compacted_dict
    return value


def _bounded_json_record(value: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    if _json_size(value) <= max_bytes:
        return value
    compacted = _compact_json_value(value)
    if isinstance(compacted, dict):
        compacted["_amaura_truncated"] = True
        compacted["_amaura_original_bytes"] = _json_size(value)
    if _json_size(compacted) <= max_bytes:
        return compacted
    keep = {
        key: compacted[key]
        for key in (
            "run_id",
            "status",
            "mode",
            "worker_id",
            "actions",
            "errors",
            "summary",
            "_amaura_truncated",
            "_amaura_original_bytes",
        )
        if isinstance(compacted, dict) and key in compacted
    }
    keep["_amaura_truncated"] = True
    keep["_amaura_compaction"] = "large autonomy result stored as bounded summary"
    return keep


class CompanyStore:
    """Thread-safe, append-audited company state store."""

    JSON_COLUMNS: ClassVar[set[str]] = {
        "acceptance_criteria",
        "dependencies",
        "evidence",
        "metadata",
        "payload",
        "details",
        "config",
        "score_components",
        "output",
        "metrics",
        "lesson",
        "asset_metadata",
        "evidence_snapshot",
        "result",
        "labels",
        "attributes",
        "receipt",
        "inputs",
        "asset_ids",
        "raw_metadata",
        "classification",
        "line_items",
        "value",
    }
    MUTABLE_WORK_FIELDS: ClassVar[set[str]] = {
        "owner_id",
        "reviewer_id",
        "state",
        "priority",
        "deadline",
        "budget_cents",
        "spent_cents",
        "risk",
        "success_metric",
        "acceptance_criteria",
        "dependencies",
        "evidence",
        "summary",
        "action_type",
        "metadata",
    }

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        audit_checkpoint_path: str | Path | None = None,
    ):
        default_dir = Path(os.environ.get("AMAURA_DATA_DIR", get_data_dir() / "amaura"))
        self.db_path = Path(db_path) if db_path else default_dir / "amaura.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_checkpoint_path_override = (
            Path(audit_checkpoint_path).expanduser().resolve() if audit_checkpoint_path is not None else None
        )
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._autocommit = True  # set False inside atomic_block to batch commits
        self._savepoints = 0
        self._closed = False
        self._audit_integrity_fault = ""
        try:
            self._migrate()
            self._initialize_empty_audit_checkpoint()
            self._validate_external_audit_checkpoint_on_open()
        except Exception:
            self._connection.close()
            self._closed = True
            raise
        self._finalizer = weakref.finalize(self, CompanyStore._finalize_connection, self._connection)
        # Explicit service shutdown handles process-global stores.  Running many
        # SQLite close callbacks during late interpreter finalization can block
        # Python shutdown after a multiprocessing test or worker lifecycle.
        cast(Any, self._finalizer).atexit = False

    @staticmethod
    def _finalize_connection(connection: sqlite3.Connection) -> None:
        try:
            connection.close()
        except Exception:
            pass

    def close(self) -> None:
        """Close the SQLite connection exactly once."""
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            if getattr(self, "_closed", True):
                return
            finalizer = getattr(self, "_finalizer", None)
            if finalizer is not None and finalizer.alive:
                finalizer()
            else:
                CompanyStore._finalize_connection(self._connection)
            self._closed = True

    def __enter__(self) -> CompanyStore:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    @contextlib.contextmanager
    def atomic_block(self) -> Any:
        """Context manager that wraps multiple operations in a single transaction (P1).

        Within the block, individual operations skip their per-row commits.
        On exit the transaction is committed; on exception it is rolled back.
        Supports nested transactions using SQLite SAVEPOINTs (P0-3).
        """
        with self._lock:
            is_outer = self._savepoints == 0

            if is_outer:
                self._connection.execute("BEGIN IMMEDIATE")
                self._autocommit = False

            self._savepoints += 1
            sp_name = f"sp_{self._savepoints}"
            self._connection.execute(f"SAVEPOINT {sp_name}")

            try:
                yield
                self._connection.execute(f"RELEASE SAVEPOINT {sp_name}")
                if is_outer:
                    self._connection.commit()
            except Exception:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                if is_outer:
                    self._connection.rollback()
                raise
            finally:
                self._savepoints -= 1
                if is_outer:
                    self._autocommit = True

    def _commit_if_needed(self) -> None:
        if self._autocommit:
            self._connection.commit()

    def integrity_check(self) -> dict[str, Any]:
        """Run SQLite structural and referential integrity checks."""
        with self._lock:
            integrity = [row[0] for row in self._connection.execute("PRAGMA integrity_check").fetchall()]
            foreign_keys = [dict(row) for row in self._connection.execute("PRAGMA foreign_key_check").fetchall()]
            journal_mode = self._connection.execute("PRAGMA journal_mode").fetchone()[0]
        audit_chain = self.audit_chain_check()
        return {
            "ok": integrity == ["ok"] and not foreign_keys and audit_chain["ok"],
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "journal_mode": journal_mode,
            "audit_chain": audit_chain,
        }

    def backup(self, destination: str | Path) -> Path:
        """Create a transactionally consistent SQLite backup."""
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(sqlite3.connect(target)) as backup_connection:
            self._connection.backup(backup_connection)
        if os.name == "posix":
            target.chmod(0o600)
        return target

    def _migrate(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            definition TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS work_items (
            id TEXT PRIMARY KEY,
            parent_id TEXT REFERENCES work_items(id),
            item_type TEXT NOT NULL,
            workflow_id TEXT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            owner_id TEXT NOT NULL,
            reviewer_id TEXT,
            state TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 3,
            deadline TEXT,
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK (budget_cents >= 0),
            spent_cents INTEGER NOT NULL DEFAULT 0 CHECK (spent_cents >= 0),
            risk TEXT NOT NULL DEFAULT 'low',
            action_type TEXT NOT NULL DEFAULT 'internal_work',
            success_metric TEXT NOT NULL DEFAULT '',
            acceptance_criteria TEXT NOT NULL DEFAULT '[]',
            dependencies TEXT NOT NULL DEFAULT '[]',
            evidence TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_work_parent ON work_items(parent_id);
        CREATE INDEX IF NOT EXISTS idx_work_state ON work_items(state);
        CREATE INDEX IF NOT EXISTS idx_work_owner ON work_items(owner_id);

        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES work_items(id),
            action_type TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            decided_by TEXT,
            reason TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            payload_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_approval_per_task
            ON approvals(task_id) WHERE status = 'pending';

        CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

        CREATE TABLE IF NOT EXISTS audit_logs (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            prev_hash TEXT NOT NULL DEFAULT '',
            entry_hash TEXT NOT NULL DEFAULT '',
            entry_signature TEXT NOT NULL DEFAULT '',
            signature_key_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge (
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            sensitivity TEXT NOT NULL DEFAULT 'internal',
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(namespace, key)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY,
            decision TEXT NOT NULL,
            context TEXT NOT NULL,
            options TEXT NOT NULL,
            chosen_option TEXT NOT NULL,
            reason TEXT NOT NULL,
            owner TEXT NOT NULL,
            review_date TEXT,
            outcome TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS costs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES work_items(id),
            agent_id TEXT NOT NULL,
            category TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
            units REAL NOT NULL DEFAULT 0,
            unit_name TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cost_task ON costs(task_id);

        CREATE TABLE IF NOT EXISTS execution_runs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES work_items(id),
            worker_id TEXT NOT NULL,
            attempt INTEGER NOT NULL CHECK(attempt > 0),
            state TEXT NOT NULL,
            lease_until TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_execution_runs_task ON execution_runs(task_id, attempt);
        CREATE INDEX IF NOT EXISTS idx_execution_runs_state_lease ON execution_runs(state, lease_until);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_execution_per_task
            ON execution_runs(task_id) WHERE state IN ('leased', 'running');

        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_segment TEXT NOT NULL,
            offer TEXT NOT NULL,
            minimum_score INTEGER NOT NULL DEFAULT 70 CHECK(minimum_score BETWEEN 0 AND 100),
            active INTEGER NOT NULL DEFAULT 1,
            daily_lead_limit INTEGER NOT NULL DEFAULT 10 CHECK(daily_lead_limit BETWEEN 1 AND 100),
            daily_outreach_limit INTEGER NOT NULL DEFAULT 3 CHECK(daily_outreach_limit BETWEEN 0 AND 50),
            daily_followup_limit INTEGER NOT NULL DEFAULT 5 CHECK(daily_followup_limit BETWEEN 0 AND 100),
            maximum_followups INTEGER NOT NULL DEFAULT 2 CHECK(maximum_followups BETWEEN 0 AND 5),
            config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(id),
            company_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            contact_name TEXT NOT NULL DEFAULT '',
            public_contact TEXT NOT NULL DEFAULT '',
            contact_source_url TEXT NOT NULL DEFAULT '',
            linkedin_url TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT 'discovered',
            total_score INTEGER NOT NULL DEFAULT 0 CHECK(total_score BETWEEN 0 AND 100),
            score_components TEXT NOT NULL DEFAULT '{}',
            do_not_contact INTEGER NOT NULL DEFAULT 0,
            opt_out_reason TEXT NOT NULL DEFAULT '',
            estimated_value_cents INTEGER NOT NULL DEFAULT 0 CHECK(estimated_value_cents >= 0),
            next_action TEXT NOT NULL DEFAULT '',
            next_action_at TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(domain)
        );
        CREATE INDEX IF NOT EXISTS idx_leads_campaign_stage ON leads(campaign_id, stage);
        CREATE INDEX IF NOT EXISTS idx_leads_next_action ON leads(next_action_at);

        CREATE TABLE IF NOT EXISTS lead_evidence (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL REFERENCES leads(id),
            claim_type TEXT NOT NULL,
            claim TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_excerpt TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(lead_id, claim_type, source_url, content_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_lead ON lead_evidence(lead_id);

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL REFERENCES leads(id),
            channel TEXT NOT NULL,
            message_type TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            recipient TEXT NOT NULL DEFAULT '',
            approved_payload_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            approved_by TEXT,
            approved_at TEXT,
            sent_at TEXT,
            external_message_id TEXT,
            thread_id TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            evidence_snapshot TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external_id ON messages(external_message_id)
            WHERE external_message_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS pipeline_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT REFERENCES leads(id),
            campaign_id TEXT REFERENCES campaigns(id),
            event_type TEXT NOT NULL,
            agent TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            output TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_events_lead ON pipeline_events(lead_id, sequence);

        CREATE TABLE IF NOT EXISTS idempotency_records (
            idempotency_key TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            result_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS system_controls (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS company_objectives (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            objective TEXT NOT NULL,
            department TEXT NOT NULL,
            workflow_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
            success_metric TEXT NOT NULL,
            target_value REAL,
            current_value REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            cadence TEXT NOT NULL DEFAULT 'weekly',
            inputs TEXT NOT NULL DEFAULT '{}',
            max_active_programmes INTEGER NOT NULL DEFAULT 1 CHECK(max_active_programmes BETWEEN 1 AND 20),
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            deadline TEXT,
            last_planned_key TEXT NOT NULL DEFAULT '',
            last_planned_at TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_objectives_status_priority
            ON company_objectives(status, priority, updated_at);
        CREATE INDEX IF NOT EXISTS idx_objectives_workflow
            ON company_objectives(workflow_key, status);

        CREATE TABLE IF NOT EXISTS objective_updates (
            id TEXT PRIMARY KEY,
            objective_id TEXT NOT NULL REFERENCES company_objectives(id) ON DELETE CASCADE,
            previous_value REAL NOT NULL,
            new_value REAL NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            actor TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_objective_updates_objective
            ON objective_updates(objective_id, created_at);

        CREATE TABLE IF NOT EXISTS objective_cadence_runs (
            objective_id TEXT NOT NULL REFERENCES company_objectives(id) ON DELETE CASCADE,
            cadence_key TEXT NOT NULL,
            programme_id TEXT,
            status TEXT NOT NULL DEFAULT 'claimed',
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(objective_id, cadence_key)
        );
        CREATE INDEX IF NOT EXISTS idx_objective_cadence_runs_created
            ON objective_cadence_runs(created_at, status);

        CREATE TABLE IF NOT EXISTS content_campaigns (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            audience TEXT NOT NULL,
            business_objective TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS content_assets (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES content_campaigns(id),
            asset_type TEXT NOT NULL,
            uri TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            source_url TEXT NOT NULL DEFAULT '',
            creator TEXT NOT NULL DEFAULT '',
            licence TEXT NOT NULL DEFAULT '',
            asset_metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(campaign_id, asset_type, sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_content_assets_campaign ON content_assets(campaign_id);

        CREATE TABLE IF NOT EXISTS content_metrics (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES content_campaigns(id),
            platform TEXT NOT NULL,
            window TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            metrics TEXT NOT NULL,
            UNIQUE(campaign_id, platform, window)
        );

        CREATE TABLE IF NOT EXISTS content_lessons (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES content_campaigns(id),
            lesson TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS distribution_publications (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES content_campaigns(id),
            task_id TEXT NOT NULL REFERENCES work_items(id),
            platform TEXT NOT NULL,
            account_ref TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            asset_ids TEXT NOT NULL DEFAULT '[]',
            payload_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            scheduled_at TEXT,
            outbox_event_id TEXT,
            external_id TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            provider_status TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_distribution_status_schedule
            ON distribution_publications(status, scheduled_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_distribution_campaign
            ON distribution_publications(campaign_id, created_at);

        CREATE TABLE IF NOT EXISTS venture_opportunities (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            problem TEXT NOT NULL,
            target_user TEXT NOT NULL,
            product_type TEXT NOT NULL,
            source TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '[]',
            score_components TEXT NOT NULL DEFAULT '{}',
            total_score INTEGER NOT NULL DEFAULT 0 CHECK(total_score BETWEEN 0 AND 100),
            estimated_build_days INTEGER NOT NULL DEFAULT 14 CHECK(estimated_build_days BETWEEN 1 AND 14),
            monetization TEXT NOT NULL,
            distribution_channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'discovered',
            strategic_fit TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(title, target_user)
        );
        CREATE INDEX IF NOT EXISTS idx_venture_opportunity_status_score
            ON venture_opportunities(status, total_score DESC);

        CREATE TABLE IF NOT EXISTS venture_experiments (
            id TEXT PRIMARY KEY,
            opportunity_id TEXT NOT NULL REFERENCES venture_opportunities(id),
            product_name TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'planned',
            timebox_days INTEGER NOT NULL DEFAULT 14 CHECK(timebox_days BETWEEN 1 AND 14),
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            spent_cents INTEGER NOT NULL DEFAULT 0 CHECK(spent_cents >= 0),
            primary_metric TEXT NOT NULL,
            target_value REAL NOT NULL,
            kill_threshold REAL NOT NULL,
            current_value REAL NOT NULL DEFAULT 0,
            recommendation TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            programme_id TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            started_at TEXT,
            deadline TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_venture_experiment_stage
            ON venture_experiments(stage, deadline);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_venture_build
            ON venture_experiments((1)) WHERE stage IN ('building','launching');

        CREATE TABLE IF NOT EXISTS venture_sprint_slots (
            slot_number INTEGER PRIMARY KEY CHECK(slot_number > 0),
            experiment_id TEXT NOT NULL UNIQUE REFERENCES venture_experiments(id) ON DELETE CASCADE,
            acquired_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS venture_metric_events (
            id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL REFERENCES venture_experiments(id),
            metric_name TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '[]',
            captured_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_venture_metrics_experiment
            ON venture_metric_events(experiment_id, captured_at);

        CREATE TABLE IF NOT EXISTS venture_cashflow_streams (
            id TEXT PRIMARY KEY,
            opportunity_id TEXT NOT NULL REFERENCES venture_opportunities(id),
            experiment_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            lane TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            offer TEXT NOT NULL,
            target_user TEXT NOT NULL,
            distribution_channel TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            price_cents INTEGER NOT NULL DEFAULT 0 CHECK(price_cents >= 0),
            unit_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost_cents >= 0),
            founder_minutes_per_week INTEGER NOT NULL DEFAULT 0 CHECK(founder_minutes_per_week >= 0),
            automation_level INTEGER NOT NULL DEFAULT 0 CHECK(automation_level BETWEEN 0 AND 100),
            launch_url TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_venture_cashflow_status
            ON venture_cashflow_streams(status, lane, created_at);

        CREATE TABLE IF NOT EXISTS venture_financial_events (
            id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL REFERENCES venture_cashflow_streams(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
            currency TEXT NOT NULL,
            source TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '[]',
            trust_level TEXT NOT NULL DEFAULT 'unverified',
            provider TEXT NOT NULL DEFAULT '',
            external_event_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_venture_financial_stream_time
            ON venture_financial_events(stream_id, occurred_at);

        CREATE TABLE IF NOT EXISTS venture_cashflow_actions (
            id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL DEFAULT '',
            action_type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
            requires_founder_approval INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL DEFAULT '{}',
            payload_hash TEXT NOT NULL DEFAULT '',
            approval_id TEXT NOT NULL DEFAULT '',
            approval_task_id TEXT NOT NULL DEFAULT '',
            mission_id TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '{}',
            due_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_venture_cashflow_actions_status
            ON venture_cashflow_actions(status, priority, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_venture_cashflow_one_active_action
            ON venture_cashflow_actions(stream_id, action_type)
            WHERE status IN ('proposed','approved','running','blocked');

        CREATE TABLE IF NOT EXISTS review_attestations (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES work_items(id),
            reviewer_id TEXT NOT NULL,
            reviewer_model TEXT NOT NULL,
            submission_sha256 TEXT NOT NULL,
            decision TEXT NOT NULL,
            signature TEXT NOT NULL,
            attestation TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_review_attestations_task
            ON review_attestations(task_id, created_at);

        CREATE TABLE IF NOT EXISTS operational_metrics (
            name TEXT NOT NULL,
            labels_key TEXT NOT NULL,
            labels TEXT NOT NULL DEFAULT '{}',
            value REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(name, labels_key)
        );

        CREATE TABLE IF NOT EXISTS operational_traces (
            id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            outcome TEXT NOT NULL,
            duration_ms REAL NOT NULL CHECK(duration_ms >= 0),
            attributes TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_operational_traces_created
            ON operational_traces(created_at);

        CREATE TABLE IF NOT EXISTS operational_alerts (
            id TEXT PRIMARY KEY,
            severity TEXT NOT NULL,
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            resource_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_operational_alerts_status
            ON operational_alerts(status, created_at);

        CREATE TABLE IF NOT EXISTS company_signals (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            signal_type TEXT NOT NULL,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            department TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            programme_id TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            claimed_by TEXT NOT NULL DEFAULT '',
            claim_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_company_signals_status
            ON company_signals(status, severity, created_at);
        CREATE INDEX IF NOT EXISTS idx_company_signals_type
            ON company_signals(signal_type, created_at);

        CREATE TABLE IF NOT EXISTS autonomy_runs (
            id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_autonomy_runs_started
            ON autonomy_runs(started_at DESC);

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inbound_messages (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            lead_id TEXT REFERENCES leads(id),
            sender TEXT NOT NULL DEFAULT '',
            recipient TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            classification TEXT NOT NULL DEFAULT '{}',
            raw_metadata TEXT NOT NULL DEFAULT '{}',
            content_hash TEXT NOT NULL,
            received_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_messages(status, received_at);
        CREATE INDEX IF NOT EXISTS idx_inbound_lead ON inbound_messages(lead_id, received_at);
        CREATE INDEX IF NOT EXISTS idx_inbound_thread ON inbound_messages(provider, thread_id);

        CREATE TABLE IF NOT EXISTS integration_cursors (
            provider TEXT PRIMARY KEY,
            cursor TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS integration_actions (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            operation TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            payload_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            risk TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'awaiting_approval',
            requested_by TEXT NOT NULL,
            approved_by TEXT,
            approved_at TEXT,
            outbox_event_id TEXT,
            receipt TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(outbox_event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_integration_actions_status
            ON integration_actions(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_integration_actions_provider
            ON integration_actions(provider, operation, created_at);

        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'closed',
            consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
            last_success_at TEXT,
            last_failure_at TEXT,
            circuit_open_until TEXT,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL DEFAULT '',
            client_name TEXT NOT NULL,
            client_email TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'INR',
            amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
            tax_minor INTEGER NOT NULL DEFAULT 0 CHECK(tax_minor >= 0),
            line_items TEXT NOT NULL DEFAULT '[]',
            due_date TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            payment_uri TEXT NOT NULL DEFAULT '',
            document_path TEXT NOT NULL DEFAULT '',
            payload_hash TEXT NOT NULL,
            payment_reference TEXT NOT NULL DEFAULT '',
            status_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status, due_date);

        CREATE TABLE IF NOT EXISTS invoice_status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL REFERENCES invoices(id),
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            actor TEXT NOT NULL,
            reference TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_status_events
            ON invoice_status_events(invoice_id, id);

            CREATE TABLE IF NOT EXISTS outbox_events (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
                worker_id TEXT NOT NULL DEFAULT '',
                lease_until TEXT,
                next_attempt_at TEXT,
                receipt TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                processed_at TEXT
            );
        """
        with self._lock:
            self._connection.executescript(schema)
            self._ensure_column("approvals", "payload_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("approvals", "expires_at", "TEXT")
            self._ensure_column("audit_logs", "prev_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("audit_logs", "entry_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("audit_logs", "entry_signature", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("audit_logs", "signature_key_id", "TEXT NOT NULL DEFAULT ''")
            # P0-6: bind recipient and payload hash to message at staging time
            self._ensure_column("messages", "recipient", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("messages", "approved_payload_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("outbox_events", "attempt", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("outbox_events", "worker_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("outbox_events", "lease_until", "TEXT")
            self._ensure_column("outbox_events", "next_attempt_at", "TEXT")

            # Create indexes after ensuring columns exist
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status, next_attempt_at, created_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_lease ON outbox_events(status, lease_until)"
            )
            self._ensure_column("outbox_events", "receipt", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column("outbox_events", "updated_at", "TEXT")
            self._ensure_column("invoices", "idempotency_key", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("invoices", "payment_reference", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("invoices", "status_reason", "TEXT NOT NULL DEFAULT ''")
            # v5.4 Ventures trust/execution linkage. Existing rows remain readable
            # but are explicitly unverified/unlinked until reconciled.
            self._ensure_column("venture_financial_events", "trust_level", "TEXT NOT NULL DEFAULT 'unverified'")
            self._ensure_column("venture_financial_events", "provider", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("venture_financial_events", "external_event_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("venture_cashflow_actions", "payload_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("venture_cashflow_actions", "approval_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("venture_cashflow_actions", "approval_task_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("venture_cashflow_actions", "mission_id", "TEXT NOT NULL DEFAULT ''")
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_idempotency "
                "ON invoices(idempotency_key) WHERE idempotency_key <> ''"
            )
            self._backfill_approval_integrity()
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (360, "free_first_integrations", utc_now()),
            )
            self._initialize_or_validate_audit_hash_chain()
            self._commit_if_needed()

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def canonical_hash(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _backfill_approval_integrity(self) -> None:
        rows = self._connection.execute(
            "SELECT id,payload,payload_hash,created_at,expires_at FROM approvals"
        ).fetchall()
        for row in rows:
            changes: dict[str, str] = {}
            if not row["payload_hash"]:
                try:
                    payload = json.loads(row["payload"])
                except json.JSONDecodeError:
                    payload = row["payload"]
                changes["payload_hash"] = self.canonical_hash(payload)
            if not row["expires_at"]:
                created_at = datetime.fromisoformat(row["created_at"])
                changes["expires_at"] = (created_at + timedelta(hours=48)).isoformat()
            if changes:
                self._connection.execute(
                    f"UPDATE approvals SET {', '.join(f'{key}=?' for key in changes)} WHERE id=?",
                    [*changes.values(), row["id"]],
                )

    @staticmethod
    def _audit_digest(
        *,
        previous: str,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        details_json: str,
        created_at: str,
    ) -> str:
        entry = {
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
            "details": details_json,
            "created_at": created_at,
        }
        payload = previous + json.dumps(entry, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _audit_key() -> bytes:
        return os.environ.get("AMAURA_AUDIT_HMAC_KEY", "").encode("utf-8")

    @classmethod
    def _audit_signature(cls, entry_hash: str) -> str:
        key = cls._audit_key()
        if len(key) < 32:
            return ""
        return hmac.new(key, entry_hash.encode("ascii"), hashlib.sha256).hexdigest()

    @staticmethod
    def _audit_key_id() -> str:
        explicit = os.environ.get("AMAURA_AUDIT_KEY_ID", "").strip()
        if explicit:
            return explicit
        key = os.environ.get("AMAURA_AUDIT_HMAC_KEY", "").encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:16] if len(key) >= 32 else ""

    def _checkpoint_path(self) -> Path | None:
        if self._audit_checkpoint_path_override is not None:
            return self._audit_checkpoint_path_override
        configured = os.environ.get("AMAURA_AUDIT_CHECKPOINT_PATH", "").strip()
        if not configured:
            return None
        return Path(configured).expanduser().resolve()

    def _initialize_empty_audit_checkpoint(self) -> None:
        """Anchor a newly created strict-audit store without masking history.

        A missing checkpoint is a real integrity failure once an audit history
        exists.  For a brand-new database, though, creating the signed
        sequence-zero anchor is the only safe way to satisfy the configured
        external-checkpoint contract; no historical state is reconstructed.
        """
        if os.environ.get("AMAURA_STRICT_AUDIT_CHECKPOINT", "0") != "1":
            return
        checkpoint = self._checkpoint_path()
        if checkpoint is None or checkpoint.is_file():
            return
        count = int(self._connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0])
        if count == 0:
            self._write_external_audit_checkpoint(
                sequence=0,
                head="",
                signature=self._audit_signature(""),
                key_id=self._audit_key_id(),
            )

    def _validate_external_audit_checkpoint_on_open(self) -> None:
        """Fail closed when an external audit anchor proves DB rollback.

        The database commit happens before the external checkpoint update, so a
        checkpoint may legitimately lag the database during concurrent writers.
        The reverse cannot occur in the normal append protocol: a checkpoint
        ahead of the durable database is rollback evidence.
        """
        if os.environ.get("AMAURA_REQUIRE_EXTERNAL_AUDIT_CHECKPOINT", "0") != "1":
            return

        checkpoint = self._checkpoint_path()
        if checkpoint is None or not checkpoint.is_file():
            raise RuntimeError("Audit integrity failure: required external checkpoint is missing")

        lock_path = checkpoint.with_suffix(checkpoint.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+b") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                try:
                    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                    checkpoint_sequence = int(saved.get("sequence", -1))
                except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
                    raise RuntimeError("Audit integrity failure: external checkpoint is invalid") from exc

                if checkpoint_sequence < 0:
                    raise RuntimeError("Audit integrity failure: external checkpoint sequence is invalid")

                row = self._connection.execute(
                    "SELECT sequence,entry_hash FROM audit_logs ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                database_sequence = int(row["sequence"]) if row is not None else 0
                if checkpoint_sequence > database_sequence:
                    raise RuntimeError(
                        "Audit integrity failure: external checkpoint is ahead of the database; "
                        "possible database rollback detected"
                    )

                if checkpoint_sequence == 0:
                    anchored_head = ""
                else:
                    anchor = self._connection.execute(
                        "SELECT entry_hash FROM audit_logs WHERE sequence=?", (checkpoint_sequence,)
                    ).fetchone()
                    if anchor is None:
                        raise RuntimeError(
                            "Audit integrity failure: external checkpoint references a missing audit row"
                        )
                    anchored_head = str(anchor["entry_hash"])

                checkpoint_head = str(saved.get("head", ""))
                if not hmac.compare_digest(checkpoint_head, anchored_head):
                    raise RuntimeError("Audit integrity failure: external checkpoint head does not match audit history")

                checkpoint_signature = str(saved.get("signature", ""))
                expected_signature = self._audit_signature(checkpoint_head)
                if checkpoint_signature:
                    if not expected_signature or not hmac.compare_digest(checkpoint_signature, expected_signature):
                        raise RuntimeError("Audit integrity failure: external checkpoint signature is invalid")
                elif os.environ.get("AMAURA_STRICT_AUDIT_SIGNATURES", "0") == "1":
                    raise RuntimeError("Audit integrity failure: external checkpoint signature is missing")
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass

    def _write_external_audit_checkpoint(self, *, sequence: int, head: str, signature: str, key_id: str) -> None:
        target = self._checkpoint_path()
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = target.with_suffix(target.suffix + ".lock")
        payload = {"sequence": int(sequence), "head": head, "signature": signature, "key_id": key_id}
        with open(lock_path, "a+b") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            current_sequence = -1
            if target.is_file():
                try:
                    current_sequence = int(json.loads(target.read_text(encoding="utf-8")).get("sequence", -1))
                except (OSError, ValueError, json.JSONDecodeError, TypeError):
                    current_sequence = -1
            if sequence >= current_sequence:
                fd, temporary_name = tempfile.mkstemp(prefix=".audit-head-", dir=target.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_name, target)
                finally:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass

    def _initialize_or_validate_audit_hash_chain(self) -> None:
        """Validate existing audit integrity and never silently re-sign history.

        Historical unsigned databases may be migrated only through an explicit
        one-time maintenance mode.  Partially stripped integrity metadata is
        always treated as corruption because automatically reconstructing it
        would let a database attacker rewrite and re-sign history on restart.
        """
        rows = self._connection.execute("SELECT * FROM audit_logs ORDER BY sequence").fetchall()
        if not rows:
            return

        fully_unsigned = all(
            not row["prev_hash"]
            and not row["entry_hash"]
            and not row["entry_signature"]
            and not row["signature_key_id"]
            for row in rows
        )
        hash_chain_only = all(
            bool(row["entry_hash"]) and not row["entry_signature"] and not row["signature_key_id"] for row in rows
        )
        fully_signed = all(
            bool(row["entry_hash"]) and bool(row["entry_signature"]) and bool(row["signature_key_id"]) for row in rows
        )

        if hash_chain_only or fully_signed:
            check = self._audit_chain_check_rows(
                rows,
                require_checkpoint=False,
                enforce_strict=not (
                    hash_chain_only and os.environ.get("AMAURA_ALLOW_LEGACY_AUDIT_MIGRATION", "0") == "1"
                ),
            )
            if not check["ok"]:
                self._audit_integrity_fault = (
                    f"Audit history integrity failure at sequence {check.get('broken_at_sequence')}: "
                    f"{check.get('reason', 'unknown')}"
                )
                return
            # Older hardened stores may already have an intact hash chain but
            # predate per-entry signatures.  Signing that history is safe only
            # after validating the chain and only through the explicit,
            # one-time controlled migration switch.
            if os.environ.get("AMAURA_ALLOW_LEGACY_AUDIT_MIGRATION", "0") == "1":
                if len(self._audit_key()) < 32:
                    raise RuntimeError("Legacy audit migration requires AMAURA_AUDIT_HMAC_KEY of at least 32 bytes")
                if self._checkpoint_path() is None:
                    raise RuntimeError("Legacy audit migration requires AMAURA_AUDIT_CHECKPOINT_PATH")
                key_id = self._audit_key_id()
                if hash_chain_only:
                    for row in rows:
                        self._connection.execute(
                            "UPDATE audit_logs SET entry_signature=?, signature_key_id=? WHERE sequence=?",
                            (self._audit_signature(str(row["entry_hash"])), key_id, row["sequence"]),
                        )
                    self._connection.commit()
                self._write_external_audit_checkpoint(
                    sequence=int(rows[-1]["sequence"]),
                    head=str(rows[-1]["entry_hash"]),
                    signature=self._audit_signature(str(rows[-1]["entry_hash"])),
                    key_id=key_id,
                )
            return

        if not fully_unsigned:
            self._audit_integrity_fault = (
                "Audit history contains missing, mixed, or partially stripped integrity metadata; "
                "automatic repair is forbidden"
            )
            return

        checkpoint = self._checkpoint_path()
        if checkpoint and checkpoint.is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                saved = {}
            if int(saved.get("sequence", 0) or 0) > 0 or str(saved.get("head", "")):
                self._audit_integrity_fault = (
                    "Audit integrity metadata was stripped while an external checkpoint exists; "
                    "automatic repair is forbidden"
                )
                return

        if os.environ.get("AMAURA_ALLOW_LEGACY_AUDIT_MIGRATION", "0") != "1":
            raise RuntimeError(
                "Unsigned legacy audit history requires explicit migration. Set "
                "AMAURA_ALLOW_LEGACY_AUDIT_MIGRATION=1 only during a controlled, "
                "offline migration with a verified backup and external checkpoint."
            )
        if len(self._audit_key()) < 32:
            raise RuntimeError("Legacy audit migration requires AMAURA_AUDIT_HMAC_KEY of at least 32 bytes")
        if self._checkpoint_path() is None:
            raise RuntimeError("Legacy audit migration requires AMAURA_AUDIT_CHECKPOINT_PATH")

        previous = ""
        key_id = self._audit_key_id()
        for row in rows:
            entry_hash = self._audit_digest(
                previous=previous,
                actor=row["actor"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                outcome=row["outcome"],
                details_json=row["details"],
                created_at=row["created_at"],
            )
            signature = self._audit_signature(entry_hash)
            self._connection.execute(
                "UPDATE audit_logs SET prev_hash=?,entry_hash=?,entry_signature=?,signature_key_id=? WHERE sequence=?",
                (previous, entry_hash, signature, key_id, row["sequence"]),
            )
            previous = entry_hash
        self._write_external_audit_checkpoint(
            sequence=int(rows[-1]["sequence"]),
            head=previous,
            signature=self._audit_signature(previous),
            key_id=key_id,
        )

    def _audit_chain_check_rows(
        self,
        rows: list[sqlite3.Row],
        *,
        require_checkpoint: bool,
        enforce_strict: bool = True,
    ) -> dict[str, Any]:
        previous = ""
        key = self._audit_key()
        require_signatures = enforce_strict and os.environ.get("AMAURA_STRICT_AUDIT_SIGNATURES", "0") == "1"
        require_checkpoint = bool(require_checkpoint)
        signed_entries = 0
        for row in rows:
            expected = self._audit_digest(
                previous=previous,
                actor=row["actor"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                outcome=row["outcome"],
                details_json=row["details"],
                created_at=row["created_at"],
            )
            if row["prev_hash"] != previous or row["entry_hash"] != expected:
                return {
                    "ok": False,
                    "broken_at_sequence": row["sequence"],
                    "entries": len(rows),
                    "reason": "hash_chain_mismatch",
                }
            signature = str(row["entry_signature"] or "")
            if signature:
                signed_entries += 1
                if len(key) < 32 or not hmac.compare_digest(signature, self._audit_signature(expected)):
                    return {
                        "ok": False,
                        "broken_at_sequence": row["sequence"],
                        "entries": len(rows),
                        "reason": "signature_invalid",
                    }
            elif require_signatures:
                return {
                    "ok": False,
                    "broken_at_sequence": row["sequence"],
                    "entries": len(rows),
                    "reason": "signature_missing",
                }
            previous = row["entry_hash"]
        if not require_checkpoint:
            return {
                "ok": True,
                "broken_at_sequence": None,
                "entries": len(rows),
                "head": previous,
                "signed_entries": signed_entries,
                "checkpoint_ok": True,
                "reason": "",
            }
        checkpoint_ok = True
        checkpoint_reason = ""
        checkpoint = self._checkpoint_path()
        if checkpoint and checkpoint.is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                checkpoint_ok = int(saved.get("sequence", -1)) == (
                    int(rows[-1]["sequence"]) if rows else 0
                ) and hmac.compare_digest(str(saved.get("head", "")), previous)
                if saved.get("signature"):
                    checkpoint_ok = checkpoint_ok and hmac.compare_digest(
                        str(saved["signature"]), self._audit_signature(previous)
                    )
                checkpoint_reason = "" if checkpoint_ok else "external_checkpoint_mismatch"
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                checkpoint_ok = False
                checkpoint_reason = "external_checkpoint_invalid"
        elif enforce_strict and os.environ.get("AMAURA_REQUIRE_EXTERNAL_AUDIT_CHECKPOINT", "0") == "1":
            checkpoint_ok = False
            checkpoint_reason = "external_checkpoint_missing"
        return {
            "ok": checkpoint_ok,
            "broken_at_sequence": None if checkpoint_ok else (int(rows[-1]["sequence"]) if rows else 0),
            "entries": len(rows),
            "head": previous,
            "signed_entries": signed_entries,
            "checkpoint_ok": checkpoint_ok,
            "reason": checkpoint_reason,
        }

    def audit_chain_check(self) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM audit_logs ORDER BY sequence").fetchall()
        return self._audit_chain_check_rows(rows, require_checkpoint=True)

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in CompanyStore.JSON_COLUMNS | {"definition", "evidence_refs", "options"}:
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except json.JSONDecodeError:
                    pass
        if "enabled" in result:
            result["enabled"] = bool(result["enabled"])
        for key in ("active", "do_not_contact"):
            if key in result:
                result[key] = bool(result[key])
        return result

    def upsert_agent(self, definition: dict[str, Any]) -> None:
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO agents(agent_id, name, department, definition, enabled, updated_at)
                VALUES(?, ?, ?, ?, 1, ?)
                ON CONFLICT(agent_id) DO UPDATE SET name=excluded.name,
                department=excluded.department, definition=excluded.definition, updated_at=excluded.updated_at""",
                (definition["agent_id"], definition["name"], definition["department"], json.dumps(definition), now),
            )
            self._commit_if_needed()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM agents ORDER BY department, name").fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown Amaura agent: {agent_id}")
        return decoded

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE agents SET enabled = ?, updated_at = ? WHERE agent_id = ?", (int(enabled), utc_now(), agent_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown Amaura agent: {agent_id}")
            self._commit_if_needed()
        return self.get_agent(agent_id)

    def insert_work_item(self, item: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "parent_id": None,
            "workflow_id": None,
            "description": "",
            "reviewer_id": None,
            "state": "assigned",
            "priority": 3,
            "deadline": None,
            "budget_cents": 0,
            "spent_cents": 0,
            "risk": "low",
            "action_type": "internal_work",
            "success_metric": "",
            "acceptance_criteria": [],
            "dependencies": [],
            "evidence": [],
            "summary": "",
            "metadata": {},
            **item,
        }
        columns = (
            "id",
            "parent_id",
            "item_type",
            "workflow_id",
            "title",
            "description",
            "owner_id",
            "reviewer_id",
            "state",
            "priority",
            "deadline",
            "budget_cents",
            "spent_cents",
            "risk",
            "action_type",
            "success_metric",
            "acceptance_criteria",
            "dependencies",
            "evidence",
            "summary",
            "metadata",
            "created_at",
            "updated_at",
        )
        values["created_at"] = now
        values["updated_at"] = now
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        placeholders = ", ".join("?" for _ in columns)
        with self._lock:
            self._connection.execute(f"INSERT INTO work_items({', '.join(columns)}) VALUES({placeholders})", encoded)
            if self._autocommit:
                self._commit_if_needed()
        return self.get_work_item(values["id"])

    def get_work_item(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown work item: {item_id}")
        return decoded

    def list_work_items(
        self,
        *,
        item_type: str | None = None,
        state: str | None = None,
        owner_id: str | None = None,
        parent_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("item_type", item_type),
            ("state", state),
            ("owner_id", owner_id),
            ("parent_id", parent_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM work_items{where} ORDER BY priority ASC, created_at ASC LIMIT ?", params
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_work_item(self, item_id: str, **fields: Any) -> dict[str, Any]:
        invalid = set(fields) - self.MUTABLE_WORK_FIELDS
        if invalid:
            raise ValueError(f"Invalid work-item fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_work_item(item_id)
        fields["updated_at"] = utc_now()
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            params.append(json.dumps(value) if key in self.JSON_COLUMNS else value)
        params.append(item_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE work_items SET {', '.join(assignments)} WHERE id = ?", params)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown work item: {item_id}")
            self._commit_if_needed()
        return self.get_work_item(item_id)

    def create_approval(self, approval: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "status": "pending",
            "decided_by": None,
            "reason": "",
            "payload": {},
            "expires_at": (datetime.now(UTC) + timedelta(hours=48)).isoformat(),
            **approval,
        }
        payload_json = json.dumps(values["payload"], sort_keys=True, separators=(",", ":"), default=str)
        payload_hash = self.canonical_hash(values["payload"])
        with self._lock:
            try:
                self._connection.execute(
                    """INSERT INTO approvals(id, task_id, action_type, risk, status, requested_by,
                    decided_by, reason, payload, payload_hash, created_at, expires_at, resolved_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                    (
                        values["id"],
                        values["task_id"],
                        values["action_type"],
                        values["risk"],
                        values["status"],
                        values["requested_by"],
                        values["decided_by"],
                        values["reason"],
                        payload_json,
                        payload_hash,
                        now,
                        values["expires_at"],
                    ),
                )
                self._commit_if_needed()
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                if "approvals.task_id" in str(exc):
                    existing = self._connection.execute(
                        "SELECT id FROM approvals WHERE task_id=? AND status='pending'", (values["task_id"],)
                    ).fetchone()
                    if existing:
                        return self.get_approval(existing["id"])
                raise
        return self.get_approval(values["id"])

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown approval: {approval_id}")
        return decoded

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM approvals"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def expire_stale_approvals(self) -> int:
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE approvals SET status='expired',resolved_at=?
                WHERE status='pending' AND expires_at IS NOT NULL AND expires_at<=?""",
                (utc_now(), utc_now()),
            )
            self._commit_if_needed()
        return cursor.rowcount

    def resolve_approval(self, approval_id: str, status: str, decided_by: str, reason: str) -> dict[str, Any]:
        with self._lock:
            current = self._connection.execute(
                "SELECT status,expires_at FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"Unknown approval: {approval_id}")
            if current["status"] != "pending":
                raise ValueError(f"Approval is already {current['status']}")
            if current["expires_at"] and datetime.fromisoformat(current["expires_at"]) <= datetime.now(UTC):
                self._connection.execute(
                    "UPDATE approvals SET status='expired',resolved_at=? WHERE id=? AND status='pending'",
                    (utc_now(), approval_id),
                )
                self._commit_if_needed()
                raise ValueError("Approval has expired and must be requested again")
            cursor = self._connection.execute(
                """UPDATE approvals SET status = ?, decided_by = ?, reason = ?, resolved_at = ?
                WHERE id = ? AND status = 'pending'""",
                (status, decided_by, reason, utc_now(), approval_id),
            )
            if cursor.rowcount != 1:
                latest = self.get_approval(approval_id)
                raise ValueError(f"Approval is already {latest['status']}")
            self._commit_if_needed()
        return self.get_approval(approval_id)

    def publish_event(self, event_type: str, aggregate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        created_at = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO events(event_type, aggregate_id, payload, created_at) VALUES(?, ?, ?, ?)",
                (event_type, aggregate_id, json.dumps(payload), created_at),
            )
            self._commit_if_needed()
        return {
            "sequence": cursor.lastrowid,
            "event_type": event_type,
            "aggregate_id": aggregate_id,
            "payload": payload,
            "created_at": created_at,
        }

    def enqueue_outbox_event(
        self, provider: str, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        """Enqueue one idempotent provider operation for durable dispatch."""
        now = utc_now()
        event_id = f"outbox_{uuid.uuid4().hex[:16]}"
        with self._lock:
            try:
                self._connection.execute(
                    """INSERT INTO outbox_events(
                    id,idempotency_key,provider,operation,payload,status,error,attempt,
                    worker_id,lease_until,next_attempt_at,receipt,created_at,updated_at
                    ) VALUES(?,?,?,?,?,'pending','',0,'',NULL,?, '{}',?,?)""",
                    (
                        event_id,
                        idempotency_key,
                        provider,
                        operation,
                        json.dumps(payload),
                        now,
                        now,
                        now,
                    ),
                )
                self._commit_if_needed()
            except sqlite3.IntegrityError:
                row = self._connection.execute(
                    "SELECT * FROM outbox_events WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    return self._decode_row(row)  # type: ignore[return-value]
                raise
        return self.get_outbox_event(event_id)

    def get_outbox_event(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM outbox_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown outbox event: {event_id}")
        return decoded

    def recover_expired_outbox_events(self) -> list[dict[str, Any]]:
        """Return abandoned provider leases to the pending queue."""
        now = utc_now()
        with self.atomic_block():
            rows = self._connection.execute(
                """SELECT * FROM outbox_events
                WHERE status='processing' AND lease_until IS NOT NULL AND lease_until<=?
                ORDER BY created_at""",
                (now,),
            ).fetchall()
            for row in rows:
                ambiguous_external = requires_reconciliation_after_lease_expiry(str(row["operation"]))
                status = "reconciliation_required" if ambiguous_external else "pending"
                next_attempt = None if ambiguous_external else now
                processed_at = now if ambiguous_external else None
                self._connection.execute(
                    """UPDATE outbox_events
                    SET status=?,worker_id='',lease_until=NULL,next_attempt_at=?,updated_at=?,processed_at=?,
                    error=CASE WHEN error='' THEN 'Worker lease expired before provider completion' ELSE error END
                    WHERE id=? AND status='processing'""",
                    (status, next_attempt, now, processed_at, row["id"]),
                )
        return [self.get_outbox_event(row["id"]) for row in rows]

    def claim_outbox_events(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 120,
        max_attempts: int = 5,
    ) -> list[dict[str, Any]]:
        """Atomically lease eligible provider operations to one worker."""
        if not worker_id.strip():
            raise ValueError("Outbox worker_id is required")
        limit = max(1, min(int(limit), 500))
        lease_seconds = max(30, min(int(lease_seconds), 3600))
        max_attempts = max(1, min(int(max_attempts), 20))
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        claimed_ids: list[str] = []
        with self.atomic_block():
            rows = self._connection.execute(
                """SELECT id FROM outbox_events
                WHERE status='pending'
                  AND attempt < ?
                  AND (next_attempt_at IS NULL OR next_attempt_at<=?)
                ORDER BY created_at ASC
                LIMIT ?""",
                (max_attempts, now, limit),
            ).fetchall()
            for row in rows:
                cursor = self._connection.execute(
                    """UPDATE outbox_events
                    SET status='processing',attempt=attempt+1,worker_id=?,lease_until=?,updated_at=?
                    WHERE id=? AND status='pending'
                      AND (next_attempt_at IS NULL OR next_attempt_at<=?)""",
                    (worker_id.strip(), lease_until, now, row["id"], now),
                )
                if cursor.rowcount == 1:
                    claimed_ids.append(row["id"])
            if not claimed_ids:
                return []
            placeholders = ",".join("?" for _ in claimed_ids)
            claimed_rows = self._connection.execute(
                f"SELECT * FROM outbox_events WHERE id IN ({placeholders}) ORDER BY created_at",
                claimed_ids,
            ).fetchall()
        return [self._decode_row(row) for row in claimed_rows]  # type: ignore[misc]

    def fetch_pending_outbox_events(
        self,
        limit: int = 50,
        *,
        worker_id: str = "legacy-outbox-worker",
        lease_seconds: int = 120,
        max_attempts: int = 5,
    ) -> list[dict[str, Any]]:
        """Backward-compatible alias for the lease-based outbox claim API."""
        self.recover_expired_outbox_events()
        return self.claim_outbox_events(
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
        )

    def complete_outbox_event(
        self,
        event_id: str,
        error: str = "",
        *,
        worker_id: str = "",
        receipt: dict[str, Any] | None = None,
        retryable: bool = False,
        reconciliation_required: bool = False,
        max_attempts: int = 5,
        base_delay_seconds: int = 30,
    ) -> dict[str, Any]:
        """Complete, retry, or dead-letter one leased provider operation."""
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        max_attempts = max(1, min(int(max_attempts), 20))
        with self.atomic_block():
            row = self._connection.execute(
                "SELECT * FROM outbox_events WHERE id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown outbox event: {event_id}")
            if worker_id and row["worker_id"] not in {"", worker_id}:
                raise ValueError("Outbox lease belongs to another worker")
            if row["status"] == "completed":
                return self._decode_row(row)  # type: ignore[return-value]
            if error:
                attempt = int(row["attempt"] or 0)
                if reconciliation_required:
                    next_attempt = None
                    status = "reconciliation_required"
                    processed_at = now
                elif retryable and attempt < max_attempts:
                    delay = min(max(1, int(base_delay_seconds)) * (2 ** max(0, attempt - 1)), 3600)
                    next_attempt = (now_dt + timedelta(seconds=delay)).isoformat()
                    status = "pending"
                    processed_at = None
                else:
                    next_attempt = None
                    status = "failed"
                    processed_at = now
                self._connection.execute(
                    """UPDATE outbox_events SET status=?,error=?,worker_id='',lease_until=NULL,
                    next_attempt_at=?,updated_at=?,processed_at=? WHERE id=?""",
                    (status, error[:4000], next_attempt, now, processed_at, event_id),
                )
            else:
                self._connection.execute(
                    """UPDATE outbox_events SET status='completed',error='',worker_id='',lease_until=NULL,
                    next_attempt_at=NULL,receipt=?,updated_at=?,processed_at=? WHERE id=?""",
                    (json.dumps(receipt or {}), now, now, event_id),
                )
        return self.get_outbox_event(event_id)

    def resolve_outbox_reconciliation(
        self,
        event_id: str,
        *,
        resolution: str,
        receipt: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Resolve an ambiguous provider attempt after a human/provider check."""
        if resolution not in {"completed", "failed", "requeue"}:
            raise ValueError("Resolution must be completed, failed, or requeue")
        now = utc_now()
        event = self.get_outbox_event(event_id)
        if event["status"] != "reconciliation_required":
            raise ValueError("Outbox event is not awaiting reconciliation")
        if resolution == "completed" and not receipt:
            raise ValueError("A verified provider receipt is required to mark reconciliation completed")
        with self._lock:
            if resolution == "requeue":
                self._connection.execute(
                    """UPDATE outbox_events SET status='pending',worker_id='',lease_until=NULL,
                    next_attempt_at=?,error=?,updated_at=?,processed_at=NULL WHERE id=?""",
                    (now, reason[:4000], now, event_id),
                )
            else:
                self._connection.execute(
                    """UPDATE outbox_events SET status=?,worker_id='',lease_until=NULL,
                    next_attempt_at=NULL,error=?,receipt=?,updated_at=?,processed_at=? WHERE id=?""",
                    (
                        resolution,
                        reason[:4000],
                        json.dumps(receipt or {}),
                        now,
                        now,
                        event_id,
                    ),
                )
            self._commit_if_needed()
        return self.get_outbox_event(event_id)

    def resolve_message_reconciliation(self, message_id: str, *, resolution: str) -> dict[str, Any]:
        """Move a quarantined outbound message to an explicit founder-selected state."""
        status_by_resolution = {
            "failed": "failed",
            "requeue": "sending",
        }
        if resolution not in status_by_resolution:
            raise ValueError("Message reconciliation resolution must be failed or requeue")
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE messages SET status=?,updated_at=?
                WHERE id=? AND status='reconciliation_required'""",
                (status_by_resolution[resolution], now, message_id),
            )
            if cursor.rowcount != 1:
                message = self.get_message(message_id)
                if message["status"] == status_by_resolution[resolution]:
                    return message
                raise ValueError(f"Message is {message['status']} and is not awaiting reconciliation")
            self._commit_if_needed()
        self.publish_event(
            f"message.reconciliation_{resolution}",
            message_id,
            {"resolution": resolution},
        )
        return self.get_message(message_id)

    def list_outbox_events(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM outbox_events"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def list_events(self, event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM events"
        params: list[Any] = []
        if event_type:
            query += " WHERE event_type = ?"
            params.append(event_type)
        query += " ORDER BY sequence DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def audit(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._audit_integrity_fault:
            raise RuntimeError(self._audit_integrity_fault)
        if os.environ.get("AMAURA_STRICT_AUDIT_SIGNATURES", "0") == "1" and len(self._audit_key()) < 32:
            raise RuntimeError("Strict audit signatures require AMAURA_AUDIT_HMAC_KEY of at least 32 bytes")
        created_at = utc_now()
        details_json = json.dumps(details or {}, sort_keys=True, separators=(",", ":"), default=str)
        sequence = 0
        entry_hash = ""
        signature = ""
        key_id = ""
        # BEGIN IMMEDIATE serialises the read-head + append operation across processes.
        with self.atomic_block():
            row = self._connection.execute(
                "SELECT entry_hash FROM audit_logs ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous = row["entry_hash"] if row else ""
            entry_hash = self._audit_digest(
                previous=previous,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                details_json=details_json,
                created_at=created_at,
            )
            signature = self._audit_signature(entry_hash)
            key_id = self._audit_key_id() if signature else ""
            cursor = self._connection.execute(
                """INSERT INTO audit_logs(actor, action, resource_type, resource_id, outcome, details,
                prev_hash,entry_hash,entry_signature,signature_key_id,created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    actor,
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    details_json,
                    previous,
                    entry_hash,
                    signature,
                    key_id,
                    created_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Audit insert did not return a sequence")
            sequence = int(cursor.lastrowid)
        self._write_external_audit_checkpoint(sequence=sequence, head=entry_hash, signature=signature, key_id=key_id)

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_logs ORDER BY sequence DESC LIMIT ?", (max(1, min(limit, 1000)),)
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def record_cost(self, entry: dict[str, Any]) -> None:
        metadata = entry.get("metadata", {})
        with self._lock:
            self._connection.execute(
                """INSERT INTO costs(id, task_id, agent_id, category, amount_cents, units, unit_name, metadata, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"],
                    entry["task_id"],
                    entry["agent_id"],
                    entry["category"],
                    entry["amount_cents"],
                    entry.get("units", 0),
                    entry.get("unit_name", ""),
                    json.dumps(metadata),
                    utc_now(),
                ),
            )
            self._connection.execute(
                "UPDATE work_items SET spent_cents = spent_cents + ?, updated_at = ? WHERE id = ?",
                (entry["amount_cents"], utc_now(), entry["task_id"]),
            )
            self._commit_if_needed()

    def upsert_knowledge(
        self, namespace: str, key: str, value: Any, evidence_refs: list[str], sensitivity: str, actor: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO knowledge(namespace, key, value, evidence_refs, sensitivity, updated_by, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value,
                evidence_refs=excluded.evidence_refs, sensitivity=excluded.sensitivity,
                updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                (namespace, key, json.dumps(value), json.dumps(evidence_refs), sensitivity, actor, utc_now()),
            )
            self._commit_if_needed()

    def get_knowledge(self, namespace: str, key: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM knowledge WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown knowledge item: {namespace}:{key}")
        return decoded

    def list_knowledge(self, *, namespace: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM knowledge"
        params: list[Any] = []
        if namespace is not None:
            query += " WHERE namespace=?"
            params.append(namespace)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def delete_knowledge(self, namespace: str, key: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM knowledge WHERE namespace=? AND key=?",
                (namespace, key),
            )
            self._commit_if_needed()
        return cursor.rowcount == 1

    def record_decision(self, decision: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO decisions(id, decision, context, options, chosen_option, reason, owner,
                review_date, outcome, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision["id"],
                    decision["decision"],
                    decision["context"],
                    json.dumps(decision["options"]),
                    decision["chosen_option"],
                    decision["reason"],
                    decision["owner"],
                    decision.get("review_date"),
                    decision.get("outcome", ""),
                    utc_now(),
                ),
            )
            self._commit_if_needed()

    # -- Company objectives -----------------------------------------------

    def create_objective(self, objective: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "status": "active",
            "priority": 3,
            "target_value": None,
            "current_value": 0.0,
            "unit": "",
            "cadence": "weekly",
            "inputs": {},
            "max_active_programmes": 1,
            "budget_cents": 0,
            "deadline": None,
            "last_planned_key": "",
            "last_planned_at": None,
            **objective,
        }
        columns = (
            "id",
            "title",
            "objective",
            "department",
            "workflow_key",
            "status",
            "priority",
            "success_metric",
            "target_value",
            "current_value",
            "unit",
            "cadence",
            "inputs",
            "max_active_programmes",
            "budget_cents",
            "deadline",
            "last_planned_key",
            "last_planned_at",
            "created_by",
            "created_at",
            "updated_at",
        )
        values["created_at"] = now
        values["updated_at"] = now
        encoded = [json.dumps(values[column]) if column == "inputs" else values[column] for column in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO company_objectives({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        return self.get_objective(values["id"])

    def get_objective(self, objective_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM company_objectives WHERE id=?", (objective_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown company objective: {objective_id}")
        return decoded

    def list_objectives(
        self,
        *,
        status: str | None = None,
        department: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if department is not None:
            clauses.append("department=?")
            params.append(department)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM company_objectives{where} ORDER BY priority, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_objective(self, objective_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {
            "title",
            "objective",
            "status",
            "priority",
            "success_metric",
            "target_value",
            "current_value",
            "unit",
            "cadence",
            "inputs",
            "max_active_programmes",
            "budget_cents",
            "deadline",
            "last_planned_key",
            "last_planned_at",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported objective fields: {sorted(invalid)}")
        if not updates:
            return self.get_objective(objective_id)
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in updates.items():
            assignments.append(f"{key}=?")
            params.append(json.dumps(value) if key == "inputs" else value)
        assignments.append("updated_at=?")
        params.extend((utc_now(), objective_id))
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE company_objectives SET {', '.join(assignments)} WHERE id=?",
                params,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown company objective: {objective_id}")
            self._commit_if_needed()
        return self.get_objective(objective_id)

    def record_objective_update(
        self,
        *,
        update_id: str,
        objective_id: str,
        previous_value: float,
        new_value: float,
        note: str,
        evidence_refs: list[dict[str, Any]],
        actor: str,
    ) -> dict[str, Any]:
        created_at = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO objective_updates(
                    id,objective_id,previous_value,new_value,note,evidence_refs,actor,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    update_id,
                    objective_id,
                    float(previous_value),
                    float(new_value),
                    note,
                    json.dumps(evidence_refs),
                    actor,
                    created_at,
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute("SELECT * FROM objective_updates WHERE id=?", (update_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Objective update was not persisted")
        return decoded

    def list_objective_updates(self, objective_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM objective_updates WHERE objective_id=? ORDER BY created_at DESC LIMIT ?",
                (objective_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def claim_objective_cadence(
        self,
        objective_id: str,
        cadence_key: str,
        *,
        budget_cents: int,
        created_at: str | None = None,
    ) -> bool:
        """Atomically reserve one objective/cadence pair.

        The composite primary key is the cross-process idempotency boundary. Call
        this inside ``atomic_block`` together with programme creation so a crash or
        downstream exception rolls the claim back rather than stranding it.
        """
        now = created_at or utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO objective_cadence_runs(
                    objective_id,cadence_key,programme_id,status,budget_cents,created_at,updated_at
                ) VALUES(?,?,NULL,'claimed',?,?,?)""",
                (objective_id, cadence_key, int(budget_cents), now, now),
            )
            self._commit_if_needed()
            return cursor.rowcount == 1

    def complete_objective_cadence(
        self,
        objective_id: str,
        cadence_key: str,
        *,
        programme_id: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE objective_cadence_runs
                   SET programme_id=?,status='created',updated_at=?
                   WHERE objective_id=? AND cadence_key=? AND status='claimed'""",
                (programme_id, now, objective_id, cadence_key),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Objective cadence was not claimed by this transaction")
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM objective_cadence_runs WHERE objective_id=? AND cadence_key=?",
                (objective_id, cadence_key),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Objective cadence completion was not persisted")
        return decoded

    def get_objective_cadence_run(self, objective_id: str, cadence_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM objective_cadence_runs WHERE objective_id=? AND cadence_key=?",
                (objective_id, cadence_key),
            ).fetchone()
        return self._decode_row(row)

    def objective_cadence_budget_for_date(self, date_iso: str) -> int:
        """Return durably reserved/created autopilot budget for a UTC date."""
        with self._lock:
            row = self._connection.execute(
                """SELECT COALESCE(SUM(budget_cents),0) AS total
                   FROM objective_cadence_runs
                   WHERE substr(created_at,1,10)=? AND status IN ('claimed','created','credited')""",
                (date_iso,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def list_objective_cadence_runs(
        self,
        *,
        objective_id: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if objective_id is not None:
            clauses.append("objective_id=?")
            params.append(objective_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM objective_cadence_runs{where} ORDER BY created_at LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def credit_objective_cadence(
        self,
        objective_id: str,
        cadence_key: str,
    ) -> bool:
        """Mark a completed cadence as credited exactly once."""
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE objective_cadence_runs SET status='credited',updated_at=?
                   WHERE objective_id=? AND cadence_key=? AND status='created'""",
                (utc_now(), objective_id, cadence_key),
            )
            self._commit_if_needed()
            return cursor.rowcount == 1

    # -- Revenue pipeline -------------------------------------------------

    def upsert_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "minimum_score": 70,
            "active": True,
            "daily_lead_limit": 10,
            "daily_outreach_limit": 3,
            "daily_followup_limit": 5,
            "maximum_followups": 2,
            "config": {},
            **campaign,
        }
        with self._lock:
            self._connection.execute(
                """INSERT INTO campaigns(id,name,target_segment,offer,minimum_score,active,
                daily_lead_limit,daily_outreach_limit,daily_followup_limit,maximum_followups,
                config,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,target_segment=excluded.target_segment,
                offer=excluded.offer,minimum_score=excluded.minimum_score,active=excluded.active,
                daily_lead_limit=excluded.daily_lead_limit,daily_outreach_limit=excluded.daily_outreach_limit,
                daily_followup_limit=excluded.daily_followup_limit,maximum_followups=excluded.maximum_followups,
                config=excluded.config,updated_at=excluded.updated_at""",
                (
                    values["id"],
                    values["name"],
                    values["target_segment"],
                    values["offer"],
                    values["minimum_score"],
                    int(values["active"]),
                    values["daily_lead_limit"],
                    values["daily_outreach_limit"],
                    values["daily_followup_limit"],
                    values["maximum_followups"],
                    json.dumps(values["config"]),
                    now,
                    now,
                ),
            )
            self._commit_if_needed()
        return self.get_campaign(values["id"])

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        result = self._decode_row(row)
        if result is None:
            raise KeyError(f"Unknown campaign: {campaign_id}")
        return result

    def list_campaigns(self, active: bool | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM campaigns", []
        if active is not None:
            query, params = query + " WHERE active=?", [int(active)]
        query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def insert_lead(
        self, lead: dict[str, Any], *, daily_limit: int | None = None, day_prefix: str = ""
    ) -> dict[str, Any]:
        now = utc_now()
        values = {
            "contact_name": "",
            "public_contact": "",
            "contact_source_url": "",
            "linkedin_url": "",
            "country": "",
            "industry": "",
            "stage": "discovered",
            "total_score": 0,
            "score_components": {},
            "do_not_contact": False,
            "opt_out_reason": "",
            "estimated_value_cents": 0,
            "next_action": "",
            "next_action_at": None,
            "metadata": {},
            **lead,
        }
        with self.atomic_block():
            if daily_limit is not None:
                count = self._connection.execute(
                    "SELECT COUNT(*) FROM leads WHERE campaign_id=? AND created_at LIKE ?",
                    (values["campaign_id"], f"{day_prefix}%"),
                ).fetchone()[0]
                if count >= daily_limit:
                    raise ValueError("Daily lead discovery limit reached")
            self._connection.execute(
                """INSERT INTO leads(id,campaign_id,company_name,domain,contact_name,public_contact,
                    contact_source_url,linkedin_url,country,industry,stage,total_score,score_components,
                    do_not_contact,opt_out_reason,estimated_value_cents,next_action,next_action_at,metadata,
                    created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["campaign_id"],
                    values["company_name"],
                    values["domain"],
                    values["contact_name"],
                    values["public_contact"],
                    values["contact_source_url"],
                    values["linkedin_url"],
                    values["country"],
                    values["industry"],
                    values["stage"],
                    values["total_score"],
                    json.dumps(values["score_components"]),
                    int(values["do_not_contact"]),
                    values["opt_out_reason"],
                    values["estimated_value_cents"],
                    values["next_action"],
                    values["next_action_at"],
                    json.dumps(values["metadata"]),
                    now,
                    now,
                ),
            )
        return self.get_lead(values["id"])

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        result = self._decode_row(row)
        if result is None:
            raise KeyError(f"Unknown lead: {lead_id}")
        return result

    def get_lead_by_domain(self, domain: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM leads WHERE domain=?", (domain,)).fetchone()
        return self._decode_row(row)

    def get_lead_by_public_contact(self, public_contact: str) -> dict[str, Any] | None:
        normalized = str(public_contact or "").strip().lower()
        if not normalized:
            return None
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM leads WHERE public_contact<>'' ORDER BY updated_at DESC LIMIT 2000"
            ).fetchall()
        for row in rows:
            decoded = self._decode_row(row)
            if decoded and str(decoded.get("public_contact", "")).strip().lower() == normalized:
                return decoded
        return None

    def list_leads(
        self, campaign_id: str | None = None, stage: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if campaign_id:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
        if stage:
            clauses.append("stage=?")
            params.append(stage)
        query = "SELECT * FROM leads" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        query += " ORDER BY total_score DESC, created_at ASC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_lead(self, lead_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "stage",
            "total_score",
            "score_components",
            "do_not_contact",
            "opt_out_reason",
            "estimated_value_cents",
            "next_action",
            "next_action_at",
            "metadata",
            "contact_name",
            "public_contact",
            "contact_source_url",
            "linkedin_url",
            "country",
            "industry",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid lead fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_lead(lead_id)
        fields["updated_at"] = utc_now()
        assignments, params = [], []
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            if key in {"score_components", "metadata"}:
                value = json.dumps(value)
            elif key == "do_not_contact":
                value = int(value)
            params.append(value)
        params.append(lead_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE leads SET {', '.join(assignments)} WHERE id=?", params)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown lead: {lead_id}")
            self._commit_if_needed()
        return self.get_lead(lead_id)

    def add_lead_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        values = {"retrieved_at": utc_now(), **evidence}
        with self._lock:
            self._connection.execute(
                """INSERT INTO lead_evidence(id,lead_id,claim_type,claim,source_url,source_excerpt,
                retrieved_at,confidence,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["lead_id"],
                    values["claim_type"],
                    values["claim"],
                    values["source_url"],
                    values["source_excerpt"],
                    values["retrieved_at"],
                    values["confidence"],
                    values["content_hash"],
                    utc_now(),
                ),
            )
            self._commit_if_needed()
        with self._lock:
            row = self._connection.execute("SELECT * FROM lead_evidence WHERE id=?", (values["id"],)).fetchone()
        return self._decode_row(row)  # type: ignore[return-value]

    def list_lead_evidence(self, lead_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM lead_evidence WHERE lead_id=? ORDER BY created_at", (lead_id,)
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def insert_message(self, message: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "subject": "",
            "recipient": "",
            "approved_payload_hash": "",
            "status": "draft",
            "approved_by": None,
            "approved_at": None,
            "sent_at": None,
            "external_message_id": None,
            "thread_id": None,
            "evidence_snapshot": [],
            **message,
        }
        with self._lock:
            self._connection.execute(
                """INSERT INTO messages(id,lead_id,channel,message_type,subject,body,
                recipient,approved_payload_hash,status,approved_by,
                approved_at,sent_at,external_message_id,thread_id,idempotency_key,evidence_snapshot,
                created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["lead_id"],
                    values["channel"],
                    values["message_type"],
                    values["subject"],
                    values["body"],
                    values["recipient"],
                    values["approved_payload_hash"],
                    values["status"],
                    values["approved_by"],
                    values["approved_at"],
                    values["sent_at"],
                    values["external_message_id"],
                    values["thread_id"],
                    values["idempotency_key"],
                    json.dumps(values["evidence_snapshot"]),
                    now,
                    now,
                ),
            )
            self._commit_if_needed()
        return self.get_message(values["id"])

    def get_message(self, message_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        result = self._decode_row(row)
        if result is None:
            raise KeyError(f"Unknown message: {message_id}")
        return result

    def update_message(self, message_id: str, **fields: Any) -> dict[str, Any]:
        # subject and body are write-once: they are set at staging time and locked
        # from that point forward to enforce exact-payload approval (P0-6).
        # approved_payload_hash is written once at approval time by decide_message.
        allowed = {
            "status",
            "approved_by",
            "approved_at",
            "sent_at",
            "external_message_id",
            "thread_id",
            "approved_payload_hash",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid message fields: {', '.join(sorted(invalid))}")
        fields["updated_at"] = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE messages SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
                [*fields.values(), message_id],
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown message: {message_id}")
            self._commit_if_needed()
        return self.get_message(message_id)

    def mark_message_sending(self, message_id: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE messages SET status='sending',updated_at=?
                WHERE id=? AND status='approved'""",
                (now, message_id),
            )
            if cursor.rowcount != 1:
                message = self.get_message(message_id)
                if message["status"] == "sent":
                    return message
                raise ValueError(f"Message is {message['status']} and cannot start a new provider send")
            self._commit_if_needed()
        return self.get_message(message_id)

    def mark_message_reconciliation_required(self, message_id: str, reason: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE messages SET status='reconciliation_required',updated_at=?
                WHERE id=? AND status='sending'""",
                (now, message_id),
            )
            if cursor.rowcount != 1:
                return self.get_message(message_id)
            self._commit_if_needed()
        self.publish_event("message.reconciliation_required", message_id, {"reason": reason})
        return self.get_message(message_id)

    def confirm_message_sent_atomic(
        self,
        message_id: str,
        *,
        campaign_id: str,
        is_followup: bool,
        daily_limit: int,
        since: str,
        external_message_id: str,
        thread_id: str | None,
    ) -> dict[str, Any]:
        """Atomically enforce a campaign cap and record provider-confirmed delivery."""
        with self.atomic_block():
            message = self._connection.execute("SELECT status FROM messages WHERE id=?", (message_id,)).fetchone()
            if message is None:
                raise KeyError(f"Unknown message: {message_id}")
            if message["status"] == "sent":
                self._connection.rollback()
                return self.get_message(message_id)
            if message["status"] not in {
                "approved",
                "sending",
                "queued",
                "dispatching",
                "prepared",
                "reconciliation_required",
            }:
                raise ValueError(
                    "Only an approved, sending, queued, dispatching, prepared, or reconciliation-required message can be marked sent"
                )
            comparator = "='followup'" if is_followup else "!='followup'"
            count = self._connection.execute(
                f"""SELECT COUNT(*) FROM messages m JOIN leads l ON l.id=m.lead_id
                    WHERE l.campaign_id=? AND m.status='sent' AND m.message_type{comparator}
                    AND m.sent_at>=?""",
                (campaign_id, since),
            ).fetchone()[0]
            if count >= daily_limit:
                raise ValueError("Campaign daily outbound limit reached")
            now = utc_now()
            self._connection.execute(
                """UPDATE messages SET status='sent',sent_at=?,external_message_id=?,thread_id=?,updated_at=?
                    WHERE id=?""",
                (now, external_message_id, thread_id, now, message_id),
            )
        return self.get_message(message_id)

    def list_messages(
        self, lead_id: str | None = None, status: str | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        for column, value in (("lead_id", lead_id), ("status", status)):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if since:
            clauses.append("created_at>=?")
            params.append(since)
        query = (
            "SELECT * FROM messages"
            + (" WHERE " + " AND ".join(clauses) if clauses else "")
            + " ORDER BY created_at DESC"
        )
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def publish_pipeline_event(
        self,
        *,
        lead_id: str | None,
        campaign_id: str | None,
        event_type: str,
        agent: str,
        input_hash: str,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO pipeline_events(lead_id,campaign_id,event_type,agent,input_hash,output,created_at) VALUES(?,?,?,?,?,?,?)",
                (lead_id, campaign_id, event_type, agent, input_hash, json.dumps(output), now),
            )
            self._commit_if_needed()
        return {
            "sequence": cursor.lastrowid,
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "event_type": event_type,
            "agent": agent,
            "input_hash": input_hash,
            "output": output,
            "created_at": now,
        }

    def list_pipeline_events(self, lead_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM pipeline_events"
        params: list[Any] = []
        if lead_id:
            query += " WHERE lead_id=?"
            params.append(lead_id)
        query += " ORDER BY sequence DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def record_idempotency(self, key: str, operation: str, resource_id: str, result_hash: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO idempotency_records(idempotency_key,operation,resource_id,result_hash,created_at) VALUES(?,?,?,?,?)",
                (key, operation, resource_id, result_hash, utc_now()),
            )
            self._commit_if_needed()
        return cursor.rowcount == 1

    def get_idempotency(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key=?", (key,)
            ).fetchone()
        return self._decode_row(row)

    def set_control(self, key: str, value: str, actor: str) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO system_controls(key,value,updated_by,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (key, value, actor, utc_now()),
            )
            self._commit_if_needed()

    def get_control(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._connection.execute("SELECT value FROM system_controls WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    # -- Inbound communications and free-first integration actions --------

    def upsert_inbound_message(self, message: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        values = {
            "thread_id": "",
            "lead_id": None,
            "sender": "",
            "recipient": "",
            "subject": "",
            "body": "",
            "status": "new",
            "classification": {},
            "raw_metadata": {},
            "received_at": now,
            **message,
        }
        required = ("id", "provider", "external_id", "content_hash")
        if not all(str(values.get(name, "")).strip() for name in required):
            raise ValueError("Inbound message id, provider, external id, and content hash are required")
        inserted = False
        with self.atomic_block():
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO inbound_messages(
                id,provider,external_id,thread_id,lead_id,sender,recipient,subject,body,status,
                classification,raw_metadata,content_hash,received_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["provider"],
                    values["external_id"],
                    values["thread_id"],
                    values["lead_id"],
                    values["sender"],
                    values["recipient"],
                    values["subject"],
                    values["body"],
                    values["status"],
                    json.dumps(values["classification"]),
                    json.dumps(values["raw_metadata"]),
                    values["content_hash"],
                    values["received_at"],
                    now,
                    now,
                ),
            )
            inserted = cursor.rowcount == 1
            row = self._connection.execute(
                "SELECT * FROM inbound_messages WHERE provider=? AND external_id=?",
                (values["provider"], values["external_id"]),
            ).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        return decoded, inserted

    def get_inbound_message(self, message_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM inbound_messages WHERE id=?", (message_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown inbound message: {message_id}")
        return decoded

    def list_inbound_messages(
        self, *, status: str | None = None, lead_id: str | None = None, provider: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("status", status), ("lead_id", lead_id), ("provider", provider)):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        query = "SELECT * FROM inbound_messages"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY received_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_inbound_message(self, message_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"lead_id", "status", "classification", "raw_metadata"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid inbound message fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_inbound_message(message_id)
        fields["updated_at"] = utc_now()
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            if key in {"classification", "raw_metadata"}:
                value = json.dumps(value)
            params.append(value)
        params.append(message_id)
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE inbound_messages SET {', '.join(assignments)} WHERE id=?", params
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown inbound message: {message_id}")
            self._commit_if_needed()
        return self.get_inbound_message(message_id)

    def set_integration_cursor(
        self, provider: str, cursor: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO integration_cursors(provider,cursor,metadata,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(provider) DO UPDATE SET cursor=excluded.cursor,metadata=excluded.metadata,updated_at=excluded.updated_at""",
                (provider, cursor, json.dumps(metadata or {}), now),
            )
            self._commit_if_needed()
            row = self._connection.execute("SELECT * FROM integration_cursors WHERE provider=?", (provider,)).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        return decoded

    def get_integration_cursor(self, provider: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM integration_cursors WHERE provider=?", (provider,)).fetchone()
        return self._decode_row(row)

    def insert_integration_action(self, action: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        values = {
            "risk": "medium",
            "status": "awaiting_approval",
            "approved_by": None,
            "approved_at": None,
            "outbox_event_id": None,
            "receipt": {},
            "error": "",
            **action,
        }
        inserted = False
        with self.atomic_block():
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO integration_actions(
                id,provider,operation,payload,payload_hash,idempotency_key,risk,status,requested_by,
                approved_by,approved_at,outbox_event_id,receipt,error,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["provider"],
                    values["operation"],
                    json.dumps(values["payload"]),
                    values["payload_hash"],
                    values["idempotency_key"],
                    values["risk"],
                    values["status"],
                    values["requested_by"],
                    values["approved_by"],
                    values["approved_at"],
                    values["outbox_event_id"],
                    json.dumps(values["receipt"]),
                    values["error"],
                    now,
                    now,
                ),
            )
            inserted = cursor.rowcount == 1
            row = self._connection.execute(
                "SELECT * FROM integration_actions WHERE idempotency_key=?",
                (values["idempotency_key"],),
            ).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        return decoded, inserted

    def get_integration_action(self, action_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM integration_actions WHERE id=?", (action_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown integration action: {action_id}")
        return decoded

    def list_integration_actions(
        self, *, status: str | None = None, provider: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("status", status), ("provider", provider)):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        query = "SELECT * FROM integration_actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def approve_integration_action(self, action_id: str, *, actor: str, approved: bool, reason: str) -> dict[str, Any]:
        now = utc_now()
        target = "approved" if approved else "rejected"
        with self.atomic_block():
            row = self._connection.execute("SELECT * FROM integration_actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown integration action: {action_id}")
            if row["status"] != "awaiting_approval":
                raise ValueError(f"Integration action is already {row['status']}")
            payload = json.loads(row["payload"])
            if not hmac.compare_digest(self.canonical_hash(payload), row["payload_hash"]):
                raise ValueError("Integration action payload hash mismatch")
            self._connection.execute(
                """UPDATE integration_actions SET status=?,approved_by=?,approved_at=?,error=?,updated_at=?
                WHERE id=? AND status='awaiting_approval'""",
                (target, actor, now, reason[:4000], now, action_id),
            )
        return self.get_integration_action(action_id)

    def approve_and_enqueue_integration_action(
        self,
        action_id: str,
        *,
        actor: str,
        reason: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically approve and enqueue one external integration action.

        This method is deliberately idempotent for an already-enqueued action
        and can recover the legacy v3.6.0 partial state where an action was
        committed as ``approved`` before its outbox row was created.
        """
        now = utc_now()
        with self.atomic_block():
            row = self._connection.execute("SELECT * FROM integration_actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown integration action: {action_id}")

            payload = json.loads(row["payload"])
            if not hmac.compare_digest(self.canonical_hash(payload), row["payload_hash"]):
                raise ValueError("Integration action payload hash mismatch")

            status = str(row["status"])
            existing_outbox_id = str(row["outbox_event_id"] or "")
            if status == "enqueued" and existing_outbox_id:
                return self.get_integration_action(action_id), self.get_outbox_event(existing_outbox_id)
            if status not in {"awaiting_approval", "approved"}:
                raise ValueError(f"Integration action is already {status}")

            if status == "awaiting_approval":
                cursor = self._connection.execute(
                    """UPDATE integration_actions
                    SET status='approved',approved_by=?,approved_at=?,error='',updated_at=?
                    WHERE id=? AND status='awaiting_approval'""",
                    (actor, now, now, action_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Integration action approval raced with another decision")

            event_payload = {**payload, "action_id": action_id, "actor": actor}
            event = self.enqueue_outbox_event(
                provider=str(row["provider"]),
                operation=str(row["operation"]),
                payload=event_payload,
                idempotency_key=str(row["idempotency_key"]),
            )
            self._connection.execute(
                """UPDATE integration_actions
                SET status='enqueued',outbox_event_id=?,error=?,updated_at=?
                WHERE id=?""",
                (event["id"], reason[:4000], now, action_id),
            )
            action = self.get_integration_action(action_id)
        return action, event

    def bind_integration_action_outbox(self, action_id: str, outbox_event_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.atomic_block():
            row = self._connection.execute(
                "SELECT status,payload,payload_hash FROM integration_actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown integration action: {action_id}")
            if row["status"] not in {"approved", "enqueued"}:
                raise ValueError("Only an approved integration action can be enqueued")
            if not hmac.compare_digest(self.canonical_hash(json.loads(row["payload"])), row["payload_hash"]):
                raise ValueError("Integration action payload changed after approval")
            self._connection.execute(
                """UPDATE integration_actions SET status='enqueued',outbox_event_id=?,updated_at=?
                WHERE id=?""",
                (outbox_event_id, now, action_id),
            )
        return self.get_integration_action(action_id)

    def complete_integration_action(
        self, action_id: str, *, receipt: dict[str, Any] | None = None, error: str = "", status: str = "completed"
    ) -> dict[str, Any]:
        if status not in {"completed", "prepared", "failed", "reconciliation_required"}:
            raise ValueError("Invalid integration action completion status")
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE integration_actions SET status=?,receipt=?,error=?,updated_at=? WHERE id=?""",
                (status, json.dumps(receipt or {}), error[:4000], utc_now(), action_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown integration action: {action_id}")
            self._commit_if_needed()
        return self.get_integration_action(action_id)

    def provider_can_attempt(self, provider: str) -> tuple[bool, dict[str, Any]]:
        now = datetime.now(UTC)
        with self._lock:
            row = self._connection.execute("SELECT * FROM provider_health WHERE provider=?", (provider,)).fetchone()
        decoded = self._decode_row(row) or {
            "provider": provider,
            "state": "closed",
            "consecutive_failures": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "circuit_open_until": None,
            "last_error": "",
            "updated_at": utc_now(),
        }
        until = decoded.get("circuit_open_until")
        if decoded.get("state") == "open" and until:
            try:
                if datetime.fromisoformat(str(until)) > now:
                    return False, decoded
            except ValueError:
                return False, decoded
        return True, decoded

    def record_provider_success(self, provider: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO provider_health(provider,state,consecutive_failures,last_success_at,last_failure_at,circuit_open_until,last_error,updated_at)
                VALUES(?, 'closed', 0, ?, NULL, NULL, '', ?)
                ON CONFLICT(provider) DO UPDATE SET state='closed',consecutive_failures=0,last_success_at=excluded.last_success_at,
                circuit_open_until=NULL,last_error='',updated_at=excluded.updated_at""",
                (provider, now, now),
            )
            self._commit_if_needed()
            row = self._connection.execute("SELECT * FROM provider_health WHERE provider=?", (provider,)).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        return decoded

    def record_provider_failure(
        self, provider: str, error: str, *, threshold: int = 3, cooldown_seconds: int = 300
    ) -> dict[str, Any]:
        threshold = max(1, min(int(threshold), 20))
        cooldown_seconds = max(30, min(int(cooldown_seconds), 86_400))
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        with self.atomic_block():
            row = self._connection.execute(
                "SELECT consecutive_failures FROM provider_health WHERE provider=?", (provider,)
            ).fetchone()
            failures = (int(row[0]) if row else 0) + 1
            state = "open" if failures >= threshold else "closed"
            open_until = (now_dt + timedelta(seconds=cooldown_seconds)).isoformat() if state == "open" else None
            self._connection.execute(
                """INSERT INTO provider_health(provider,state,consecutive_failures,last_success_at,last_failure_at,circuit_open_until,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(provider) DO UPDATE SET state=excluded.state,consecutive_failures=excluded.consecutive_failures,
                last_failure_at=excluded.last_failure_at,circuit_open_until=excluded.circuit_open_until,last_error=excluded.last_error,updated_at=excluded.updated_at""",
                (provider, state, failures, None, now, open_until, error[:4000], now),
            )
            result = self._connection.execute("SELECT * FROM provider_health WHERE provider=?", (provider,)).fetchone()
        decoded = self._decode_row(result)
        assert decoded is not None
        return decoded

    def list_provider_health(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM provider_health ORDER BY provider").fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def insert_invoice(self, invoice: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        values = {
            "client_email": "",
            "currency": "INR",
            "tax_minor": 0,
            "line_items": [],
            "due_date": None,
            "status": "draft",
            "payment_uri": "",
            "document_path": "",
            "idempotency_key": "",
            "payment_reference": "",
            "status_reason": "",
            **invoice,
        }
        inserted = False
        with self.atomic_block():
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO invoices(
                id,idempotency_key,client_name,client_email,currency,amount_minor,tax_minor,line_items,
                due_date,status,payment_uri,document_path,payload_hash,payment_reference,status_reason,
                created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["idempotency_key"],
                    values["client_name"],
                    values["client_email"],
                    values["currency"],
                    values["amount_minor"],
                    values["tax_minor"],
                    json.dumps(values["line_items"]),
                    values["due_date"],
                    values["status"],
                    values["payment_uri"],
                    values["document_path"],
                    values["payload_hash"],
                    values["payment_reference"],
                    values["status_reason"],
                    now,
                    now,
                ),
            )
            inserted = cursor.rowcount == 1
            if values["idempotency_key"]:
                row = self._connection.execute(
                    "SELECT * FROM invoices WHERE idempotency_key=?",
                    (values["idempotency_key"],),
                ).fetchone()
            else:
                row = self._connection.execute("SELECT * FROM invoices WHERE id=?", (values["id"],)).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        if not hmac.compare_digest(str(decoded["payload_hash"]), str(values["payload_hash"])):
            raise ValueError("Invoice idempotency key was already used for different content")
        return decoded, inserted

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown invoice: {invoice_id}")
        return decoded

    def list_invoices(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM invoices"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_invoice(self, invoice_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "payment_uri",
            "document_path",
            "due_date",
            "payment_reference",
            "status_reason",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid invoice fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_invoice(invoice_id)
        fields["updated_at"] = utc_now()
        assignments = [f"{key}=?" for key in fields]
        params = list(fields.values()) + [invoice_id]
        with self._lock:
            cursor = self._connection.execute(f"UPDATE invoices SET {', '.join(assignments)} WHERE id=?", params)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown invoice: {invoice_id}")
            self._commit_if_needed()
        return self.get_invoice(invoice_id)

    def transition_invoice(
        self,
        invoice_id: str,
        *,
        to_status: str,
        actor: str,
        reference: str = "",
    ) -> dict[str, Any]:
        """Apply a validated, append-recorded invoice state transition."""
        transitions = {
            "draft": {"approved", "void"},
            "approved": {"sent", "void"},
            "sent": {"paid", "overdue", "void"},
            "overdue": {"paid", "void"},
            "paid": set(),
            "void": set(),
        }
        now = utc_now()
        clean_reference = reference.strip()
        with self.atomic_block():
            row = self._connection.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown invoice: {invoice_id}")
            current = str(row["status"])
            if current not in transitions or to_status not in transitions[current]:
                raise ValueError(f"Invalid invoice transition: {current} -> {to_status}")
            if to_status in {"paid", "void"} and not clean_reference:
                raise ValueError(f"Invoice transition to {to_status} requires a reference or reason")
            payment_reference = clean_reference if to_status == "paid" else str(row["payment_reference"] or "")
            status_reason = clean_reference if to_status == "void" else ""
            cursor = self._connection.execute(
                """UPDATE invoices
                SET status=?,payment_reference=?,status_reason=?,updated_at=?
                WHERE id=? AND status=?""",
                (to_status, payment_reference, status_reason, now, invoice_id, current),
            )
            if cursor.rowcount != 1:
                raise ValueError("Invoice state changed concurrently; retry from the latest state")
            self._connection.execute(
                """INSERT INTO invoice_status_events(
                invoice_id,from_status,to_status,actor,reference,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (invoice_id, current, to_status, actor, clean_reference, now),
            )
        return self.get_invoice(invoice_id)

    def list_invoice_status_events(self, invoice_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM invoice_status_events WHERE invoice_id=? ORDER BY id",
                (invoice_id,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    # -- Durable worker leases -------------------------------------------

    def _get_execution(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM execution_runs WHERE id=?", (run_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown execution run: {run_id}")
        return decoded

    def list_executions(
        self, *, state: str | None = None, task_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("state=?")
            params.append(state)
        if task_id:
            clauses.append("task_id=?")
            params.append(task_id)
        query = "SELECT * FROM execution_runs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def recover_expired_executions(self, *, max_attempts: int = 3) -> list[dict[str, Any]]:
        """Expire abandoned leases and make retryable tasks available again."""
        now = utc_now()
        recovered: list[dict[str, Any]] = []
        with self.atomic_block():
            rows = self._connection.execute(
                """SELECT * FROM execution_runs
                    WHERE state IN ('leased','running') AND lease_until<=?
                    ORDER BY started_at""",
                (now,),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    """UPDATE execution_runs
                        SET state='expired',finished_at=?,error=?
                        WHERE id=? AND state IN ('leased','running')""",
                    (now, "Worker lease expired before completion", row["id"]),
                )
                retry = row["attempt"] < max(1, max_attempts)
                task_state = "assigned" if retry else "failed"
                self._connection.execute(
                    """UPDATE work_items SET state=?,updated_at=?,
                        summary=CASE WHEN summary='' THEN ? ELSE ? || '\n\n' || summary END
                        WHERE id=? AND state='in_progress'""",
                    (
                        task_state,
                        now,
                        "Execution lease expired; JARVIS recovered the task.",
                        "Execution lease expired; JARVIS recovered the task.",
                        row["task_id"],
                    ),
                )
                recovered.append(
                    {
                        "run_id": row["id"],
                        "task_id": row["task_id"],
                        "attempt": row["attempt"],
                        "retry_scheduled": retry,
                    }
                )
        return recovered

    def dynamic_mission_task_runnable(self, task: dict[str, Any]) -> bool:
        metadata = dict(task.get("metadata") or {})
        if not metadata.get("dynamic_goal"):
            return True
        programme_id = str(metadata.get("programme_id") or "")
        if not programme_id:
            return False
        try:
            programme = self.get_work_item(programme_id)
        except KeyError:
            return False
        pmeta = dict(programme.get("metadata") or {})
        return bool(
            pmeta.get("dynamic_goal") is True
            and pmeta.get("mission_runnable") is True
            and pmeta.get("mission_paused") is not True
            and pmeta.get("cancel_requested") is not True
            and programme.get("state") not in {"draft", "cancelled", "completed"}
            and int(metadata.get("mission_generation", 1) or 1) == int(pmeta.get("mission_generation", 1) or 1)
        )

    def _dynamic_mission_candidate_runnable(self, candidate: sqlite3.Row) -> bool:
        """Enforce JARVIS mission authority at the lowest claim boundary.

        Higher layers normally keep held tasks in DRAFT, but stale state or a
        race must never make a held/cancelled generation executable merely
        because a child row says ASSIGNED.
        """
        try:
            metadata = json.loads(candidate["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        if not metadata.get("dynamic_goal"):
            return True
        programme_id = str(metadata.get("programme_id") or "")
        if not programme_id:
            return False
        programme = self._connection.execute(
            "SELECT state,metadata FROM work_items WHERE id=? AND item_type='programme'",
            (programme_id,),
        ).fetchone()
        if programme is None:
            return False
        try:
            pmeta = json.loads(programme["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return False
        if pmeta.get("dynamic_goal") is not True or pmeta.get("mission_runnable") is not True:
            return False
        if pmeta.get("mission_paused") is True or pmeta.get("cancel_requested") is True:
            return False
        if programme["state"] in {"draft", "cancelled", "completed"}:
            return False
        task_generation = int(metadata.get("mission_generation", 1) or 1)
        programme_generation = int(pmeta.get("mission_generation", 1) or 1)
        return task_generation == programme_generation

    def claim_next_task(
        self, *, worker_id: str, lease_seconds: int = 900, max_attempts: int = 3, workflow_id: str | None = None
    ) -> dict[str, Any] | None:
        """Atomically lease one dependency-ready task to one worker."""
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        lease_seconds = max(30, min(int(lease_seconds), 86_400))
        max_attempts = max(1, min(int(max_attempts), 20))
        self.recover_expired_executions(max_attempts=max_attempts)
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease_until = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        with self.atomic_block():
            params: list[Any] = []
            workflow_clause = ""
            if workflow_id:
                workflow_clause = " AND w.workflow_id=?"
                params.append(workflow_id)
            candidates = self._connection.execute(
                f"""SELECT w.* FROM work_items w
                    JOIN agents a ON a.agent_id=w.owner_id AND a.enabled=1
                    WHERE w.item_type='task' AND w.state IN ('assigned','blocked')
                    {workflow_clause}
                    AND NOT EXISTS (
                        SELECT 1 FROM execution_runs r
                        WHERE r.task_id=w.id AND r.state IN ('leased','running')
                    )
                    ORDER BY w.priority ASC,w.created_at ASC LIMIT 200""",
                params,
            ).fetchall()
            selected: sqlite3.Row | None = None
            attempt = 0
            for candidate in candidates:
                if not self._dynamic_mission_candidate_runnable(candidate):
                    # Freeze a stale dynamic task rather than allowing a
                    # global supervisor/autopilot to bypass the mission.
                    if candidate["state"] in {"assigned", "blocked"}:
                        self._connection.execute(
                            "UPDATE work_items SET state='draft',updated_at=? WHERE id=?",
                            (now, candidate["id"]),
                        )
                    continue
                try:
                    dependencies = json.loads(candidate["dependencies"])
                except json.JSONDecodeError:
                    dependencies = []
                if dependencies:
                    placeholders = ",".join("?" for _ in dependencies)
                    incomplete = self._connection.execute(
                        f"""SELECT COUNT(*) FROM work_items
                            WHERE id IN ({placeholders}) AND state!='completed'""",
                        dependencies,
                    ).fetchone()[0]
                    if incomplete:
                        if candidate["state"] != "blocked":
                            self._connection.execute(
                                "UPDATE work_items SET state='blocked',updated_at=? WHERE id=?", (now, candidate["id"])
                            )
                        continue
                prior = self._connection.execute(
                    "SELECT COALESCE(MAX(attempt),0) FROM execution_runs WHERE task_id=?", (candidate["id"],)
                ).fetchone()[0]
                if prior >= max_attempts:
                    self._connection.execute(
                        "UPDATE work_items SET state='failed',updated_at=? WHERE id=?", (now, candidate["id"])
                    )
                    continue
                selected = candidate
                attempt = prior + 1
                break
            if selected is None:
                self._commit_if_needed()
                return None
            cursor = self._connection.execute(
                """UPDATE work_items SET state='in_progress',updated_at=?
                    WHERE id=? AND state IN ('assigned','blocked')""",
                (now, selected["id"]),
            )
            if cursor.rowcount != 1:
                self._connection.rollback()
                return None
            self._connection.execute(
                """INSERT INTO execution_runs(
                    id,task_id,worker_id,attempt,state,lease_until,heartbeat_at,started_at,result
                    ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (run_id, selected["id"], worker_id.strip(), attempt, "running", lease_until, now, now, "{}"),
            )
        return {"run": self._get_execution(run_id), "task": self.get_work_item(selected["id"])}

    def heartbeat_execution(self, run_id: str, *, worker_id: str, lease_seconds: int = 900) -> dict[str, Any]:
        now_dt = datetime.now(UTC)
        lease_until = (now_dt + timedelta(seconds=max(30, min(int(lease_seconds), 86_400)))).isoformat()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE execution_runs SET heartbeat_at=?,lease_until=?
                WHERE id=? AND worker_id=? AND state='running'""",
                (now_dt.isoformat(), lease_until, run_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Execution lease is no longer active or belongs to another worker")
            self._commit_if_needed()
        return self._get_execution(run_id)

    def finish_execution(
        self,
        run_id: str,
        *,
        worker_id: str,
        succeeded: bool,
        result: dict[str, Any] | None = None,
        error: str = "",
        retryable: bool = True,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Close a lease and deterministically retry or fail an interrupted task."""
        now = utc_now()
        with self.atomic_block():
            run = self._connection.execute("SELECT * FROM execution_runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"Unknown execution run: {run_id}")
            if run["worker_id"] != worker_id:
                raise ValueError("Execution lease belongs to another worker")
            if run["state"] != "running":
                raise ValueError(f"Execution run is already {run['state']}")
            state = "succeeded" if succeeded else "failed"
            self._connection.execute(
                """UPDATE execution_runs SET state=?,finished_at=?,heartbeat_at=?,
                    error=?,result=? WHERE id=?""",
                (state, now, now, error[:4000], json.dumps(result or {}, sort_keys=True, default=str), run_id),
            )
            if not succeeded:
                retry = retryable and run["attempt"] < max(1, max_attempts)
                task_state = "assigned" if retry else "failed"
                summary = (
                    f"EXECUTION ATTEMPT {run['attempt']} FAILED: {error[:2000]}"
                    if error
                    else f"EXECUTION ATTEMPT {run['attempt']} FAILED"
                )
                self._connection.execute(
                    """UPDATE work_items SET state=?,updated_at=?,
                        summary=CASE WHEN summary='' THEN ? ELSE ? || '\n\n' || summary END
                        WHERE id=? AND state='in_progress'""",
                    (task_state, now, summary, summary, run["task_id"]),
                )
        return self._get_execution(run_id)

    def execution_status(self) -> dict[str, Any]:
        with self._lock:
            counts = {
                row["state"]: row["count"]
                for row in self._connection.execute(
                    "SELECT state,COUNT(*) AS count FROM execution_runs GROUP BY state"
                ).fetchall()
            }
            active = [
                self._decode_row(row)
                for row in self._connection.execute(
                    """SELECT * FROM execution_runs WHERE state IN ('leased','running')
                    ORDER BY started_at"""
                ).fetchall()
            ]
        return {"counts": counts, "active": active}

    # -- Content factory --------------------------------------------------

    def create_content_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {"status": "draft", "config": {}, **campaign}
        with self._lock:
            self._connection.execute(
                "INSERT INTO content_campaigns(id,title,audience,business_objective,status,config,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    values["id"],
                    values["title"],
                    values["audience"],
                    values["business_objective"],
                    values["status"],
                    json.dumps(values["config"]),
                    now,
                    now,
                ),
            )
            self._commit_if_needed()
        return self.get_content_campaign(values["id"])

    def get_content_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM content_campaigns WHERE id=?", (campaign_id,)).fetchone()
        result = self._decode_row(row)
        if result is None:
            raise KeyError(f"Unknown content campaign: {campaign_id}")
        return result

    def add_content_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {"status": "draft", "source_url": "", "creator": "", "licence": "", "asset_metadata": {}, **asset}
        with self._lock:
            self._connection.execute(
                """INSERT INTO content_assets(id,campaign_id,asset_type,uri,sha256,status,source_url,
                creator,licence,asset_metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["campaign_id"],
                    values["asset_type"],
                    values["uri"],
                    values["sha256"],
                    values["status"],
                    values["source_url"],
                    values["creator"],
                    values["licence"],
                    json.dumps(values["asset_metadata"]),
                    now,
                    now,
                ),
            )
            self._commit_if_needed()
        with self._lock:
            row = self._connection.execute("SELECT * FROM content_assets WHERE id=?", (values["id"],)).fetchone()
        return self._decode_row(row)  # type: ignore[return-value]

    def list_content_assets(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM content_assets WHERE campaign_id=? ORDER BY created_at", (campaign_id,)
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def record_content_metrics(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._connection.execute(
                """INSERT INTO content_metrics(id,campaign_id,platform,window,captured_at,metrics)
                VALUES(?,?,?,?,?,?) ON CONFLICT(campaign_id,platform,window) DO UPDATE SET
                captured_at=excluded.captured_at,metrics=excluded.metrics""",
                (
                    entry["id"],
                    entry["campaign_id"],
                    entry["platform"],
                    entry["window"],
                    entry.get("captured_at", utc_now()),
                    json.dumps(entry["metrics"]),
                ),
            )
            self._commit_if_needed()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM content_metrics WHERE campaign_id=? AND platform=? AND window=?",
                (entry["campaign_id"], entry["platform"], entry["window"]),
            ).fetchone()
        return self._decode_row(row)  # type: ignore[return-value]

    def list_content_metrics(
        self,
        *,
        campaign_id: str | None = None,
        platform: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if campaign_id:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
        if platform:
            clauses.append("platform=?")
            params.append(platform)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM content_metrics{where} ORDER BY captured_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def record_content_lesson(
        self,
        *,
        campaign_id: str,
        lesson: str,
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        identifier = f"lesson_{uuid.uuid4().hex[:16]}"
        created_at = utc_now()
        with self._lock:
            self._connection.execute(
                "INSERT INTO content_lessons(id,campaign_id,lesson,evidence_refs,created_at) VALUES(?,?,?,?,?)",
                (identifier, campaign_id, lesson, json.dumps(evidence_refs), created_at),
            )
            self._commit_if_needed()
            row = self._connection.execute("SELECT * FROM content_lessons WHERE id=?", (identifier,)).fetchone()
        return self._decode_row(row)  # type: ignore[return-value]

    def list_content_lessons(self, campaign_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM content_lessons WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
                (campaign_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    # -- Distribution control plane ------------------------------------

    def create_distribution_publication(self, publication: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "account_ref": "",
            "scheduled_at": None,
            "outbox_event_id": "",
            "external_id": "",
            "provider": "",
            "provider_status": "",
            "error": "",
            "metadata": {},
            **publication,
        }
        with self._lock:
            try:
                self._connection.execute(
                    """INSERT INTO distribution_publications(
                    id,campaign_id,task_id,platform,account_ref,visibility,title,body,asset_ids,
                    payload_hash,idempotency_key,status,scheduled_at,outbox_event_id,external_id,
                    provider,provider_status,error,metadata,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        values["id"],
                        values["campaign_id"],
                        values["task_id"],
                        values["platform"],
                        values["account_ref"],
                        values["visibility"],
                        values["title"],
                        values["body"],
                        json.dumps(values["asset_ids"]),
                        values["payload_hash"],
                        values["idempotency_key"],
                        values["status"],
                        values["scheduled_at"],
                        values["outbox_event_id"],
                        values["external_id"],
                        values["provider"],
                        values["provider_status"],
                        values["error"],
                        json.dumps(values["metadata"]),
                        now,
                        now,
                    ),
                )
                self._commit_if_needed()
            except sqlite3.IntegrityError:
                row = self._connection.execute(
                    "SELECT * FROM distribution_publications WHERE idempotency_key=?",
                    (values["idempotency_key"],),
                ).fetchone()
                if row is not None:
                    return self._decode_row(row)  # type: ignore[return-value]
                raise
        return self.get_distribution_publication(values["id"])

    def get_distribution_publication(self, publication_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM distribution_publications WHERE id=?",
                (publication_id,),
            ).fetchone()
        result = self._decode_row(row)
        if result is None:
            raise KeyError(f"Unknown distribution publication: {publication_id}")
        return result

    def list_distribution_publications(
        self,
        *,
        status: str | None = None,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if campaign_id:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
        query = "SELECT * FROM distribution_publications"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_distribution_publication(self, publication_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "scheduled_at",
            "outbox_event_id",
            "external_id",
            "provider",
            "provider_status",
            "error",
            "metadata",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid distribution publication fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_distribution_publication(publication_id)
        fields["updated_at"] = utc_now()
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            if key == "metadata":
                value = json.dumps(value)
            params.append(value)
        params.append(publication_id)
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE distribution_publications SET {', '.join(assignments)} WHERE id=?",
                params,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown distribution publication: {publication_id}")
            self._commit_if_needed()
        return self.get_distribution_publication(publication_id)

    # -- Review attestations and operational telemetry -----------------

    def record_review_attestation(
        self,
        attestation: dict[str, Any],
    ) -> dict[str, Any]:
        identifier = str(attestation.get("id") or f"review_{uuid.uuid4().hex[:16]}")
        decision = attestation.get("decision") or {}
        deterministic = attestation.get("deterministic_review") or {}
        submission_sha256 = str(deterministic.get("submission_sha256", ""))
        if not submission_sha256:
            raise ValueError("Review attestation requires a submission digest")
        with self._lock:
            self._connection.execute(
                """INSERT INTO review_attestations(
                id,task_id,reviewer_id,reviewer_model,submission_sha256,
                decision,signature,attestation,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    identifier,
                    attestation["task_id"],
                    attestation["reviewer_id"],
                    attestation["reviewer_model"],
                    submission_sha256,
                    json.dumps(decision, sort_keys=True, default=str),
                    attestation["signature"],
                    json.dumps(attestation, sort_keys=True, default=str),
                    attestation["created_at"],
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM review_attestations WHERE id=?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Review attestation insert did not persist")
        result = dict(row)
        result["decision"] = json.loads(result["decision"])
        result["attestation"] = json.loads(result["attestation"])
        return result

    def list_review_attestations(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM review_attestations"
        params: list[Any] = []
        if task_id:
            query += " WHERE task_id=?"
            params.append(task_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["decision"] = json.loads(item["decision"])
            item["attestation"] = json.loads(item["attestation"])
            results.append(item)
        return results

    @staticmethod
    def _metric_labels_key(labels: dict[str, str]) -> str:
        return json.dumps(labels, sort_keys=True, separators=(",", ":"))

    def cost_total_since(self, start_iso: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM costs WHERE created_at>=?",
                (start_iso,),
            ).fetchone()
        return int(row[0] if row else 0)

    def record_metric(
        self,
        *,
        name: str,
        labels: dict[str, str],
        value: float,
    ) -> dict[str, Any]:
        labels_key = self._metric_labels_key(labels)
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO operational_metrics(name,labels_key,labels,value,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(name,labels_key) DO UPDATE SET
                value=operational_metrics.value+excluded.value,
                updated_at=excluded.updated_at""",
                (
                    name,
                    labels_key,
                    json.dumps(labels, sort_keys=True),
                    value,
                    now,
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM operational_metrics WHERE name=? AND labels_key=?",
                (name, labels_key),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Metric update did not persist")
        return decoded

    def list_metrics(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT name,labels,value,updated_at FROM operational_metrics ORDER BY name,labels_key"
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def record_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO operational_traces(
                id,operation,outcome,duration_ms,attributes,error,created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    trace["id"],
                    trace["operation"],
                    trace["outcome"],
                    float(trace["duration_ms"]),
                    json.dumps(trace.get("attributes") or {}, sort_keys=True, default=str),
                    str(trace.get("error", ""))[:1000],
                    now,
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM operational_traces WHERE id=?",
                (trace["id"],),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Trace insert did not persist")
        return decoded

    def list_traces(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM operational_traces ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def create_alert(self, alert: dict[str, Any]) -> dict[str, Any]:
        severity = str(alert["severity"]).lower()
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("Alert severity must be info, warning, or critical")
        now = utc_now()
        with self._lock:
            self._connection.execute(
                """INSERT INTO operational_alerts(
                id,severity,code,message,resource_id,status,details,created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    alert["id"],
                    severity,
                    alert["code"],
                    alert["message"],
                    alert.get("resource_id", ""),
                    "open",
                    json.dumps(alert.get("details") or {}, sort_keys=True, default=str),
                    now,
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM operational_alerts WHERE id=?",
                (alert["id"],),
            ).fetchone()
        result = dict(row) if row is not None else None
        if result is None:
            raise RuntimeError("Alert insert did not persist")
        result["details"] = json.loads(result["details"])
        return result

    def list_alerts(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM operational_alerts"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            results.append(item)
        return results

    def resolve_alert(self, alert_id: str) -> dict[str, Any]:
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE operational_alerts
                SET status='resolved',resolved_at=?
                WHERE id=? AND status='open'""",
                (utc_now(), alert_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown or resolved alert: {alert_id}")
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM operational_alerts WHERE id=?",
                (alert_id,),
            ).fetchone()
        result = dict(row) if row is not None else None
        if result is None:
            raise RuntimeError("Resolved alert is missing")
        result["details"] = json.loads(result["details"])
        return result

    # -- Company autonomy signals and run ledger -------------------------

    def create_company_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "id": signal.get("id") or f"sig_{uuid.uuid4().hex[:16]}",
            "idempotency_key": str(signal["idempotency_key"]),
            "signal_type": str(signal["signal_type"]),
            "source": str(signal.get("source") or "internal"),
            "severity": str(signal.get("severity") or "medium"),
            "status": "pending",
            "department": str(signal.get("department") or ""),
            "payload": dict(signal.get("payload") or {}),
            "programme_id": "",
            "error": "",
            "claimed_by": "",
            "claim_until": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }
        with self._lock:
            self._connection.execute(
                """INSERT OR IGNORE INTO company_signals(
                id,idempotency_key,signal_type,source,severity,status,department,payload,
                programme_id,error,claimed_by,claim_until,created_at,updated_at,resolved_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["id"],
                    values["idempotency_key"],
                    values["signal_type"],
                    values["source"],
                    values["severity"],
                    values["status"],
                    values["department"],
                    json.dumps(values["payload"]),
                    values["programme_id"],
                    values["error"],
                    values["claimed_by"],
                    values["claim_until"],
                    values["created_at"],
                    values["updated_at"],
                    values["resolved_at"],
                ),
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM company_signals WHERE idempotency_key=?",
                (values["idempotency_key"],),
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Company signal insert did not persist")
        return decoded

    def get_company_signal(self, signal_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM company_signals WHERE id=?", (signal_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown company signal: {signal_id}")
        return decoded

    def list_company_signals(
        self,
        *,
        status: str | None = None,
        signal_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if signal_type:
            clauses.append("signal_type=?")
            params.append(signal_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM company_signals{where} ORDER BY created_at ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def claim_company_signals(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))).isoformat()
        claimed: list[dict[str, Any]] = []
        with self.atomic_block():
            self._connection.execute(
                """UPDATE company_signals
                   SET status='pending',claimed_by='',claim_until=NULL,updated_at=?
                   WHERE status='claimed' AND claim_until IS NOT NULL AND claim_until < ?""",
                (now.isoformat(), now.isoformat()),
            )
            rows = self._connection.execute(
                """SELECT id FROM company_signals
                   WHERE status='pending'
                   ORDER BY CASE severity
                       WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                       created_at ASC
                   LIMIT ?""",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            for row in rows:
                cursor = self._connection.execute(
                    """UPDATE company_signals
                       SET status='claimed',claimed_by=?,claim_until=?,updated_at=?
                       WHERE id=? AND status='pending'""",
                    (worker_id, lease_until, now.isoformat(), row["id"]),
                )
                if cursor.rowcount == 1:
                    claimed_row = self._connection.execute(
                        "SELECT * FROM company_signals WHERE id=?", (row["id"],)
                    ).fetchone()
                    decoded = self._decode_row(claimed_row)
                    if decoded is not None:
                        claimed.append(decoded)
        return claimed

    def complete_company_signal(
        self,
        signal_id: str,
        *,
        programme_id: str,
        status: str = "resolved",
        error: str = "",
    ) -> dict[str, Any]:
        if status not in {"resolved", "ignored", "failed"}:
            raise ValueError("Invalid company signal completion status")
        now = utc_now()
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE company_signals
                   SET status=?,programme_id=?,error=?,claimed_by='',claim_until=NULL,
                       updated_at=?,resolved_at=?
                   WHERE id=? AND status IN ('pending','claimed')""",
                (status, programme_id, error, now, now, signal_id),
            )
            if cursor.rowcount != 1:
                current = self.get_company_signal(signal_id)
                if current["status"] == status:
                    return current
                raise ValueError(f"Company signal is already {current['status']}")
            self._commit_if_needed()
        return self.get_company_signal(signal_id)

    def release_company_signal(self, signal_id: str, *, error: str) -> dict[str, Any]:
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE company_signals
                   SET status='pending',error=?,claimed_by='',claim_until=NULL,updated_at=?
                   WHERE id=? AND status='claimed'""",
                (error, utc_now(), signal_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Company signal is not currently claimed")
            self._commit_if_needed()
        return self.get_company_signal(signal_id)

    def create_venture_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "status": "discovered",
            "strategic_fit": "",
            **opportunity,
            "created_at": now,
            "updated_at": now,
        }
        columns = (
            "id",
            "title",
            "problem",
            "target_user",
            "product_type",
            "source",
            "evidence",
            "score_components",
            "total_score",
            "estimated_build_days",
            "monetization",
            "distribution_channel",
            "status",
            "strategic_fit",
            "created_at",
            "updated_at",
        )
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO venture_opportunities({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        return self.get_venture_opportunity(values["id"])

    def get_venture_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM venture_opportunities WHERE id=?", (opportunity_id,)
            ).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown venture opportunity: {opportunity_id}")
        return decoded

    def list_venture_opportunities(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where = " WHERE status=?" if status else ""
        params: list[Any] = [status] if status else []
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM venture_opportunities{where} ORDER BY total_score DESC, created_at ASC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_venture_opportunity(self, opportunity_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "strategic_fit",
            "evidence",
            "score_components",
            "total_score",
            "monetization",
            "distribution_channel",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid venture opportunity fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_venture_opportunity(opportunity_id)
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = [json.dumps(value) if key in self.JSON_COLUMNS else value for key, value in fields.items()]
        values.append(opportunity_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE venture_opportunities SET {assignments} WHERE id=?", values)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown venture opportunity: {opportunity_id}")
            self._commit_if_needed()
        return self.get_venture_opportunity(opportunity_id)

    def create_venture_experiment(self, experiment: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "stage": "planned",
            "spent_cents": 0,
            "current_value": 0.0,
            "recommendation": "",
            "decision": "",
            "decision_reason": "",
            "programme_id": "",
            "metadata": {},
            "started_at": None,
            "deadline": None,
            **experiment,
            "created_at": now,
            "updated_at": now,
        }
        columns = (
            "id",
            "opportunity_id",
            "product_name",
            "hypothesis",
            "stage",
            "timebox_days",
            "budget_cents",
            "spent_cents",
            "primary_metric",
            "target_value",
            "kill_threshold",
            "current_value",
            "recommendation",
            "decision",
            "decision_reason",
            "programme_id",
            "metadata",
            "started_at",
            "deadline",
            "created_at",
            "updated_at",
        )
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO venture_experiments({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        return self.get_venture_experiment(values["id"])

    def create_venture_experiment_with_slot(self, experiment: dict[str, Any], *, max_active: int) -> dict[str, Any]:
        """Atomically reserve a bounded startup-studio slot and create the sprint."""
        max_active = max(1, int(max_active))
        with self.atomic_block():
            occupied = {
                int(row["slot_number"])
                for row in self._connection.execute("SELECT slot_number FROM venture_sprint_slots").fetchall()
            }
            slot = next((candidate for candidate in range(1, max_active + 1) if candidate not in occupied), None)
            if slot is None:
                raise RuntimeError(f"Amaura Ventures allows only {max_active} active validation sprint(s)")
            created = self.create_venture_experiment(experiment)
            self._connection.execute(
                "INSERT INTO venture_sprint_slots(slot_number,experiment_id,acquired_at) VALUES(?,?,?)",
                (slot, created["id"], utc_now()),
            )
            metadata = dict(created.get("metadata") or {})
            metadata["sprint_slot"] = slot
            self.update_venture_experiment(created["id"], metadata=metadata)
        return self.get_venture_experiment(experiment["id"])

    def release_venture_sprint_slot(self, experiment_id: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM venture_sprint_slots WHERE experiment_id=?", (experiment_id,))
            self._commit_if_needed()

    def get_venture_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM venture_experiments WHERE id=?", (experiment_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown venture experiment: {experiment_id}")
        return decoded

    def list_venture_experiments(
        self, *, stage: str | None = None, opportunity_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if stage:
            clauses.append("stage=?")
            params.append(stage)
        if opportunity_id:
            clauses.append("opportunity_id=?")
            params.append(opportunity_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 2000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM venture_experiments{where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_venture_experiment(self, experiment_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "stage",
            "spent_cents",
            "current_value",
            "recommendation",
            "decision",
            "decision_reason",
            "programme_id",
            "metadata",
            "started_at",
            "deadline",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid venture experiment fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_venture_experiment(experiment_id)
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = [json.dumps(value) if key in self.JSON_COLUMNS else value for key, value in fields.items()]
        values.append(experiment_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE venture_experiments SET {assignments} WHERE id=?", values)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown venture experiment: {experiment_id}")
            if "stage" in fields and fields["stage"] not in {
                "validating",
                "building",
                "launching",
                "measuring",
                "scaling",
            }:
                self._connection.execute("DELETE FROM venture_sprint_slots WHERE experiment_id=?", (experiment_id,))
            self._commit_if_needed()
        return self.get_venture_experiment(experiment_id)

    def create_venture_cashflow_stream(self, stream: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "experiment_id": "",
            "status": "draft",
            "currency": "INR",
            "price_cents": 0,
            "unit_cost_cents": 0,
            "founder_minutes_per_week": 0,
            "automation_level": 0,
            "launch_url": "",
            "metadata": {},
            **stream,
            "created_at": now,
            "updated_at": now,
        }
        columns = (
            "id",
            "opportunity_id",
            "experiment_id",
            "name",
            "lane",
            "platform",
            "status",
            "offer",
            "target_user",
            "distribution_channel",
            "currency",
            "price_cents",
            "unit_cost_cents",
            "founder_minutes_per_week",
            "automation_level",
            "launch_url",
            "metadata",
            "created_at",
            "updated_at",
        )
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO venture_cashflow_streams({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        return self.get_venture_cashflow_stream(values["id"])

    def create_venture_cashflow_stream_guarded(
        self, stream: dict[str, Any], *, max_founder_minutes: int
    ) -> dict[str, Any]:
        """Atomically enforce the portfolio founder-attention cap and insert a stream."""
        requested = int(stream.get("founder_minutes_per_week") or 0)
        with self.atomic_block():
            used = int(
                self._connection.execute(
                    "SELECT COALESCE(SUM(founder_minutes_per_week),0) FROM venture_cashflow_streams "
                    "WHERE status IN ('validation','ready','live')"
                ).fetchone()[0]
            )
            if used + requested > int(max_founder_minutes):
                raise ValueError(
                    f"Portfolio founder-attention cap exceeded: {used + requested} > {int(max_founder_minutes)} minutes/week"
                )
            created = self.create_venture_cashflow_stream(stream)
        return created

    def transition_venture_cashflow_stream_guarded(
        self, stream_id: str, *, status: str, max_live: int, max_founder_minutes: int
    ) -> dict[str, Any]:
        """Atomically enforce live-stream and founder-time caps during activation."""
        active_states = {"validation", "ready", "live"}
        with self.atomic_block():
            current = self.get_venture_cashflow_stream(stream_id)
            if status in active_states and current.get("status") not in active_states:
                used = int(
                    self._connection.execute(
                        "SELECT COALESCE(SUM(founder_minutes_per_week),0) FROM venture_cashflow_streams "
                        "WHERE id<>? AND status IN ('validation','ready','live')",
                        (stream_id,),
                    ).fetchone()[0]
                )
                requested = int(current.get("founder_minutes_per_week") or 0)
                if used + requested > int(max_founder_minutes):
                    raise ValueError(
                        f"Portfolio founder-attention cap exceeded: {used + requested} > {int(max_founder_minutes)} minutes/week"
                    )
            if status == "live":
                live = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM venture_cashflow_streams WHERE id<>? AND status='live'", (stream_id,)
                    ).fetchone()[0]
                )
                if live >= int(max_live):
                    raise ValueError(f"Portfolio live-stream cap reached ({int(max_live)})")
            updated = self.update_venture_cashflow_stream(stream_id, status=status)
        return updated

    def get_venture_cashflow_stream(self, stream_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM venture_cashflow_streams WHERE id=?", (stream_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown venture cash-flow stream: {stream_id}")
        return decoded

    def list_venture_cashflow_streams(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where = " WHERE status=?" if status else ""
        params: list[Any] = [status] if status else []
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM venture_cashflow_streams{where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def update_venture_cashflow_stream(self, stream_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "platform",
            "offer",
            "distribution_channel",
            "currency",
            "price_cents",
            "unit_cost_cents",
            "founder_minutes_per_week",
            "automation_level",
            "launch_url",
            "metadata",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid venture cash-flow stream fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_venture_cashflow_stream(stream_id)
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = [json.dumps(value) if key in self.JSON_COLUMNS else value for key, value in fields.items()]
        values.append(stream_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE venture_cashflow_streams SET {assignments} WHERE id=?", values)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown venture cash-flow stream: {stream_id}")
            self._commit_if_needed()
        return self.get_venture_cashflow_stream(stream_id)

    def record_venture_financial_event(self, event: dict[str, Any]) -> dict[str, Any]:
        values = {"metadata": {}, **event, "created_at": utc_now()}
        values = {"trust_level": "unverified", "provider": "", "external_event_id": "", **values}
        columns = (
            "id",
            "stream_id",
            "event_type",
            "amount_cents",
            "currency",
            "source",
            "evidence",
            "trust_level",
            "provider",
            "external_event_id",
            "idempotency_key",
            "occurred_at",
            "metadata",
            "created_at",
        )
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT OR IGNORE INTO venture_financial_events({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
            row = self._connection.execute(
                "SELECT * FROM venture_financial_events WHERE idempotency_key=?", (values["idempotency_key"],)
            ).fetchone()
        decoded = self._decode_row(row)
        assert decoded is not None
        return decoded

    def list_venture_financial_events(self, stream_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM venture_financial_events WHERE stream_id=? ORDER BY occurred_at ASC LIMIT ?",
                (stream_id, max(1, min(int(limit), 10000))),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def create_venture_cashflow_action(self, action: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        values = {
            "stream_id": "",
            "status": "proposed",
            "priority": 3,
            "requires_founder_approval": False,
            "payload": {},
            "payload_hash": "",
            "approval_id": "",
            "approval_task_id": "",
            "mission_id": "",
            "result": {},
            "due_at": "",
            **action,
            "created_at": now,
            "updated_at": now,
        }
        columns = (
            "id",
            "stream_id",
            "action_type",
            "title",
            "status",
            "priority",
            "requires_founder_approval",
            "payload",
            "payload_hash",
            "approval_id",
            "approval_task_id",
            "mission_id",
            "result",
            "due_at",
            "created_at",
            "updated_at",
        )
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO venture_cashflow_actions({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        return self.get_venture_cashflow_action(values["id"])

    def get_venture_cashflow_action(self, action_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM venture_cashflow_actions WHERE id=?", (action_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise KeyError(f"Unknown venture cash-flow action: {action_id}")
        if "requires_founder_approval" in decoded:
            decoded["requires_founder_approval"] = bool(decoded["requires_founder_approval"])
        return decoded

    def list_venture_cashflow_actions(
        self, *, status: str | None = None, stream_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if stream_id:
            clauses.append("stream_id=?")
            params.append(stream_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM venture_cashflow_actions{where} ORDER BY priority ASC, created_at ASC LIMIT ?", params
            ).fetchall()
        decoded = [decoded_row for row in rows if (decoded_row := self._decode_row(row)) is not None]
        for row in decoded:
            row["requires_founder_approval"] = bool(row.get("requires_founder_approval"))
        return decoded

    def update_venture_cashflow_action(self, action_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "priority",
            "requires_founder_approval",
            "payload",
            "payload_hash",
            "approval_id",
            "approval_task_id",
            "mission_id",
            "result",
            "due_at",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Invalid venture cash-flow action fields: {', '.join(sorted(invalid))}")
        if not fields:
            return self.get_venture_cashflow_action(action_id)
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        values = [json.dumps(value) if key in self.JSON_COLUMNS else value for key, value in fields.items()]
        values.append(action_id)
        with self._lock:
            cursor = self._connection.execute(f"UPDATE venture_cashflow_actions SET {assignments} WHERE id=?", values)
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown venture cash-flow action: {action_id}")
            self._commit_if_needed()
        return self.get_venture_cashflow_action(action_id)

    def record_venture_metric(self, event: dict[str, Any]) -> dict[str, Any]:
        values = {**event, "created_at": utc_now()}
        columns = ("id", "experiment_id", "metric_name", "value", "source", "evidence", "captured_at", "created_at")
        encoded = [json.dumps(values[c]) if c in self.JSON_COLUMNS else values[c] for c in columns]
        with self._lock:
            self._connection.execute(
                f"INSERT INTO venture_metric_events({', '.join(columns)}) VALUES({', '.join('?' for _ in columns)})",
                encoded,
            )
            self._commit_if_needed()
        with self._lock:
            row = self._connection.execute("SELECT * FROM venture_metric_events WHERE id=?", (values["id"],)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Venture metric insert did not persist")
        return decoded

    def list_venture_metrics(self, experiment_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM venture_metric_events WHERE experiment_id=? ORDER BY captured_at ASC LIMIT ?",
                (experiment_id, max(1, min(int(limit), 5000))),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def start_autonomy_run(self, *, worker_id: str, mode: str) -> dict[str, Any]:
        run_id = f"auto_{uuid.uuid4().hex[:16]}"
        started_at = utc_now()
        with self._lock:
            self._connection.execute(
                "INSERT INTO autonomy_runs(id,worker_id,mode,status,result,started_at,finished_at) VALUES(?,?,?,'running','{}',?,NULL)",
                (run_id, worker_id, mode, started_at),
            )
            self._commit_if_needed()
        return {
            "id": run_id,
            "worker_id": worker_id,
            "mode": mode,
            "status": "running",
            "result": {},
            "started_at": started_at,
            "finished_at": None,
        }

    def finish_autonomy_run(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in {"completed", "partial", "failed", "paused"}:
            raise ValueError("Invalid autonomy run status")
        finished_at = utc_now()
        max_result_bytes = max(
            4096,
            min(int(os.environ.get("AMAURA_AUTONOMY_RUN_RESULT_MAX_BYTES", "65536")), 1_000_000),
        )
        bounded_result = _bounded_json_record(result, max_bytes=max_result_bytes)
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE autonomy_runs SET status=?,result=?,finished_at=? WHERE id=? AND status='running'",
                (status, json.dumps(bounded_result), finished_at, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown or completed autonomy run: {run_id}")
            self._commit_if_needed()
            row = self._connection.execute("SELECT * FROM autonomy_runs WHERE id=?", (run_id,)).fetchone()
        decoded = self._decode_row(row)
        if decoded is None:
            raise RuntimeError("Autonomy run completion did not persist")
        return decoded

    def list_autonomy_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM autonomy_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [self._decode_row(row) for row in rows]  # type: ignore[misc]

    def dashboard(self) -> dict[str, Any]:
        with self._lock:
            states = {
                row["state"]: row["count"]
                for row in self._connection.execute(
                    "SELECT state, COUNT(*) AS count FROM work_items WHERE item_type = 'task' GROUP BY state"
                ).fetchall()
            }
            departments = {
                row["department"]: row["count"]
                for row in self._connection.execute(
                    "SELECT department, COUNT(*) AS count FROM agents WHERE enabled = 1 GROUP BY department"
                ).fetchall()
            }
            pending = self._connection.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]
            total_cost = self._connection.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM costs").fetchone()[0]
            active_programmes = self._connection.execute(
                "SELECT COUNT(*) FROM work_items WHERE item_type = 'programme' AND state NOT IN ('completed','cancelled','failed')"
            ).fetchone()[0]
            violations = self._connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE outcome = 'denied'"
            ).fetchone()[0]
            open_alerts = self._connection.execute(
                "SELECT COUNT(*) FROM operational_alerts WHERE status='open'"
            ).fetchone()[0]
            active_objectives = self._connection.execute(
                "SELECT COUNT(*) FROM company_objectives WHERE status='active'"
            ).fetchone()[0]
            completed_objectives = self._connection.execute(
                "SELECT COUNT(*) FROM company_objectives WHERE status='completed'"
            ).fetchone()[0]
            qualified_ventures = self._connection.execute(
                "SELECT COUNT(*) FROM venture_opportunities WHERE status IN ('qualified','selected','experimenting')"
            ).fetchone()[0]
            active_venture_experiments = self._connection.execute(
                "SELECT COUNT(*) FROM venture_experiments WHERE stage IN ('validating','building','launching','measuring','scaling')"
            ).fetchone()[0]
        return {
            "control_plane": "jarvis",
            "active_programmes": active_programmes,
            "task_states": states,
            "pending_approvals": pending,
            "total_cost_cents": total_cost,
            "policy_violations": violations,
            "open_alerts": open_alerts,
            "objectives": {"active": active_objectives, "completed": completed_objectives},
            "ventures": {
                "qualified_opportunities": qualified_ventures,
                "active_experiments": active_venture_experiments,
            },
            "agents": {"total": sum(departments.values()), "departments": departments},
        }
