# skillcell Enterprise Edition — Commercial License

Copyright (c) 2026 the skillcell authors. All rights reserved.

The contents of this `ee/` directory (the "Enterprise Edition") are
**source-available, not open source.** They are licensed separately from the
open-core project, which is Apache-2.0 (see the repository root `LICENSE`).

## Grant

No license is granted by default. Use, copying, modification, or distribution
of the Enterprise Edition requires a valid commercial agreement with the
copyright holders. Absent such an agreement, you may **view** the source in
this directory for evaluation only; you may not run it in production, offer it
as a service, or redistribute it.

## Scope of the Enterprise Edition

Reserved for capabilities beyond a single operator's needs:

- Multi-tenant fleet orchestration and quota/scheduling controls.
- Hosted adapter registry (managed LoRA training, storage, and promotion).
- Policy and audit packs (compliance reporting, run attestation, RBAC).

## Boundary rule

Anything required to run **one machine's cells** — the manifest spec,
provisioners, loop runner, reconciler, local and container runtimes — lives
outside `ee/` and remains Apache-2.0. The Enterprise Edition only adds
scale-out, hosting, and governance on top.

## Contact

To obtain a commercial license, open an issue titled `ee-license` or contact
the maintainers listed in the repository metadata.
