"""Small in-memory stand-in for the few `api.*` calls src/main.py makes."""

import asyncio
import os
from collections import namedtuple
from types import SimpleNamespace

ImageInfo = namedtuple("ImageInfo", ["id", "name", "dataset_id"])
DatasetInfo = namedtuple("DatasetInfo", ["id", "name", "project_id", "parent_id"])
CollectionInfo = namedtuple("CollectionInfo", ["id", "name", "type", "project_id"])


class FakeApi:
    """datasets: list of DatasetInfo; images: list of ImageInfo; image bytes are f"img-{id}"."""

    server_address = "http://fake.supervisely.local"

    def __init__(self, project_id, project_name, datasets, images, collections=()):
        self.project_name = project_name
        self.project_id = project_id
        self.datasets = {d.id: d for d in datasets}
        self.images = {i.id: i for i in images}
        self.collections = {c.id: c for c in collections}
        self.collection_items = {}
        self.calls = []
        self.download_calls = []

        self.project = SimpleNamespace(get_info_by_id=self._project_info)
        self.dataset = SimpleNamespace(tree=self._tree, get_info_by_id=self.datasets.get)
        self.image = SimpleNamespace(
            get_list=self._image_list,
            get_info_by_id_batch=self._image_batch,
            download_paths_async=self._download_paths_async,
        )
        self.entities_collection = SimpleNamespace(
            get_info_by_id=self.collections.get,
            get_items=self._collection_items,
            update=lambda cid, name: self.calls.append(("rename_collection", cid, name)),
        )
        wf = SimpleNamespace(
            add_input_project=lambda pid: self.calls.append(("input_project", pid)),
            add_input_dataset=lambda did: self.calls.append(("input_dataset", did)),
            add_output_file=lambda f, meta=None: self.calls.append(("output_file", f.id)),
        )
        self.app = SimpleNamespace(workflow=wf)

    def _project_info(self, id):
        assert id == self.project_id
        return SimpleNamespace(id=id, name=self.project_name, type="images")

    def _children(self, parent_id):
        return [d for d in self.datasets.values() if d.parent_id == parent_id]

    def _tree(self, project_id, dataset_id=None):
        def walk(parent_id, parents):
            for ds in self._children(parent_id):
                yield parents, ds
                yield from walk(ds.id, parents + [ds.name])

        if dataset_id is None:
            yield from walk(None, [])
        else:
            ds = self.datasets[dataset_id]
            yield [], ds
            yield from walk(ds.id, [ds.name])

    def _image_list(self, dataset_id, force_metadata_for_links=True):
        assert force_metadata_for_links is False
        return [i for i in self.images.values() if i.dataset_id == dataset_id]

    def _image_batch(self, ids, force_metadata_for_links=True):
        assert force_metadata_for_links is False
        return [self.images[i] for i in ids]

    def _collection_items(self, collection_id, collection_type, project_id):
        return [self.images[i] for i in self.collection_items[collection_id]]

    async def _download_paths_async(self, ids, paths, progress_cb=None):
        assert len(ids) == len(paths)
        self.download_calls.append(list(ids))
        await asyncio.sleep(0)
        for image_id, path in zip(ids, paths, strict=True):
            assert not os.path.exists(path), f"two images written to {path}"
            with open(path, "w") as f:
                f.write(f"img-{image_id}")
        if progress_cb is not None:
            progress_cb(len(ids))
