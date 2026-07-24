# ADR 0003: Use Hyak for research model compute

Status: accepted for the current research phase

## Context

The user currently wants the Mac to be the front end and lightweight project
machine, with Hyak providing the large-model compute. Early Mac/MPS
compatibility probes did not produce a successful baseline and are not a
reason to spend more local compute time.

## Decision

Run model inference, separation, sweeps, and training through Slurm on Hyak.
Use the Mac for code, orchestration, file transfer, schema validation,
annotation, and result rendering. Record the GPU model actually allocated
rather than assuming a specific Hyak accelerator.

This is a research-phase execution boundary. It does not overturn the
long-term goal in D-007 that the final Mac product remain useful without a live
Hyak connection.

## Consequences

- Task gates do not require a successful Mac model run while this decision is
  active;
- no heavy model process may run on the Mac or a Hyak login node;
- private results must be synced back to the Mac for inspection;
- a local inference fallback requires an explicit future decision based on
  measured compatibility, quality, and resource use.
