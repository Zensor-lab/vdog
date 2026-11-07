# vdog documentation

This is the implementation baseline prepared on 2026-11-07. The repository is
currently a documentation and agent-configuration starter: no camera firmware,
mobile application, backend, PCB, or application checks have been implemented.

## Reading order

1. [Product requirements](specs/product.md): purpose, scope, requirement IDs,
   confirmed decisions versus engineering proposals.
2. [Architecture](architecture.md) and [decision register](decisions.md): system
   boundaries, dependencies, unresolved gates, and change rules.
3. [Hardware](specs/hardware.md) and [firmware](specs/firmware.md).
4. [Media format](specs/media-format.md) and [interfaces](specs/interfaces.md):
   authoritative contracts shared by all three software components.
5. [Flutter frontend](specs/frontend.md) and [Rust backend](specs/backend.md).
6. [Implementation plan](plans/implementation-plan.md): ordered stages and
   numbered work packages, including inputs, outputs, tests, and handoffs.
7. [Validation](validation.md), [security](security.md), and
   [references](references.md).

## How to use the baseline

Product requirements describe desired behavior, not demonstrated capabilities.
All unmeasured hardware, price, throughput, retention, runtime, and stabilization
claims remain unverified. A proposal gives the coding agent a starting design;
it does not turn an assistant's suggestion into a user-approved requirement.
Resolve the applicable gate before implementing dependent work.

The media and interface specifications own field names and wire behavior. Other
documents explain their implementation. Resolve conflicts in those contracts
first, then update consumers and fixtures together. Do not copy a contract into
each application and allow independent drift.

Read one work package and its linked contracts at a time. The implementation plan
defines a context packet so execution does not depend on retaining this entire
documentation set, a long chat, or a 256k-token context window.

Operational agent instructions remain in [AGENTS.md](../AGENTS.md). The shared
project facts are in [project profile](project-profile.md); `.agent/PROJECT.md`
is an ignored local working copy in this starter.
