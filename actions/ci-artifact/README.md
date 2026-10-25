# Private CI artifact transport — review candidate

The client sends a short-lived GitHub OIDC token to an R2 Worker. No Cloudflare
key or reusable write credential is installed in a repository or PR runner.
The broker validates the GitHub signature, issuer, audience, time, numeric
repository identity, workflow path, event/ref, run and attempt. Its default
allowlist is empty and its public routes are disabled. Deploying it, enabling a
route and installing its explicit workflow/slot policy require approval.
Policies may additionally require signed PR base branches and an exact
`job_workflow_ref` commit for a reusable workflow. These restrictions do not
authorize a new repository or workflow by themselves.

Each approved job/artifact slot has only `payload.zip`, `manifest.json` and
`complete.json`, created with R2's conditional put. Writers may only write
within their own signed run/attempt, including for untrusted PR code. There is
no list/delete/cross-run route. There is no claim of isolation among jobs in
the *same* run: GitHub's OIDC token does not identify an individual matrix job.
Instead, unique fixed slots, first-write immutability and mandatory producer
success make cross-job squatting fail the run. All consumers must depend on
the successful expected producer and validate its expected source SHA. Where
available also pass the producer's `manifest_sha256` output.

Each consumer requires the completion marker, full manifest identity, payload
size/hash, exact filename set, and per-file sizes/SHA256. It fails on missing,
unexpected, duplicate or unsafe paths, symlinks, mismatched attempts and
destination collisions. A consumer must enumerate expected artifacts from a
frozen plan; remote wildcard discovery cannot establish completeness. ZIP
files are deterministic so retry of identical bytes is idempotent; different
bytes in an existing slot fail. Full workflow reruns use a new attempt. A
partial rerun whose prerequisites only exist under the previous attempt fails
and must be replaced by a full rerun, never a cross-attempt fallback.

The per-bundle limit is 90 MiB compressed / 1 GiB expanded. Larger artifacts
must be split into explicit independently verified slots or add a separately
reviewed multipart design; they do not silently fall back to GitHub. Retention
is recorded in manifests only. No lifecycle deletion has been configured;
operational retention and protection exemptions need approval before rollout.

Validation from the repository root:
`python3 -B -m unittest discover -s actions/ci-artifact -p 'test_*.py'`
and `node --test actions/ci-artifact/worker.test.mjs`.

Transport implementation alone does not establish completed CI migration.
Each caller needs an approved broker policy, successful producer/consumer
verification for its final candidate, missing/integrity/rerun/permission-boundary
checks and application to its intended branch. Preserve existing deployment
triggers; migration branches do not receive special deployment exclusions.
Account monthly request usage and billing must be assessed separately from
transport correctness; a free-tier estimate is not a confirmed zero-cost bill.
