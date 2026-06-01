from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from ..cluster import CommandError, require_any_command, run_command, run_json_command
from ..models import ResolvedRunPlan, ValidationError
from ..renderers.deployment import dynamo_dgd_name, render_dynamo_dgd_manifest
from ..ui import detail, step, success


def _ensure_supported_mode(plan: ResolvedRunPlan) -> None:
    if plan.deployment.mode != "aggregate":
        raise ValidationError(
            f"unsupported Dynamo deployment mode: {plan.deployment.mode}"
        )


def _dgd_exists(namespace: str, dgd_name: str, kubectl_cmd: str) -> bool:
    result = run_command(
        [
            kubectl_cmd,
            "get",
            "dynamographdeployment",
            dgd_name,
            "-n",
            namespace,
            "-o",
            "name",
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _ready_condition(payload: dict[str, Any]) -> tuple[bool, str]:
    conditions = (payload.get("status") or {}).get("conditions") or []
    for cond in conditions:
        if cond.get("type") == "Ready":
            status = str(cond.get("status", "")).strip()
            reason = str(cond.get("reason", "")).strip() or str(
                cond.get("message", "")
            ).strip()
            return status == "True", reason
    return False, "no Ready condition yet"


def _verify_dgd(
    namespace: str,
    dgd_name: str,
    kubectl_cmd: str,
    timeout_seconds: int,
) -> None:
    step(
        f"Waiting for DynamoGraphDeployment {dgd_name} in namespace {namespace} to become ready"
    )
    deadline = time.time() + timeout_seconds
    last_reason = ""
    while time.time() < deadline:
        try:
            payload = run_json_command(
                [
                    kubectl_cmd,
                    "get",
                    "dynamographdeployment",
                    dgd_name,
                    "-n",
                    namespace,
                    "-o",
                    "json",
                ]
            )
        except CommandError:
            time.sleep(10)
            continue

        ready, reason = _ready_condition(payload)
        if ready:
            success(f"DynamoGraphDeployment {dgd_name} is ready")
            return
        if reason != last_reason:
            detail(f"DGD not ready: {reason}")
            last_reason = reason
        time.sleep(10)

    raise CommandError(
        f"timed out waiting for DynamoGraphDeployment {dgd_name} to become ready "
        f"(last status: {last_reason})"
    )


def deploy_dynamo(
    plan: ResolvedRunPlan,
    *,
    manifests_dir: Path | None = None,
    skip_if_exists: bool = True,
    verify: bool = True,
    verify_timeout_seconds: int = 1800,
) -> Path:
    _ensure_supported_mode(plan)

    kubectl_cmd = require_any_command("oc", "kubectl")
    namespace = plan.deployment.namespace
    dgd_name = dynamo_dgd_name(plan)
    manifest = render_dynamo_dgd_manifest(plan)

    if skip_if_exists and _dgd_exists(namespace, dgd_name, kubectl_cmd):
        success(
            f"Skipping deploy; DynamoGraphDeployment {dgd_name} already exists"
        )
        return manifests_dir.resolve() if manifests_dir else Path.cwd()

    if manifests_dir is not None:
        manifests_dir.mkdir(parents=True, exist_ok=True)
        target = manifests_dir / "dynamographdeployment.yaml"
        target.write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
        detail(f"Rendered DGD manifest written to {target}")

    step(
        f"Applying DynamoGraphDeployment {dgd_name} in namespace {namespace}"
    )
    run_command(
        [kubectl_cmd, "apply", "-f", "-"],
        input_text=yaml.safe_dump(manifest, sort_keys=False),
    )
    success(f"Applied DynamoGraphDeployment {dgd_name} in namespace {namespace}")

    if verify:
        try:
            _verify_dgd(namespace, dgd_name, kubectl_cmd, verify_timeout_seconds)
        except CommandError as exc:
            raise CommandError(
                f"failed to verify DynamoGraphDeployment {dgd_name}: {exc}"
            ) from exc

    return manifests_dir.resolve() if manifests_dir else Path.cwd()
