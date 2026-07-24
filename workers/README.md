# Isolated model workers

Each worker owns its Python version, dependencies, model cache, install verification, and adapter. The root package never imports these dependencies.

Expected layout after installation:

```text
workers/<name>/
├── README.md
├── install_mac.sh or install_hyak.sh
├── adapter.py
└── .venv/                 ignored
```

Task 005 finalized `amt-worker-request/v1` and `amt-worker-result/v1`. New
workers use those versioned contracts; immutable earlier runs are loaded through
the same common interface. Every worker still preserves native outputs and
records exact commands, pins, source hashes, and result hashes.
