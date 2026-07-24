# Private data

Place authorized private audio under `data/private/inbox/`. Everything in this directory except this README is ignored by Git.

Recommended command:

```bash
mkdir -p data/private/inbox
chmod 700 data/private data/private/inbox
cp "/path/to/song.mp3" data/private/inbox/
```

Do not place authorization correspondence in the repository. Record only the private archive location and cryptographic hashes in `docs/AUTHORIZATION_AND_PROVENANCE.md`.
