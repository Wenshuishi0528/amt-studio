# ADR 0001: Isolate model workers

Status: accepted

## Context

Candidate AMT, separation, and beat models use incompatible Python, PyTorch, TensorFlow/CoreML, CUDA, and package versions. A single environment would be fragile and would make Mac/Hyak parity difficult.

## Decision

Each third-party model runs in a separately managed environment and communicates through request/result files. The root package owns schemas and orchestration but does not import worker packages.

## Consequences

Advantages:

- dependency conflicts are contained;
- workers can use different Python versions;
- model replacement does not change project format;
- local and Slurm execution share the same contract;
- failures are auditable.

Costs:

- subprocess overhead;
- explicit conversion adapters;
- multiple environments to maintain.

The quality and reproducibility benefits justify these costs.
