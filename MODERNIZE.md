# Modernization notes: download-images

Mechanical image move (campaign "shared legacy SDK image → hardened"), not a rewrite.
Base: `origin/master` @ d23dbc2 (v1.0.3). Branch `local/modernize`, nothing committed.

## Behaviour contract (unchanged)

Headless one-shot export, "Download as" on `images_project` / `images_dataset`.

| input | meaning |
|---|---|
| project / dataset context | whole project, or the dataset and its nested children |
| `modal.state.entityIds` (JSON list) | only these images (launch from an image selection); project id from context |
| `modal.state.collectionId` | images of an entities collection; an auto-created "Filtered entities <ts>" collection is renamed to `Download images (Task <id>)` |
| `modal.state.preserveStructure` (default `true`) | selection/collection: regroup into the dataset tree; `false` = one flat folder |
| `modal.state.datasetName` (default `""`) | flat folder name; empty = project name (selection) or `Collection <id>` |

Output: `<project name>.tar` set as the task download (`sly.app.Export` → `set_download`), layout
`<project>/<parent ds>/…/<ds>/<image name>` or `<project>/<flat folder>/<image name>`. Names are
capped to 60 chars keeping the extension, with `_NN` for collisions; in a flat folder, names that repeat
across datasets get `_<dataset id>`. Workflow lineage: project or dataset in, archive file out.

## Changes

1. `config.json`: `docker_image` `supervisely/import-export:6.74.34` → `supervisely/base-py-sdk-hardened:6.74.34`.
2. `dev_requirements.txt`: only `supervisely==6.74.34` (dropped unpinned `black`, a formatter, not a runtime dep).
3. `src/workflow.py`: ruff fixes only (`Union` → `|`, long comment). `src/main.py` untouched.
4. Added `pyproject.toml` (ruff `py314` + pytest config), `tests/`, `cases/*.env`, `.gitignore` entries.

No code change was needed for Python 3.14: the one 3.14-sensitive spot, `sly.utils.get_or_create_event_loop()`
(3.14's `asyncio.get_event_loop()` no longer creates a loop), falls back to `new_event_loop()` in SDK 6.74.34;
unit tests and real runs exercise it.

## Image decision

Bare `supervisely/base-py-sdk-hardened:6.74.34` (tag exists on Docker Hub; Python 3.14.7, amd64). The app uses
only the SDK (download + tar). The old shared image added import/export libraries (pycocotools, open3d,
nuscenes, lxml, scikit-image, …) none of which the app imports; the hardened base keeps the system libs the
SDK needs. SDK stays 6.74.34: `min_instance_version` 6.17.22 allows [6.74.29, 6.74.35) (`versions.json`).
Release CI (`workflows/release.py`) treats `base-py-sdk-hardened` as a standard image and takes the SDK
version from its tag. This repo's `release.yml` has no `build-image` job, so no per-app image is built.

## Tests

- `tests/unit` (offline, 15): name helpers; `ExportImages.process()` against an in-memory fake API for
  project, dataset subtree, selection (tree / flat / named flat), collections (filtered renamed / named not
  renamed / empty fails), batching; `main()` end to end (Export template, upload, lineage, data dir cleanup).
- `tests/contract` (`SLY_CONTRACT_TESTS=1 pytest -m contract tests/contract`): `process()` on every
  `cases/*.env` against dev, layout checked against the API. Read-only (no upload, no lineage).
- `cases/*.env`: 8 cases on dev reference projects 46, 1317, 9390 and sandbox project 9410.
  They are valid `docker --env-file` files (unquoted values).

## Verification (2026-10-25, dev.internal.supervisely.com 6.18.7)

- Unit tests: 15/15 on local Python 3.14.3 and inside `base-py-sdk-hardened:6.74.34` (3.14.7). `ruff check .` clean.
- Contract tests: 8/8.
- Old vs new on real projects: the published v1.0.3 (`fleet.py run`, old image, tasks 62692, 62694–62700)
  vs the new code in the hardened image (`python src/main.py`, `--env-file cases/<case>.env`): all 8 archives
  identical (same member paths and SHA-256 of every file): project-nested, project-lemons, project-synthetic,
  dataset-subtree, selected-flat-named, project-dupnames, selected-flat-dupnames, selected-tree.
  Scripts: session scratchpad `dlimg/scripts/{fetch_task_tar,compare}.py`.
- `ENV=production` in the image on debug task 62711 (port 8011), case project-dupnames: exit 0, archive
  uploaded (file 1719988), task output "Download archive", workflow lineage project 9410 → file 1719988,
  app data dir removed; uploaded archive identical to the old app's (task 62695).

Not covered on dev: collection launches (no collection in the reference projects; unit tests only).

## Created on dev (nothing deleted)

- Project 9410 "agents download-images dup-names" in workspace 733 (datasets 48143–48145, 7 images copied
  from project 46, with repeated and >60-char names).
- Tasks 62692, 62694–62700 (old app) and debug task 62711, all in workspace 733; their archives in team 1
  Team Files under `/tmp/supervisely/export/Download images/<task>/` and
  `/tmp/supervisely/export/Supervisely App/62711/`.

## Open

- `local.env` still points to another team's project (team 52 / project 4437) and a personal data dir; left as is.
