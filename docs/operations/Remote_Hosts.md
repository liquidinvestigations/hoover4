# Verify an authorized remote deployment.

Keep target names, addresses, paths, credentials, and access details in the gitignored `INFRASTRUCTURE_INVENTORY.md`.
Read that inventory before selecting a target.
[The remote-host skill](../../.agents/skills/operating-remote-hosts/SKILL.md) describes the operating procedure.

## Preserve the authorized scope.

Verify which target and operations the user authorized.
Read-only inspection does not authorize a deployment, reset, or unrelated configuration change.
Preserve authorization already given for the same target and scope.
Keep reviewed source changes in the repository and deliver them through the deployment procedure.
Record target-specific changes in the private inventory.

## Verify the actual environment.

Inspect the container runtime, architecture, mounts, active workflows, and available resources.
Verify the deployed revision and the source each service loads.
Inspect the generated service configuration without printing credentials.
Verify fixture paths before running ingestion or browser procedures.
Test service reachability from the consuming container.

## Preserve shared services and stored data.

Scope container operations to the authorized project and services.
An unscoped prune can remove another application's resources.
Use the worker restart procedure when a restart requires draining active work.
A reset requires explicit authorization for its target and stored data.
[The recovery procedure](Backup_And_Restore.md) describes collection export and restore prerequisites.

## Verify results on the target.

Compilation on one architecture does not establish execution on another.
A local Compose parse does not establish that another runtime accepts the configuration.
Local fixture paths and build duration do not establish remote paths or duration.
Use the relevant target checks and retain their complete output locally.
[The verification guide](../quality-assurance/Running_Checks.md) identifies checks by claim.
