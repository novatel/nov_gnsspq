# Test recordings

`sample.GPS` is a short NovAtel binary recording committed to this repository.
It drives the integration tests under `test/integration/`, so a clean checkout
runs the whole suite with no extra setup:

```bash
poetry install --with test --all-extras
poetry run pytest test/ --import-mode importlib
```

## Running against a longer recording

One assertion is skipped by default: `ParallelGPSWriter` delegates to the
single-threaded writer for inputs below 50 MB, so the `parallel_workers`
metadata field is only emitted for larger files. To exercise the parallel path,
point `NOV_GNSSPQ_TEST_GPS` at a bigger capture:

```bash
NOV_GNSSPQ_TEST_GPS=/path/to/large.GPS \
  poetry run pytest test/integration/ --import-mode importlib
```

Any NovAtel binary log works. Recordings containing `BESTPOS` and `RANGE`
exercise the root index and the nested-subtable path; `RAWIMUS` / `RAWIMUSX`
additionally exercise the IMU plots.

Large local captures are not committed — `.gitignore` keeps
`test/resources/TEST_FILE_ONE.GPS` out of the repository.
