"""Offline tests of src/main.py: name helpers and ExportImages.process() for every launch source.

process() is run against FakeApi; the produced .tar is opened and its layout checked. This also covers
the asyncio path (sly.utils.get_or_create_event_loop + download_paths_async) on Python 3.14, where
asyncio.get_event_loop() no longer creates a loop implicitly.
"""

import os
import tarfile

import pytest
import supervisely as sly
from fake_api import CollectionInfo, DatasetInfo, FakeApi, ImageInfo
from supervisely.api.entities_collection_api import CollectionType

import main

LONG = "very_long_image_name_" * 4  # 84 chars


def make_api():
    datasets = [
        DatasetInfo(1, "ds1", 10, None),
        DatasetInfo(2, "ds2", 10, None),
        DatasetInfo(3, "sub", 10, 2),
    ]
    images = [
        ImageInfo(101, "a.jpg", 1),
        ImageInfo(102, "b.png", 1),
        ImageInfo(201, "a.jpg", 2),
        ImageInfo(301, "c.jpg", 3),
        ImageInfo(302, LONG + "one.jpeg", 3),
        ImageInfo(303, LONG + "two.jpeg", 3),
    ]
    collections = [
        CollectionInfo(7, "Filtered entities 2026-07-03T14-31-57-501Z", CollectionType.DEFAULT, 10),
        CollectionInfo(8, "My picks", CollectionType.DEFAULT, 10),
    ]
    api = FakeApi(10, "Fruits", datasets, images, collections)
    api.collection_items = {7: [101, 201, 301], 8: [102]}
    return api


@pytest.fixture
def app(monkeypatch, tmp_path):
    api = make_api()
    monkeypatch.setattr(main, "api", api)
    monkeypatch.setattr(main, "TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setattr(main, "RES_DIR", str(tmp_path / "res"))
    os.makedirs(main.TMP_DIR)
    os.makedirs(main.RES_DIR)
    monkeypatch.setattr(main, "PRESERVE_STRUCTURE", True)
    monkeypatch.setattr(main, "FLAT_DATASET_NAME", "")
    monkeypatch.setattr(main, "COLLECTION_ID", None)
    monkeypatch.setattr(main, "ENTITY_IDS", None)
    monkeypatch.delenv("TASK_ID", raising=False)
    ctx = {"project": 10, "dataset": None}
    monkeypatch.setattr(sly.io.env, "project_id", lambda raise_not_found=True: ctx["project"])
    monkeypatch.setattr(sly.io.env, "dataset_id", lambda raise_not_found=True: ctx["dataset"])
    return api, ctx


def run_process():
    exporter = main.ExportImages()
    archive = exporter.process(context=None)
    assert archive == os.path.join(main.RES_DIR, "Fruits.tar")
    with tarfile.open(archive) as tar:
        return {
            m.name.lstrip("./"): tar.extractfile(m).read().decode()
            for m in tar.getmembers()
            if m.isfile()
        }


def names(files):
    return sorted(files)


# --- pure helpers -------------------------------------------------------------------------------


def test_parse_entity_ids():
    assert main.parse_entity_ids(None) is None
    assert main.parse_entity_ids("") is None
    assert main.parse_entity_ids("[]") is None
    assert main.parse_entity_ids("not json") is None
    assert main.parse_entity_ids('[1, "2"]') == [1, 2]


def test_split_ext_and_cap_length():
    assert main.split_ext("a.b.jpg") == ("a.b", ".jpg")
    assert main.split_ext("noext") == ("noext", "")
    assert main.cap_length("short.jpg", 60) == "short.jpg"
    capped = main.cap_length("x" * 100 + ".jpeg", 60)
    assert capped == "x" * 55 + ".jpeg"


def test_fit_name_keeps_extension_and_uniqueness():
    used = set()
    first = main.fit_name(LONG + "one.jpeg", used)
    second = main.fit_name(LONG + "two.jpeg", used)
    for n in (first, second):
        assert len(n) <= main.MAX_NAME_LENGTH
        assert n.endswith(".jpeg")
    assert first != second
    assert main.fit_name("a.jpg", used) == "a.jpg"
    assert main.fit_name("a.jpg", used) != "a.jpg"


def test_disambiguate_names_appends_dataset_id_to_conflicts():
    infos = [ImageInfo(1, "a.jpg", 5), ImageInfo(2, "a.jpg", 6), ImageInfo(3, "b.jpg", 5)]
    out = main.disambiguate_names(infos)
    assert [i.name for i in out] == ["a_5.jpg", "a_6.jpg", "b.jpg"]
    assert [i.id for i in out] == [1, 2, 3]


def test_filtered_collection_pattern():
    assert main.FILTERED_COLLECTION_PATTERN.match("Filtered entities 2026-07-03T14-31-57-501Z")
    assert not main.FILTERED_COLLECTION_PATTERN.match("My picks")


# --- process() per launch source ----------------------------------------------------------------

FULL_TREE = {
    "Fruits/ds1/a.jpg": "img-101",
    "Fruits/ds1/b.png": "img-102",
    "Fruits/ds2/a.jpg": "img-201",
    "Fruits/ds2/sub/c.jpg": "img-301",
}


def test_project_launch_preserves_nested_tree(app):
    api, _ = app
    files = run_process()
    long_files = {k: v for k, v in files.items() if k not in FULL_TREE}
    assert {k: files[k] for k in FULL_TREE} == FULL_TREE
    assert sorted(long_files.values()) == ["img-302", "img-303"]
    for path in long_files:
        assert path.startswith("Fruits/ds2/sub/")
        base = os.path.basename(path)
        assert len(base) <= main.MAX_NAME_LENGTH and base.endswith(".jpeg")
    assert api.calls == [("input_project", 10)]


def test_dataset_launch_exports_subtree(app):
    api, ctx = app
    ctx["dataset"] = 2
    files = run_process()
    assert {k: v for k, v in files.items() if "very_long" not in k} == {
        "Fruits/ds2/a.jpg": "img-201",
        "Fruits/ds2/sub/c.jpg": "img-301",
    }
    assert len(files) == 4
    assert api.calls == [("input_dataset", 2)]


def test_selected_images_preserve_structure(app, monkeypatch):
    api, _ = app
    monkeypatch.setattr(main, "ENTITY_IDS", [101, 201, 301])
    files = run_process()
    assert files == {
        "Fruits/ds1/a.jpg": "img-101",
        "Fruits/ds2/a.jpg": "img-201",
        "Fruits/ds2/sub/c.jpg": "img-301",
    }
    assert api.calls == [("input_project", 10)]


def test_selected_images_flat_uses_project_name_and_disambiguates(app, monkeypatch):
    monkeypatch.setattr(main, "ENTITY_IDS", [101, 201, 301])
    monkeypatch.setattr(main, "PRESERVE_STRUCTURE", False)
    files = run_process()
    assert files == {
        "Fruits/Fruits/a_1.jpg": "img-101",
        "Fruits/Fruits/a_2.jpg": "img-201",
        "Fruits/Fruits/c.jpg": "img-301",
    }


def test_selected_images_flat_custom_folder_name(app, monkeypatch):
    monkeypatch.setattr(main, "ENTITY_IDS", [102])
    monkeypatch.setattr(main, "PRESERVE_STRUCTURE", False)
    monkeypatch.setattr(main, "FLAT_DATASET_NAME", "picked")
    assert run_process() == {"Fruits/picked/b.png": "img-102"}


def test_filtered_collection_flat_is_renamed_with_task_id(app, monkeypatch):
    api, _ = app
    monkeypatch.setattr(main, "COLLECTION_ID", "7")
    monkeypatch.setattr(main, "PRESERVE_STRUCTURE", False)
    monkeypatch.setenv("TASK_ID", "555")
    files = run_process()
    assert files == {
        "Fruits/Collection 7/a_1.jpg": "img-101",
        "Fruits/Collection 7/a_2.jpg": "img-201",
        "Fruits/Collection 7/c.jpg": "img-301",
    }
    assert api.calls == [
        ("rename_collection", 7, "Download images (Task 555)"),
        ("input_project", 10),
    ]


def test_named_collection_preserve_structure_not_renamed(app, monkeypatch):
    api, _ = app
    monkeypatch.setattr(main, "COLLECTION_ID", "8")
    monkeypatch.setenv("TASK_ID", "555")
    assert run_process() == {"Fruits/ds1/b.png": "img-102"}
    assert api.calls == [("input_project", 10)]


def test_empty_collection_fails(app, monkeypatch):
    api, _ = app
    api.collection_items[8] = []
    monkeypatch.setattr(main, "COLLECTION_ID", "8")
    with pytest.raises(ValueError, match="is empty"):
        run_process()


def test_downloads_are_batched(app, monkeypatch):
    api, _ = app
    monkeypatch.setattr(main, "DOWNLOAD_BATCH_SIZE", 1)
    run_process()
    assert all(len(batch) == 1 for batch in api.download_calls)
    assert len(api.download_calls) == 6


# --- main(): Export template, task output and workflow lineage ----------------------------------


def test_main_uploads_archive_and_records_lineage(app, monkeypatch, tmp_path):
    api, _ = app
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    monkeypatch.setattr(main, "SLY_APP_DATA_DIR", str(data_dir))
    import supervisely.app.export_template as export_template

    uploaded = []

    def fake_set_download(path):
        uploaded.append(path)
        return sly.api.file_api.FileInfo(
            **{f: None for f in sly.api.file_api.FileInfo._fields}
        )._replace(id=99, name=os.path.basename(path), team_id=1)

    monkeypatch.setattr(export_template.Api, "from_env", staticmethod(lambda: api))
    monkeypatch.setattr(export_template, "set_download", fake_set_download)
    monkeypatch.setattr(sly.io.env, "team_id", lambda raise_not_found=True: 1)
    monkeypatch.setattr(sly.io.env, "workspace_id", lambda raise_not_found=True: 2)
    monkeypatch.setattr(export_template.env, "dataset_id", lambda raise_not_found=True: None)
    monkeypatch.setattr(export_template.env, "project_id", lambda raise_not_found=True: 10)

    main.main()

    assert uploaded == [os.path.join(main.RES_DIR, "Fruits.tar")]
    assert api.calls == [("input_project", 10), ("output_file", 99)]
    # production run cleans up the app data dir
    assert not data_dir.exists()
