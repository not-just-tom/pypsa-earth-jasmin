<!-- Copilot / AI agent instructions for contributors working on PyPSA-Earth -->
# Quick orientation

This repository implements PyPSA-Earth, a PyPSA-based global sector-coupled energy system modelling workflow. Key workflows are orchestrated with Snakemake (`Snakefile`) and the computational models are built on PyPSA networks stored as NetCDF files in `saved/`.

## Important places to look (fast)
- `envs/environment.yaml` — canonical conda environment for development.
- `Snakefile` and the `benchmarks/` subfolders — primary workflow targets and pipeline stages.
- `config*.yaml` (e.g. `config.tutorial.yaml`, `config.yaml`) — runtime configuration; many workflows expect `config.yaml`.
- `saved/<year>/` — serialized PyPSA networks, e.g. `saved/2018/elec_s_10_ec_lcopt_Co2L-3h.nc` (load with `pypsa.Network(path)`).
- `data/` — input datasets and external data sources (subfolders: `copernicus/`, `osm/`, etc.).
- `results/`, `networks/` — outputs from runs and postprocessing.
- `doc/` — Sphinx docs and usage examples.
- `test/` — unit and integration tests run by CI.
- `notebooks/` and `shotton/shotton.ipynb` — working examples showing how PyPSA objects and time-series are used (`network.loads_t.p`, `network.generators_t.p`).

## Architecture & patterns AI should follow
- Core modelling objects are PyPSA `Network` instances persisted as NetCDFs in `saved/`. Typical usage: `network = pypsa.Network("../saved/2018/elec_s_...nc")` and time series access like `network.loads_t.p`.
- The repository is a data-driven Snakemake pipeline: add or change pipeline steps in `Snakefile` or `benchmarks/*` and update `config.yaml` accordingly.
- Configuration is file-based. For local tests and tutorials, copy/rename `config.tutorial.yaml` → `config.yaml` before running Snakemake.
- Many helper scripts and analysis notebooks live in `scripts/`, `shotton/` or `notebooks/`. Use those as examples for input/output conventions.

## Developer workflows (concrete commands)
- Create environment: `conda env create -f envs/environment.yaml` (or use `mamba` for speed).
- Install Jupyter kernel: `ipython kernel install --user --name=pypsa-earth` and run `jupyter lab` for notebooks.
- Dry-run pipeline: from repo root with `config.yaml` present run `snakemake -j 1 solve_all_networks -n` (remove `-n` to execute).
- Run tests locally: run pytest on the `test/` folder (CI uses the same tests); e.g. `pytest -q test/`.
- Formatting / pre-commit: the project uses `black` and pre-commit. Run `pre-commit run --all-files` when modifying code.

## External integrations & runtime requirements
- A solver is required for optimization (HiGHS recommended). See PyPSA docs for HiGHS install details.
- Java is required for some parts; `java -version` should report a compatible JRE.
- Large datasets come from `data/` and external sources (Copernicus, OSM, Atlite). Avoid trying to download large public datasets in PRs — prefer small fixtures or mocks in `test/`.

## Conventions for patches and PRs
- Small, focused PRs are preferred: change one pipeline rule, one analysis script, or one API surface at a time.
- When changing pipeline inputs/outputs, update `Snakefile` and add a short note in `doc/` or the PR description showing how to run the modified step with `snakemake -n` first.
- If introducing a new public function or changing I/O formats, add or update tests under `test/` and a short example notebook or script in `notebooks/` or `shotton/`.

## Concrete examples an AI agent can use
- Inspect `shotton/shotton.ipynb` to see how NetCDF networks are loaded and how `loads_t.p` is summed and plotted.
- Use `saved/2018/...nc` as canonical examples for network file naming and structure.
- Pipeline rule examples live in `benchmarks/build_powerplants` and `benchmarks/build_renewable_profiles_solar` — follow their input/output convention when adding new rules.

## Safety & scope
- Do not attempt to download large datasets or upload private data. Use small test fixtures or point to `data/custom/` for custom inputs.
- Do not expose or attempt to retrieve secrets (API keys, credentials) from the environment.

---
If anything here is unclear or you want more detail in a particular area (tests, Snakemake rules, or NetCDF conventions), tell me which area and I'll expand or merge additional examples.
