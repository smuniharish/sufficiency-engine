# Validate a deployment

The test suite and the bundled checks verify the library. They do not configure
your services or certify a particular model, database, or deployment. Work
through this checklist with your actual stores, model, and topology before
going to production.

## Security and data

- [ ] Authorize every application, tenant, session, and source reference before
  calling the engine, and test that cross-scope access is rejected.
- [ ] Configure TLS, encryption at rest, secrets handling, least-privilege
  access, and retention for sessions, checkpoints, and both AGXAI stores.
- [ ] Delete sessions, checkpoints, and AGXAI runs together.
- [ ] Confirm that traces and logs carry no task or answer text through your
  exporters and collectors.

## Recovery

- [ ] Restore backups into an isolated environment.
- [ ] Crash the process before and after each state and audit write, including
  an acknowledged write whose response was lost, and resume.
- [ ] Simulate an AGXAI store or archive outage and confirm that the
  assessment fails closed and recovers on resume.
- [ ] Test duplicate submissions, concurrent writers, lease expiry, and
  checkpoint ownership in your deployment topology.

## Capacity

- [ ] Set throughput, concurrency, latency, memory, callback, and storage
  deadlines for your workload, and enforce request quotas outside the engine.
- [ ] Measure sustained load and overload behavior. The
  [benchmarks](../../benchmarks.md) exclude model, network, and storage time.

## Quality

- [ ] [Evaluate your discovery model](evaluate-discovery.md) on representative
  labeled cases, and review every false-ready outcome.
- [ ] Keep durable audit separate from telemetry. Do not treat traces or the
  in-memory defaults as provenance.

## Release

- [ ] Install the built wheel in a clean environment and import it.
- [ ] Review the CI results for the exact commit you deploy.
