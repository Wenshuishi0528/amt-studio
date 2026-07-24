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

The adapter contract will be finalized in Task 002 and Task 005. Until then, preserve each model's native outputs and record exact commands.
