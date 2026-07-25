# Task 007 Vocadito split

`vocadito_v3_split.json` fixes two singer-disjoint six-track sets before any
Task 007 candidate inference:

- development: tracks `2, 4, 10, 13, 15, 25`;
- blind test: tracks `5, 7, 11, 18, 27, 34`.

Both sets are disjoint from the Task 006 blind singers
`S1, S5, S11, S19, S28, S29`. The preparation script verifies the committed
track-to-singer, language, and average-pitch metadata against
`vocadito_metadata.csv`; it does not infer a split from file ordering.

`fusion_source_metadata.json` and `fusion_base_config.json` freeze the
non-reference source features, clustering tolerances, scoring weights, and
initial threshold before development scoring. The calibration command may
measure worker reliability and select the final raw-score threshold only from
the development split.

Run preparation and candidate inference only through Slurm:

```bash
sbatch --export=ALL,AMT_REPO_ROOT=/absolute/repo,VOCADITO_EXTRACTED_ROOT=/absolute/extracted,TASK007_DATA_ROOT=/absolute/task007-data,TASK007_PROJECTS_ROOT=/absolute/private-projects slurm/25_task007_vocadito_prepare.slurm

sbatch --export=ALL,AMT_REPO_ROOT=/absolute/repo,TASK007_DATA_ROOT=/absolute/task007-data,TASK007_PROJECTS_ROOT=/absolute/private-projects,SEPARATOR_MODEL_DIR=/absolute/separator-weights,GAME_MODEL_PROVENANCE=/absolute/game-provenance.json,MUSCRIPTOR_WEIGHT_PROVENANCE=/absolute/muscriptor-provenance.json slurm/26_task007_vocadito_candidates.slurm
```

The candidate job freezes the blind candidate set immediately after the four
declared candidate routes finish. It does not inspect or score blind output.

After candidate inference succeeds, submit `27_task007_fusion_calibrate.slurm`,
then `28_task007_blind_fusion_and_seal.slurm`, then
`29_task007_fusion_evaluate.slurm` with `afterok` dependencies. The blind fusion
and its pre-scoring seal are deliberately created in one batch job; the
evaluation job cannot start unless that seal exists and hash-verifies.
