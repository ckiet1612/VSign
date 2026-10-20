# Phase 3 Execution Plan

Approved design: ../specs/2026-10-15-model-registry-deployment.md

- [x] Freeze the shared API contract; write failing registry/runtime tests.
- [x] Add migration, artifact verification, gate policy, RBAC and audited API.
- [x] Add the opted-in deployment worker and dynamic active-backend integration.
- [x] In parallel, implement the models UI with focused contract/race tests;
   protect training outputs and publish candidate-only manifests.
- [x] Integrate App and deployment activity labels, preserving Dev/Test selection.
- [x] Run targeted and regression tests, lint/build, isolated browser lifecycle
   checks, and a separate read-only review. Fix actionable findings.
- [x] Back up/migrate local DB and enable worker only for 8002; verify original
   model identities and artifact hashes. Do not deploy a real candidate.
- [x] Document local auth, configuration, report schema and verification limits.

Evidence: ../../reports/2026-10-15-model-registry-deployment.md.

No commits, branches, worktrees, dataset edits or training runs are included.
