from __future__ import annotations

import time

from ..cluster import CommandError, require_any_command, run_command
from ..models import ResolvedRunPlan, ValidationError
from ..renderers.deployment import dynamo_dgd_name
from ..ui import step, success


def _ensure_supported_mode(plan: ResolvedRunPlan) -> None:
    if plan.deployment.mode != "aggregate":
        raise ValidationError(
            f"unsupported Dynamo deployment mode: {plan.deployment.mode}"
        )


def cleanup_dynamo(
    plan: ResolvedRunPlan,
    *,
    wait_for_deletion: bool = True,
    timeout_seconds: int = 300,
    skip_if_not_exists: bool = True,
) -> None:
    _ensure_supported_mode(plan)

    kubectl_cmd = require_any_command("oc", "kubectl")
    namespace = plan.deployment.namespace
    dgd_name = dynamo_dgd_name(plan)

    exists = run_command(
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
    if exists.returncode != 0:
        if skip_if_not_exists:
            return
        raise CommandError(
            f"DynamoGraphDeployment {dgd_name} not found in namespace {namespace}"
        )

    step(f"Deleting DynamoGraphDeployment {dgd_name} in namespace {namespace}")
    run_command(
        [
            kubectl_cmd,
            "delete",
            "dynamographdeployment",
            dgd_name,
            "-n",
            namespace,
        ]
    )
    success(f"Deleted DynamoGraphDeployment {dgd_name}")

    if not wait_for_deletion:
        return

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        current = run_command(
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
        if current.returncode != 0:
            return
        time.sleep(5)

    raise CommandError(
        f"timed out waiting for DynamoGraphDeployment deletion: {dgd_name}"
    )
