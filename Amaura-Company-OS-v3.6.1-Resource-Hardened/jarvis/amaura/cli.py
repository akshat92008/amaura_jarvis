"""Operator CLI for the local, internal Amaura workforce."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT.parents[1]
SOURCE_CHECKOUT = (SOURCE_ROOT / "pyproject.toml").is_file() and (SOURCE_ROOT / "jarvis").is_dir()
REPOSITORY_ROOT = SOURCE_ROOT if SOURCE_CHECKOUT else Path.cwd().resolve()
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.amaura"
ENV_TEMPLATE = (
    SOURCE_ROOT / ".env.amaura.example"
    if SOURCE_CHECKOUT
    else PACKAGE_ROOT / "resources" / "env.amaura.example"
)
SANDBOX_DOCKERFILE = (
    SOURCE_ROOT / "docker" / "amaura-sandbox.Dockerfile"
    if SOURCE_CHECKOUT
    else PACKAGE_ROOT / "resources" / "amaura-sandbox.Dockerfile"
)
_SECRET_NAMES = {
    "AMAURA_OPERATOR_KEY",
    "AMAURA_APPROVAL_KEY",
    "AMAURA_REVIEW_ATTESTATION_KEY",
    "AMAURA_PROVIDER_RECEIPT_KEY",
    "AMAURA_AUDIT_HMAC_KEY",
    "AMAURA_EVIDENCE_HMAC_KEY",
    "AMAURA_EVALUATION_PACK_HMAC_KEY",
    "JARVIS_API_KEY",
}
_SECRET_PLACEHOLDER = "replace-with-independent-random-value"


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def load_env_file(path: str | Path, *, override: bool = False) -> dict[str, str]:
    """Compatibility wrapper around the strict Amaura environment loader."""

    loaded = load_amaura_env(
        path,
        override=override,
        require_private_permissions=True,
    )
    return {"path": str(loaded)} if loaded else {}


def _render_env_template() -> str:
    if not ENV_TEMPLATE.exists():
        raise RuntimeError(f"Missing environment template: {ENV_TEMPLATE}")
    directory_values = {
        "AMAURA_DATA_DIR": str(REPOSITORY_ROOT / ".amaura-data"),
        "JARVIS_DATA_DIR": str(REPOSITORY_ROOT / ".jarvis-data"),
        "AMAURA_EVIDENCE_DIR": str(REPOSITORY_ROOT / ".amaura-data" / "evidence"),
        "AMAURA_BACKUP_DIR": str(REPOSITORY_ROOT.parent / f"{REPOSITORY_ROOT.name}-backups"),
        "AMAURA_AUDIT_CHECKPOINT_PATH": str(REPOSITORY_ROOT.parent / f"{REPOSITORY_ROOT.name}-trust" / "audit-head.json"),
    }
    lines: list[str] = []
    generated_authorities: set[str] = set()
    for raw_line in ENV_TEMPLATE.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            lines.append(raw_line)
            continue
        name, value = raw_line.split("=", 1)
        if name == "AMAURA_REVIEWER_KEYS":
            reviewer_entries: list[str] = []
            for entry in value.split(","):
                reviewer_id, separator, reviewer_key = entry.strip().partition(":")
                if not separator or not reviewer_id:
                    raise RuntimeError("AMAURA_REVIEWER_KEYS must use reviewer_id:key entries")
                if reviewer_key in {"", _SECRET_PLACEHOLDER}:
                    reviewer_key = secrets.token_urlsafe(48)
                reviewer_entries.append(f"{reviewer_id}:{reviewer_key}")
            value = ",".join(reviewer_entries)
            generated_authorities.add(name)
        elif name in _SECRET_NAMES or value == _SECRET_PLACEHOLDER:
            value = secrets.token_urlsafe(48)
            if name in _SECRET_NAMES:
                generated_authorities.add(name)
        elif name in directory_values:
            value = directory_values[name]
        lines.append(f"{name}={value}")
    required_authorities = _SECRET_NAMES | {"AMAURA_REVIEWER_KEYS"}
    missing_authorities = sorted(required_authorities - generated_authorities)
    if missing_authorities:
        raise RuntimeError(
            "Failed to generate every independent Amaura authority secret: "
            + ", ".join(missing_authorities)
        )
    return "\n".join(lines) + "\n"


def _build_sandbox() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"ok": False, "error": "docker_not_installed"}
    dockerfile = SANDBOX_DOCKERFILE
    if not dockerfile.is_file():
        return {"ok": False, "error": "sandbox_dockerfile_missing", "path": str(dockerfile)}
    image = os.environ.get("AMAURA_SANDBOX_IMAGE", "amaura-sandbox:3.6.0")
    completed = subprocess.run(
        [docker, "build", "-f", str(dockerfile), "-t", image, str(REPOSITORY_ROOT)],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    smoke = None
    if completed.returncode == 0:
        smoke = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                image,
                "sh",
                "-lc",
                (
                    "python --version && python -m pytest --version && "
                    "ruff --version && mypy --version && node --version && "
                    "npm --version && git --version && rg --version"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    image_digest = ""
    if completed.returncode == 0:
        inspected = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if inspected.returncode == 0:
            image_digest = inspected.stdout.strip().lower()
    ok = completed.returncode == 0 and smoke is not None and smoke.returncode == 0 and image_digest.startswith("sha256:")
    return {
        "ok": ok,
        "image": image,
        "image_digest": image_digest,
        "build_returncode": completed.returncode,
        "smoke_returncode": None if smoke is None else smoke.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "smoke_stdout": "" if smoke is None else smoke.stdout[-4000:],
        "smoke_stderr": "" if smoke is None else smoke.stderr[-4000:],
    }



def _upsert_env_value(path: Path, key: str, value: str) -> None:
    """Atomically update one non-secret runtime value in the private env file."""
    path = path.expanduser().resolve()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rendered = []
    replaced = False
    for line in lines:
        if line.startswith(f"{key}="):
            rendered.append(f"{key}={value}")
            replaced = True
        else:
            rendered.append(line)
    if not replaced:
        rendered.append(f"{key}={value}")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name == "posix":
        path.chmod(0o600)

def command_init(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file).expanduser().resolve()
    if env_path.exists() and not args.force:
        _emit({"ok": False, "error": "env_file_exists", "path": str(env_path)})
        return 2
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(_render_env_template(), encoding="utf-8")
    if os.name == "posix":
        env_path.chmod(0o600)
    load_env_file(env_path, override=True)
    for name in (
        "AMAURA_DATA_DIR",
        "JARVIS_DATA_DIR",
        "AMAURA_EVIDENCE_DIR",
        "AMAURA_BACKUP_DIR",
    ):
        value = os.environ.get(name, "")
        if value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = REPOSITORY_ROOT / path
            path.mkdir(parents=True, exist_ok=True)
    sandbox = _build_sandbox() if args.build_sandbox else {"ok": None, "skipped": True}
    if sandbox.get("ok") and sandbox.get("image_digest"):
        _upsert_env_value(env_path, "AMAURA_SANDBOX_IMAGE_DIGEST", str(sandbox["image_digest"]))
        os.environ["AMAURA_SANDBOX_IMAGE_DIGEST"] = str(sandbox["image_digest"])
    _emit(
        {
            "ok": sandbox.get("ok") is not False,
            "env_file": str(env_path),
            "sandbox": sandbox,
            "next_required_configuration": [
                "Confirm AMAURA_LOCAL_MODEL and AMAURA_LOCAL_REVIEW_MODEL are installed and distinct.",
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_USER_ID together only when Telegram control is enabled.",
                "Set Gmail credentials only when outbound delivery is intentionally enabled.",
                "Run: amaura doctor",
            ],
        }
    )
    return 0 if sandbox.get("ok") is not False else 1


def command_build_sandbox(args: argparse.Namespace) -> int:
    result = _build_sandbox()
    if result.get("ok") and result.get("image_digest"):
        env_path = Path(args.env_file).expanduser().resolve()
        if env_path.exists():
            _upsert_env_value(env_path, "AMAURA_SANDBOX_IMAGE_DIGEST", str(result["image_digest"]))
            result["env_updated"] = str(env_path)
    _emit(result)
    return 0 if result.get("ok") else 1


def _control():
    from jarvis.amaura.control_plane import AmauraControlPlane

    return AmauraControlPlane()


def command_doctor(args: argparse.Namespace) -> int:
    from jarvis.amaura.doctor import certify_release

    report = certify_release(repository_root=REPOSITORY_ROOT, static_only=args.static)
    _emit(report)
    key = "source_certified" if args.static else "production_ready"
    return 0 if report.get(key) else 1


def command_status(args: argparse.Namespace) -> int:
    control = _control()
    try:
        from jarvis.amaura.readiness import production_readiness
        from jarvis.amaura.supervisor import AmauraSupervisor

        supervisor = AmauraSupervisor(
            control,
            lease_seconds=int(os.environ.get("AMAURA_LEASE_SECONDS", "900")),
            max_attempts=int(os.environ.get("AMAURA_MAX_ATTEMPTS", "3")),
            outbox_max_attempts=int(os.environ.get("AMAURA_OUTBOX_MAX_ATTEMPTS", "3")),
            outbox_lease_seconds=int(os.environ.get("AMAURA_OUTBOX_LEASE_SECONDS", "120")),
        )
        _emit(
            {
                "supervisor": supervisor.status(),
                "company": control.dashboard(),
                "readiness": production_readiness(control, live=not args.no_live),
            }
        )
    finally:
        control.close()
    return 0


def command_worker(args: argparse.Namespace) -> int:
    from jarvis.amaura.supervisor import AmauraSupervisor

    control = _control()
    supervisor = AmauraSupervisor(
        control,
        lease_seconds=int(os.environ.get("AMAURA_LEASE_SECONDS", "900")),
        max_attempts=int(os.environ.get("AMAURA_MAX_ATTEMPTS", "3")),
        outbox_max_attempts=int(os.environ.get("AMAURA_OUTBOX_MAX_ATTEMPTS", "3")),
        outbox_lease_seconds=int(os.environ.get("AMAURA_OUTBOX_LEASE_SECONDS", "120")),
        automatic_reviews=not args.no_auto_review,
    )
    try:
        if args.once:
            _emit(supervisor.tick(workflow_id=args.workflow or None))
        elif args.drain:
            _emit(supervisor.drain(workflow_id=args.workflow or None, max_ticks=args.max_ticks))
        else:
            supervisor.run_forever(workflow_id=args.workflow or None, poll_seconds=args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        control.close()
    return 0


def command_backup(args: argparse.Namespace) -> int:
    control = _control()
    try:
        if args.destination:
            destination = Path(args.destination).expanduser().resolve()
        else:
            backup_dir = Path(os.environ["AMAURA_BACKUP_DIR"]).expanduser().resolve()
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination = backup_dir / f"amaura-{timestamp}.db"
        path = control.store.backup(destination)
        _emit(
            {
                "ok": True,
                "backup": str(path),
                "bytes": path.stat().st_size,
                "integrity": control.store.integrity_check(),
            }
        )
    finally:
        control.close()
    return 0


def command_reconcile(args: argparse.Namespace) -> int:
    control = _control()
    try:
        if args.reconcile_action == "list":
            _emit(
                {
                    "events": control.store.list_outbox_events(
                        status="reconciliation_required",
                        limit=args.limit,
                    )
                }
            )
            return 0
        receipt: dict[str, Any] | None = None
        if args.receipt_json:
            receipt = json.loads(Path(args.receipt_json).read_text(encoding="utf-8"))
        event = control.reconcile_outbox_event(
            args.event_id,
            resolution=args.resolution,
            reason=args.reason,
            provider_receipt=receipt,
            actor=control.founder_id,
        )
        _emit({"ok": True, "event": event})
    finally:
        control.close()
    return 0


def command_create_program(args: argparse.Namespace) -> int:
    control = _control()
    try:
        inputs = json.loads(args.inputs_json) if args.inputs_json else {}
        created = control.create_program(
            objective=args.objective,
            success_metric=args.success_metric,
            workflow_key=args.workflow,
            title=args.title or None,
            priority=args.priority,
            deadline=args.deadline or None,
            inputs=inputs,
        )
        _emit(created)
    finally:
        control.close()
    return 0


def command_autopilot(args: argparse.Namespace) -> int:
    from jarvis.amaura.autopilot import AutonomousCompanyRuntime

    control = _control()
    runtime = AutonomousCompanyRuntime(control, automatic_reviews=not args.no_auto_review)
    try:
        if args.once:
            _emit(
                runtime.tick(
                    max_work_units=args.max_work_units,
                    max_new_programmes=args.max_new_programmes,
                    max_signals=args.max_signals,
                )
            )
        else:
            runtime.run_forever(
                poll_seconds=args.poll_seconds,
                max_work_units=args.max_work_units,
                max_new_programmes=args.max_new_programmes,
                max_signals=args.max_signals,
            )
    except KeyboardInterrupt:
        return 0
    finally:
        control.close()
    return 0


def command_mission(args: argparse.Namespace) -> int:
    from jarvis.amaura.mission_control import MissionControl

    control = _control()
    mission = MissionControl(control)
    try:
        if args.mission_action == "list":
            portfolio = mission.portfolio()
            if args.status:
                portfolio["objectives"] = [
                    item for item in portfolio["objectives"] if item["status"] == args.status
                ]
            _emit(portfolio)
        elif args.mission_action == "create":
            _emit(
                mission.create_objective(
                    title=args.title, objective=args.objective, success_metric=args.success_metric,
                    workflow_key=args.workflow, cadence=args.cadence, inputs=json.loads(args.inputs_json),
                    priority=args.priority, target_value=args.target_value, current_value=args.current_value,
                    unit=args.unit, max_active_programmes=args.max_active_programmes,
                    budget_cents=args.budget_cents, deadline=args.deadline or None,
                )
            )
        elif args.mission_action == "progress":
            _emit(
                mission.record_progress(
                    args.objective_id, value=args.value, delta=args.delta, note=args.note,
                    evidence_refs=json.loads(args.evidence_json), actor=control.founder_id,
                )
            )
        elif args.mission_action == "set-status":
            _emit(mission.set_status(args.objective_id, args.status, reason=args.reason))
        elif args.mission_action == "bootstrap-distribution":
            _emit({
                "created": mission.bootstrap_distribution_first(repository_path=args.repository or None),
                "portfolio": mission.portfolio(),
            })
        elif args.mission_action == "autopilot":
            _emit(mission.set_autopilot(args.autopilot_action == "enable", reason=args.reason))
        else:
            raise RuntimeError(f"Unsupported mission action: {args.mission_action}")
    finally:
        control.close()
    return 0


def command_company(args: argparse.Namespace) -> int:
    from jarvis.amaura.autopilot import AutonomousCompanyRuntime
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
    from jarvis.amaura.mission_control import MissionControl

    control = _control()
    company = CompanyAutonomyEngine(control)
    try:
        if args.company_action == "status":
            _emit(company.status())
        elif args.company_action == "bootstrap":
            _emit(
                company.bootstrap_company(
                    repository_path=args.repository,
                    product_name=args.product_name,
                    audience=args.audience,
                    target_user=args.target_user,
                )
            )
        elif args.company_action == "signal":
            _emit(
                company.ingest_signal(
                    signal_type=args.signal_type,
                    source=args.source,
                    severity=args.severity,
                    payload=json.loads(args.payload_json),
                    idempotency_key=args.idempotency_key or None,
                    actor=control.founder_id,
                )
            )
        elif args.company_action == "signals":
            _emit(
                {
                    "signals": control.store.list_company_signals(
                        status=args.status or None,
                        signal_type=args.signal_type or None,
                        limit=args.limit,
                    )
                }
            )
        elif args.company_action == "department":
            _emit(
                company.set_department(
                    args.department,
                    enabled=args.department_state == "enable",
                    reason=args.reason,
                )
            )
        elif args.company_action == "autopilot":
            _emit(
                MissionControl(control).set_autopilot(
                    args.autopilot_state == "enable", reason=args.reason
                )
            )
        elif args.company_action == "run-once":
            runtime = AutonomousCompanyRuntime(
                control, automatic_reviews=not args.no_auto_review
            )
            _emit(
                runtime.tick(
                    max_work_units=args.max_work_units,
                    max_new_programmes=args.max_new_programmes,
                    max_signals=args.max_signals,
                )
            )
        else:
            raise RuntimeError(f"Unsupported company action: {args.company_action}")
    finally:
        control.close()
    return 0


def command_ventures(args: argparse.Namespace) -> int:
    from jarvis.amaura.ventures import VentureStudio

    control = _control()
    studio = VentureStudio(control)
    try:
        if args.ventures_action == "status":
            _emit(studio.dashboard())
        elif args.ventures_action == "opportunity-add":
            _emit(
                studio.create_opportunity(
                    title=args.title,
                    problem=args.problem,
                    target_user=args.target_user,
                    product_type=args.product_type,
                    source=args.source,
                    evidence=json.loads(args.evidence_json),
                    score_components=json.loads(args.score_json),
                    estimated_build_days=args.estimated_build_days,
                    monetization=args.monetization,
                    distribution_channel=args.distribution_channel,
                    strategic_fit=args.strategic_fit,
                    actor=control.founder_id,
                )
            )
        elif args.ventures_action == "opportunities":
            _emit({"opportunities": control.store.list_venture_opportunities(status=args.status or None, limit=args.limit)})
        elif args.ventures_action == "start":
            _emit(
                studio.start_validation(
                    opportunity_id=args.opportunity_id,
                    product_name=args.product_name,
                    hypothesis=args.hypothesis,
                    primary_metric=args.primary_metric,
                    target_value=args.target_value,
                    kill_threshold=args.kill_threshold,
                    budget_cents=args.budget_cents,
                    timebox_days=args.timebox_days,
                )
            )
        elif args.ventures_action == "metric":
            _emit(
                studio.record_metric(
                    args.experiment_id,
                    metric_name=args.metric_name,
                    value=args.value,
                    source=args.source,
                    evidence=json.loads(args.evidence_json),
                    captured_at=args.captured_at or None,
                    actor=control.founder_id,
                )
            )
        elif args.ventures_action == "recommend":
            _emit(studio.recommend(args.experiment_id))
        elif args.ventures_action == "decide":
            _emit(studio.decide(args.experiment_id, decision=args.decision, reason=args.reason))
        elif args.ventures_action == "stage":
            _emit(studio.set_stage(args.experiment_id, stage=args.stage, reason=args.reason))
        else:
            raise RuntimeError(f"Unsupported ventures action: {args.ventures_action}")
    finally:
        control.close()
    return 0


def command_resources(args: argparse.Namespace) -> int:
    from jarvis.amaura.resources import CapabilityRouter

    router = CapabilityRouter()
    _emit({"resources": router.inventory(), "mac_8gb_profile": router.mac_8gb_profile()})
    return 0


def command_company_blueprint(args: argparse.Namespace) -> int:
    from jarvis.amaura.company import company_blueprint

    _emit(company_blueprint())
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    from jarvis.amaura.handoffs import create_antigravity_packet, create_flow_packet

    if args.handoff_provider == "antigravity":
        packet = create_antigravity_packet(
            objective=args.objective,
            repository=args.repository,
            plan=json.loads(args.plan_json),
            acceptance_criteria=json.loads(args.criteria_json),
            allowed_paths=json.loads(args.allowed_paths_json),
        )
    else:
        packet = create_flow_packet(
            objective=args.objective,
            scenes=json.loads(args.scenes_json),
            acceptance_criteria=json.loads(args.criteria_json),
            aspect_ratio=args.aspect_ratio,
        )
    _emit({"ok": True, "handoff": packet.to_dict()})
    return 0


def command_distribution(args: argparse.Namespace) -> int:
    control = _control()
    try:
        distribution = control.distribution
        if args.distribution_action == "list":
            _emit({
                "publications": control.store.list_distribution_publications(
                    status=args.status or None,
                    campaign_id=args.campaign_id or None,
                    limit=args.limit,
                ),
                "dashboard": distribution.dashboard(),
            })
        elif args.distribution_action == "stage":
            _emit(distribution.stage_publication(
                campaign_id=args.campaign_id,
                platform=args.platform,
                title=args.title,
                body=args.body,
                asset_ids=json.loads(args.asset_ids_json),
                visibility=args.visibility,
                scheduled_at=args.scheduled_at or None,
                account_ref=args.account_ref,
                metadata=json.loads(args.metadata_json),
                actor="jarvis",
            ))
        elif args.distribution_action == "decide":
            _emit(control.decide_approval(
                args.approval_id,
                actor=control.founder_id,
                decision=args.decision,
                reason=args.reason,
            ))
        elif args.distribution_action == "dispatch":
            _emit({"publication": distribution.dispatch(args.publication_id)})
        elif args.distribution_action == "metrics":
            _emit(distribution.record_metrics(
                args.publication_id,
                window=args.window,
                metrics=json.loads(args.metrics_json),
                captured_at=args.captured_at or None,
            ))
        elif args.distribution_action == "lessons":
            publication = control.store.get_distribution_publication(args.publication_id)
            _emit({
                "publication": publication,
                "lessons": control.store.list_content_lessons(
                    publication["campaign_id"], limit=args.limit
                ),
            })
        else:
            raise RuntimeError(f"Unknown distribution action: {args.distribution_action}")
    finally:
        control.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the local Amaura internal workforce")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    subparsers = parser.add_subparsers(dest="command", required=True)

    resources = subparsers.add_parser("resources", help="Show free-first capability and availability inventory")
    resources.set_defaults(handler=command_resources)

    blueprint = subparsers.add_parser("company-blueprint", help="Show the complete Amaura company operating blueprint")
    blueprint.set_defaults(handler=command_company_blueprint)

    init = subparsers.add_parser("init", help="Create a secure local environment file")
    init.add_argument("--force", action="store_true")
    init.add_argument("--build-sandbox", action="store_true")
    init.set_defaults(handler=command_init)

    sandbox = subparsers.add_parser("build-sandbox", help="Build the governed Docker execution image")
    sandbox.set_defaults(handler=command_build_sandbox)

    doctor = subparsers.add_parser("doctor", help="Run the release gate")
    doctor.add_argument("--static", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    status = subparsers.add_parser("status", help="Show readiness and workforce state")
    status.add_argument("--no-live", action="store_true")
    status.set_defaults(handler=command_status)

    worker = subparsers.add_parser("worker", help="Run the durable workforce supervisor")
    mode = worker.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--drain", action="store_true")
    worker.add_argument("--workflow", default="")
    worker.add_argument("--poll-seconds", type=float, default=5.0)
    worker.add_argument("--max-ticks", type=int, default=100)
    worker.add_argument("--no-auto-review", action="store_true")
    worker.set_defaults(handler=command_worker)

    autopilot = subparsers.add_parser("autopilot", help="Run the safe autonomous company cadence and governed supervisor")
    autopilot.add_argument("--once", action="store_true")
    autopilot.add_argument("--poll-seconds", type=float, default=30.0)
    autopilot.add_argument("--no-auto-review", action="store_true")
    autopilot.add_argument("--max-work-units", type=int, default=1)
    autopilot.add_argument("--max-new-programmes", type=int, default=None)
    autopilot.add_argument("--max-signals", type=int, default=3)
    autopilot.set_defaults(handler=command_autopilot)

    company = subparsers.add_parser(
        "company", help="Operate the full Amaura company autonomy layer"
    )
    company_sub = company.add_subparsers(dest="company_action", required=True)

    company_status = company_sub.add_parser("status", help="Show company autonomy status")
    company_status.set_defaults(handler=command_company)

    company_bootstrap = company_sub.add_parser(
        "bootstrap", help="Create the full founder-approved company objective portfolio"
    )
    company_bootstrap.add_argument("--repository", required=True)
    company_bootstrap.add_argument("--product-name", default="Amaura Labs")
    company_bootstrap.add_argument(
        "--audience",
        default="AI builders, students, developers, researchers and founders",
    )
    company_bootstrap.add_argument(
        "--target-user",
        default="Indian developers, students, researchers and resource-constrained teams",
    )
    company_bootstrap.set_defaults(handler=command_company)

    company_signal = company_sub.add_parser(
        "signal", help="Ingest a durable product, content, engineering or security signal"
    )
    company_signal.add_argument("--type", dest="signal_type", required=True)
    company_signal.add_argument("--source", required=True)
    company_signal.add_argument(
        "--severity", choices=("low", "medium", "high", "critical"), default="medium"
    )
    company_signal.add_argument("--payload-json", default="{}")
    company_signal.add_argument("--idempotency-key", default="")
    company_signal.set_defaults(handler=command_company)

    company_signals = company_sub.add_parser("signals", help="List company signals")
    company_signals.add_argument("--status", default="")
    company_signals.add_argument("--type", dest="signal_type", default="")
    company_signals.add_argument("--limit", type=int, default=100)
    company_signals.set_defaults(handler=command_company)

    company_department = company_sub.add_parser(
        "department", help="Pause or resume a department autonomy circuit"
    )
    company_department.add_argument("department")
    company_department.add_argument("department_state", choices=("enable", "pause"))
    company_department.add_argument("--reason", required=True)
    company_department.set_defaults(handler=command_company)

    company_autopilot = company_sub.add_parser(
        "autopilot", help="Founder kill switch for the complete company runtime"
    )
    company_autopilot.add_argument("autopilot_state", choices=("enable", "pause"))
    company_autopilot.add_argument("--reason", required=True)
    company_autopilot.set_defaults(handler=command_company)

    company_run = company_sub.add_parser(
        "run-once", help="Run one complete company autonomy cycle"
    )
    company_run.add_argument("--max-work-units", type=int, default=4)
    company_run.add_argument("--max-new-programmes", type=int, default=3)
    company_run.add_argument("--max-signals", type=int, default=3)
    company_run.add_argument("--no-auto-review", action="store_true")
    company_run.set_defaults(handler=command_company)

    mission = subparsers.add_parser("mission", help="Manage persistent founder objectives and objective-driven autopilot")
    mission_sub = mission.add_subparsers(dest="mission_action", required=True)

    mission_list = mission_sub.add_parser("list", help="Show objective portfolio")
    mission_list.add_argument("--status", choices=("active", "paused", "completed", "cancelled"), default="")
    mission_list.set_defaults(handler=command_mission)

    mission_create = mission_sub.add_parser("create", help="Create a founder-approved recurring objective")
    mission_create.add_argument("--title", required=True)
    mission_create.add_argument("--objective", required=True)
    mission_create.add_argument("--success-metric", required=True)
    mission_create.add_argument("--workflow", required=True)
    mission_create.add_argument("--cadence", choices=("daily", "weekly", "monthly", "manual"), default="weekly")
    mission_create.add_argument("--inputs-json", default="{}")
    mission_create.add_argument("--priority", type=int, default=3)
    mission_create.add_argument("--target-value", type=float, default=None)
    mission_create.add_argument("--current-value", type=float, default=0.0)
    mission_create.add_argument("--unit", default="")
    mission_create.add_argument("--max-active-programmes", type=int, default=1)
    mission_create.add_argument("--budget-cents", type=int, default=0)
    mission_create.add_argument("--deadline", default="")
    mission_create.set_defaults(handler=command_mission)

    mission_progress = mission_sub.add_parser("progress", help="Record evidenced objective progress")
    mission_progress.add_argument("objective_id")
    progress_value = mission_progress.add_mutually_exclusive_group(required=True)
    progress_value.add_argument("--value", type=float)
    progress_value.add_argument("--delta", type=float)
    mission_progress.add_argument("--note", required=True)
    mission_progress.add_argument("--evidence-json", required=True, help="JSON array of evidence references")
    mission_progress.set_defaults(handler=command_mission)

    mission_status = mission_sub.add_parser("set-status", help="Pause, resume, complete, or cancel an objective")
    mission_status.add_argument("objective_id")
    mission_status.add_argument("--status", choices=("active", "paused", "completed", "cancelled"), required=True)
    mission_status.add_argument("--reason", required=True)
    mission_status.set_defaults(handler=command_mission)

    mission_bootstrap = mission_sub.add_parser("bootstrap-distribution", help="Create the distribution-first Amaura objective portfolio")
    mission_bootstrap.add_argument("--repository", default="")
    mission_bootstrap.set_defaults(handler=command_mission)

    mission_autopilot = mission_sub.add_parser("autopilot", help="Enable or pause company autopilot")
    mission_autopilot.add_argument("autopilot_action", choices=("enable", "pause"))
    mission_autopilot.add_argument("--reason", required=True)
    mission_autopilot.set_defaults(handler=command_mission)

    ventures = subparsers.add_parser("ventures", help="Operate the separate Amaura Ventures startup studio")
    ventures_sub = ventures.add_subparsers(dest="ventures_action", required=True)

    ventures_status = ventures_sub.add_parser("status", help="Show venture portfolio, constraints and active experiments")
    ventures_status.set_defaults(handler=command_ventures)

    ventures_add = ventures_sub.add_parser("opportunity-add", help="Register and deterministically score an evidenced product opportunity")
    ventures_add.add_argument("--title", required=True)
    ventures_add.add_argument("--problem", required=True)
    ventures_add.add_argument("--target-user", required=True)
    ventures_add.add_argument("--product-type", required=True)
    ventures_add.add_argument("--source", required=True)
    ventures_add.add_argument("--evidence-json", required=True)
    ventures_add.add_argument("--score-json", required=True)
    ventures_add.add_argument("--estimated-build-days", type=int, default=14)
    ventures_add.add_argument("--monetization", required=True)
    ventures_add.add_argument("--distribution-channel", required=True)
    ventures_add.add_argument("--strategic-fit", default="")
    ventures_add.set_defaults(handler=command_ventures)

    ventures_list = ventures_sub.add_parser("opportunities", help="List scored venture opportunities")
    ventures_list.add_argument("--status", default="")
    ventures_list.add_argument("--limit", type=int, default=100)
    ventures_list.set_defaults(handler=command_ventures)

    ventures_start = ventures_sub.add_parser("start", help="Founder-start a time-boxed validation sprint")
    ventures_start.add_argument("opportunity_id")
    ventures_start.add_argument("--product-name", required=True)
    ventures_start.add_argument("--hypothesis", required=True)
    ventures_start.add_argument("--primary-metric", required=True)
    ventures_start.add_argument("--target-value", type=float, required=True)
    ventures_start.add_argument("--kill-threshold", type=float, required=True)
    ventures_start.add_argument("--budget-cents", type=int, default=0)
    ventures_start.add_argument("--timebox-days", type=int, default=14)
    ventures_start.set_defaults(handler=command_ventures)

    ventures_metric = ventures_sub.add_parser("metric", help="Record an evidenced primary-metric observation")
    ventures_metric.add_argument("experiment_id")
    ventures_metric.add_argument("--metric-name", required=True)
    ventures_metric.add_argument("--value", type=float, required=True)
    ventures_metric.add_argument("--source", required=True)
    ventures_metric.add_argument("--evidence-json", required=True)
    ventures_metric.add_argument("--captured-at", default="")
    ventures_metric.set_defaults(handler=command_ventures)

    ventures_recommend = ventures_sub.add_parser("recommend", help="Calculate a threshold-based venture recommendation")
    ventures_recommend.add_argument("experiment_id")
    ventures_recommend.set_defaults(handler=command_ventures)

    ventures_decide = ventures_sub.add_parser("decide", help="Founder kill, iterate, pause or double down decision")
    ventures_decide.add_argument("experiment_id")
    ventures_decide.add_argument("--decision", choices=("kill", "iterate", "double_down", "pause"), required=True)
    ventures_decide.add_argument("--reason", required=True)
    ventures_decide.set_defaults(handler=command_ventures)

    ventures_stage = ventures_sub.add_parser("stage", help="Founder-controlled experiment stage transition")
    ventures_stage.add_argument("experiment_id")
    ventures_stage.add_argument("--stage", required=True)
    ventures_stage.add_argument("--reason", required=True)
    ventures_stage.set_defaults(handler=command_ventures)

    backup = subparsers.add_parser("backup", help="Create a transactionally consistent database backup")
    backup.add_argument("destination", nargs="?", default="")
    backup.set_defaults(handler=command_backup)

    reconcile = subparsers.add_parser("reconcile", help="Resolve ambiguous provider operations")
    reconcile_sub = reconcile.add_subparsers(dest="reconcile_action", required=True)
    reconcile_list = reconcile_sub.add_parser("list")
    reconcile_list.add_argument("--limit", type=int, default=100)
    reconcile_list.set_defaults(handler=command_reconcile)
    reconcile_resolve = reconcile_sub.add_parser("resolve")
    reconcile_resolve.add_argument("event_id")
    reconcile_resolve.add_argument("--resolution", choices=("completed", "failed", "requeue"), required=True)
    reconcile_resolve.add_argument("--receipt-json", default="")
    reconcile_resolve.add_argument("--reason", required=True)
    reconcile_resolve.set_defaults(handler=command_reconcile)

    create = subparsers.add_parser("create-program", help="Create a governed company programme")
    create.add_argument("--workflow", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--success-metric", required=True)
    create.add_argument("--title", default="")
    create.add_argument("--priority", type=int, default=3)
    create.add_argument("--deadline", default="")
    create.add_argument("--inputs-json", default="{}")
    create.set_defaults(handler=command_create_program)

    distribution = subparsers.add_parser(
        "distribution",
        help="Stage, approve, dispatch, and learn from immutable content publications",
    )
    distribution_sub = distribution.add_subparsers(dest="distribution_action", required=True)

    distribution_list = distribution_sub.add_parser("list", help="Show publication queue and status")
    distribution_list.add_argument("--status", default="")
    distribution_list.add_argument("--campaign-id", default="")
    distribution_list.add_argument("--limit", type=int, default=100)
    distribution_list.set_defaults(handler=command_distribution)

    distribution_stage = distribution_sub.add_parser("stage", help="Create an immutable publication package")
    distribution_stage.add_argument("--campaign-id", required=True)
    distribution_stage.add_argument("--platform", required=True)
    distribution_stage.add_argument("--title", required=True)
    distribution_stage.add_argument("--body", required=True)
    distribution_stage.add_argument("--asset-ids-json", required=True, help="JSON array of approved content asset IDs")
    distribution_stage.add_argument("--visibility", choices=("private", "draft", "public"), default="public")
    distribution_stage.add_argument("--scheduled-at", default="", help="Timezone-aware ISO-8601 timestamp")
    distribution_stage.add_argument("--account-ref", default="")
    distribution_stage.add_argument("--metadata-json", default="{}")
    distribution_stage.set_defaults(handler=command_distribution)

    distribution_decide = distribution_sub.add_parser("decide", help="Founder decision for an exact publication package")
    distribution_decide.add_argument("approval_id")
    distribution_decide.add_argument(
        "--decision",
        choices=("approved", "rejected", "changes_requested", "postponed"),
        required=True,
    )
    distribution_decide.add_argument("--reason", required=True)
    distribution_decide.set_defaults(handler=command_distribution)

    distribution_dispatch = distribution_sub.add_parser("dispatch", help="Enqueue an approved due publication")
    distribution_dispatch.add_argument("publication_id")
    distribution_dispatch.set_defaults(handler=command_distribution)

    distribution_metrics = distribution_sub.add_parser("metrics", help="Record a measured performance window")
    distribution_metrics.add_argument("publication_id")
    distribution_metrics.add_argument("--window", choices=("24h", "72h", "7d", "30d"), required=True)
    distribution_metrics.add_argument("--metrics-json", required=True)
    distribution_metrics.add_argument("--captured-at", default="")
    distribution_metrics.set_defaults(handler=command_distribution)

    distribution_lessons = distribution_sub.add_parser("lessons", help="Show evidence-backed campaign lessons")
    distribution_lessons.add_argument("publication_id")
    distribution_lessons.add_argument("--limit", type=int, default=100)
    distribution_lessons.set_defaults(handler=command_distribution)

    handoff = subparsers.add_parser("handoff", help="Create a founder-controlled external execution packet")
    handoff_sub = handoff.add_subparsers(dest="handoff_provider", required=True)
    antigravity = handoff_sub.add_parser("antigravity")
    antigravity.add_argument("--objective", required=True)
    antigravity.add_argument("--repository", required=True)
    antigravity.add_argument("--plan-json", required=True, help="JSON array of engineering instructions")
    antigravity.add_argument("--criteria-json", required=True, help="JSON array of acceptance criteria")
    antigravity.add_argument("--allowed-paths-json", default='["."]')
    antigravity.set_defaults(handler=command_handoff)
    flow = handoff_sub.add_parser("flow")
    flow.add_argument("--objective", required=True)
    flow.add_argument("--scenes-json", required=True, help="JSON array of scene objects")
    flow.add_argument("--criteria-json", required=True, help="JSON array of acceptance criteria")
    flow.add_argument("--aspect-ratio", default="16:9")
    flow.set_defaults(handler=command_handoff)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        requires_env = args.command not in {"init", "resources", "company-blueprint"} and not (
            args.command == "doctor" and bool(getattr(args, "static", False))
        )
        if requires_env:
            loaded = load_amaura_env(
                args.env_file,
                require_private_permissions=True,
            )
            if loaded is None:
                raise RuntimeError("Amaura is not initialised. Run: amaura init")
        return int(args.handler(args))
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        _emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 1
    except Exception as exc:  # fail closed with machine-readable operator output
        _emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
