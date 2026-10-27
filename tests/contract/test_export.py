"""Contract tests: ExportImages.process() on every cases/*.env against a real instance.

Opt-in: SLY_CONTRACT_TESTS=1 and a dev token in ~/supervisely.env. Read-only on the platform:
process() downloads images and builds the .tar locally; the upload (set_download) and workflow
lineage happen in main(), which is not called here. Collection launches (which may rename an
auto-created filter collection) are not among the cases.

    SLY_CONTRACT_TESTS=1 pytest -m contract tests/contract
"""

import json
import os
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

import pytest
import supervisely as sly
from dotenv import dotenv_values

import main

CASES = sorted((Path(__file__).parents[2] / "cases").glob("*.env"))

pytestmark = [
    pytest.mark.contract,
    pytest.mark.skipif(os.environ.get("SLY_CONTRACT_TESTS") != "1", reason="set SLY_CONTRACT_TESTS=1"),
]


@pytest.fixture(scope="module")
def api():
    env = dotenv_values(os.path.expanduser("~/supervisely.env"))
    if not env.get("SERVER_ADDRESS") or not env.get("API_TOKEN"):
        pytest.skip("no ~/supervisely.env")
    return sly.Api(env["SERVER_ADDRESS"], env["API_TOKEN"])


def expected_images(api, project_id, dataset_id, entity_ids):
    """(folder path relative to the project, ImageInfo) for every image the launch covers."""
    paths = {ds.id: "/".join([*parents, ds.name]) for parents, ds in api.dataset.tree(project_id)}
    if entity_ids:
        infos = api.image.get_info_by_id_batch(entity_ids)
    else:
        ds_ids = [ds.id for _, ds in api.dataset.tree(project_id, dataset_id=dataset_id)]
        infos = [i for ds_id in ds_ids for i in api.image.get_list(ds_id)]
    return [(paths[i.dataset_id], i) for i in infos]


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_case(case, api, monkeypatch, tmp_path):
    env = dotenv_values(case)
    project_id = int(env["PROJECT_ID"])
    dataset_id = int(env["DATASET_ID"]) if env.get("DATASET_ID") else None
    entity_ids = json.loads(env.get("modal.state.entityIds") or "null")
    preserve = env.get("modal.state.preserveStructure", "true").lower() == "true"
    flat_name = env.get("modal.state.datasetName") or ""

    monkeypatch.setattr(main, "api", api)
    monkeypatch.setattr(main, "TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setattr(main, "RES_DIR", str(tmp_path / "res"))
    os.makedirs(main.TMP_DIR)
    os.makedirs(main.RES_DIR)
    monkeypatch.setattr(main, "PRESERVE_STRUCTURE", preserve)
    monkeypatch.setattr(main, "FLAT_DATASET_NAME", flat_name)
    monkeypatch.setattr(main, "COLLECTION_ID", None)
    monkeypatch.setattr(main, "ENTITY_IDS", entity_ids)
    monkeypatch.setattr(sly.io.env, "project_id", lambda raise_not_found=True: project_id)
    monkeypatch.setattr(sly.io.env, "dataset_id", lambda raise_not_found=True: dataset_id)

    archive = main.ExportImages().process(context=None)

    project_name = api.project.get_info_by_id(project_id).name
    assert archive == os.path.join(main.RES_DIR, f"{project_name}.tar")
    with tarfile.open(archive) as tar:
        files = [m.name.strip("/") for m in tar.getmembers() if m.isfile() and m.size > 0]
    expected = expected_images(api, project_id, dataset_id, entity_ids)
    assert len(files) == len(expected)

    by_folder = defaultdict(list)
    for f in files:
        folder, name = f.rsplit("/", 1)
        assert len(name) <= main.MAX_NAME_LENGTH
        by_folder[folder].append(name)

    if preserve or not entity_ids:
        want = Counter(f"{project_name}/{folder}" for folder, _ in expected)
        assert Counter({k: len(v) for k, v in by_folder.items()}) == want
        for folder, info in expected:
            if len(info.name) <= main.MAX_NAME_LENGTH:
                assert info.name in by_folder[f"{project_name}/{folder}"]
            else:
                ext = sly.fs.get_file_ext(info.name)
                assert any(n.endswith(ext) for n in by_folder[f"{project_name}/{folder}"])
    else:
        folder = f"{project_name}/{flat_name or project_name}"
        assert list(by_folder) == [folder]
        names = by_folder[folder]
        assert len(set(names)) == len(names)
        counts = Counter(info.name for _, info in expected)
        for _, info in expected:
            stem, ext = main.split_ext(info.name)
            if counts[info.name] > 1:
                assert any(n.endswith(f"_{info.dataset_id}{ext}") for n in names)
            elif len(info.name) <= main.MAX_NAME_LENGTH:
                assert info.name in names
