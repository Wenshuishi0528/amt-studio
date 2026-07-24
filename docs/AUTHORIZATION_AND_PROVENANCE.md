# Authorization and provenance register

The project owner states that the current work is private academic use and that relevant authors have granted permission. This file does not replace the actual correspondence. Keep copies of authorization messages outside Git and record a cryptographic hash or private archive location here.

For each asset, complete one record before use in training, evaluation, publication, or redistribution.

## Record template

```yaml
asset_id: unique-name
asset_type: audio | midi | score | dataset | code | model_weights | soundfont
owner_or_author:
source:
version_or_commit:
obtained_on:
intended_use: private academic research
permission_basis: license | written authorization | owned by project user
permission_scope:
  training: unknown
  evaluation: unknown
  derivative_weights: unknown
  publication_of_metrics: unknown
  publication_of_examples: unknown
  redistribution: unknown
  commercial_use: unknown
restrictions:
correspondence_archive:
correspondence_sha256:
asset_sha256:
notes:
```

## Current private reference song

```yaml
asset_id: glass-kiss-reference-audio
asset_type: audio
owner_or_author: TO BE RECORDED BY PROJECT OWNER
source: private local file
obtained_on: TO BE RECORDED
intended_use: private academic research and personal evaluation
permission_basis: written authorization reported by project owner
permission_scope:
  training: TO BE RECORDED
  evaluation: TO BE RECORDED
  derivative_weights: TO BE RECORDED
  publication_of_metrics: TO BE RECORDED
  publication_of_examples: TO BE RECORDED
  redistribution: false unless separately documented
  commercial_use: false for current project scope
correspondence_archive: private location, not committed
correspondence_sha256: TO BE RECORDED
asset_sha256: 3464cdb850fdb1796c2cc48e0580640f04c39062eb236143e1ff0f2bdc0d1dbe
notes: Do not commit or redistribute the audio.
```

## Model and dataset caution

Permission from a song author does not automatically grant rights to third-party model weights, code, datasets, soundfonts, or recordings. Record each layer separately. Keep model identifiers and license status in `configs/model_registry.yaml`.
