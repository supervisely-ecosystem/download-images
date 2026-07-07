import asyncio
import os
import re
from collections import defaultdict, namedtuple

import supervisely as sly
from dotenv import load_dotenv
from supervisely._utils import generate_free_name
from supervisely.api.entities_collection_api import CollectionType, CollectionTypeFilter

import workflow as w

if sly.is_development():
    load_dotenv("local.env")
    load_dotenv(os.path.expanduser("~/supervisely.env"))

api: sly.Api = sly.Api.from_env()

DatasetData = namedtuple("DatasetData", ["name", "id", "image_infos"])

SLY_APP_DATA_DIR = sly.app.get_data_dir()
TMP_DIR = os.path.join(SLY_APP_DATA_DIR, "tmp")
RES_DIR = os.path.join(SLY_APP_DATA_DIR, "res")
os.makedirs(TMP_DIR, exist_ok=True)
os.makedirs(RES_DIR, exist_ok=True)

if api.server_address == "https://app.supervisely.com":
    semaphore = api.get_default_semaphore()
    if semaphore._value == 10:
        api.set_semaphore_size(7)

DOWNLOAD_BATCH_SIZE = 5000
APP_NAME = "Download images"
COLLECTION_ID = os.environ.get("modal.state.collectionId")
PRESERVE_STRUCTURE = (os.environ.get("modal.state.preserveStructure", "true")).lower() == "true"
FLAT_DATASET_NAME = os.environ.get("modal.state.datasetName")
# auto-created filter collections are named like "Filtered entities 2026-07-03T14-31-57-501Z"
FILTERED_COLLECTION_PATTERN = re.compile(
    r"^Filtered entities \d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z"
)


def rename_filtered_collection(collection_info) -> None:
    """Rename an auto-created filter collection to reflect the task that processed it."""
    if not FILTERED_COLLECTION_PATTERN.match(collection_info.name):
        return
    task_id = sly.env.task_id(raise_not_found=False)
    if task_id is None:
        return
    new_name = f"{APP_NAME} (Task {task_id})"
    try:
        api.entities_collection.update(collection_info.id, name=new_name)
        sly.logger.info(
            f"Collection {collection_info.id} renamed: '{collection_info.name}' -> '{new_name}'"
        )
    except Exception as e:
        sly.logger.warning(f"Failed to rename collection {collection_info.id}: {repr(e)}")


def get_collection_image_infos(collection_id: int):
    """Return the collection info and its image infos."""
    collection_info = api.entities_collection.get_info_by_id(collection_id)
    if collection_info is None:
        raise ValueError(f"Collection with id={collection_id} not found")
    collection_type = (
        CollectionTypeFilter.AI_SEARCH
        if collection_info.type == CollectionType.AI_SEARCH
        else CollectionTypeFilter.DEFAULT
    )
    image_infos = api.entities_collection.get_items(
        collection_id, collection_type, collection_info.project_id
    )
    if len(image_infos) == 0:
        raise ValueError(f"Collection with id={collection_id} is empty")
    return collection_info, image_infos


def disambiguate_names(image_infos):
    """Rename images whose names repeat across datasets in the flat list.

    Every image involved in a name conflict gets its source dataset ID appended
    to the name, so the origin of each file stays visible.
    """
    name_counts = defaultdict(int)
    for image_info in image_infos:
        name_counts[image_info.name] += 1
    used_names = {image_info.name for image_info in image_infos}
    result = []
    for image_info in image_infos:
        if name_counts[image_info.name] < 2:
            result.append(image_info)
            continue
        if "." in image_info.name:
            stem, ext = image_info.name.rsplit(".", 1)
            new_name = f"{stem}_{image_info.dataset_id}.{ext}"
        else:
            new_name = f"{image_info.name}_{image_info.dataset_id}"
        new_name = generate_free_name(
            used_names, new_name, with_ext=True, extend_used_names=True
        )
        sly.logger.info(
            f"Duplicate image name in collection: '{image_info.name}' "
            f"(dataset {image_info.dataset_id}) renamed to '{new_name}'"
        )
        result.append(image_info._replace(name=new_name))
    return result


class ExportImages(sly.app.Export):
    def _process_datasets(self, project_id: int, dataset_id=None):
        for path, dataset in api.dataset.tree(project_id, dataset_id=dataset_id):
            dataset_info = api.dataset.get_info_by_id(dataset.id)
            path = "/".join(path)
            path = os.path.join(path, dataset_info.name)
            self.image_data[path] = self.read_dataset(dataset_info)

    def _process_collection(self, collection_id: int) -> int:
        collection_info, image_infos = get_collection_image_infos(collection_id)
        rename_filtered_collection(collection_info)
        if PRESERVE_STRUCTURE:
            by_dataset = defaultdict(list)
            for image_info in image_infos:
                by_dataset[image_info.dataset_id].append(image_info)
            for path, dataset in api.dataset.tree(collection_info.project_id):
                if dataset.id not in by_dataset:
                    continue
                path = "/".join(path)
                path = os.path.join(path, dataset.name)
                dataset_image_infos = by_dataset[dataset.id]
                self.image_data[path] = DatasetData(
                    dataset.name, dataset.id, dataset_image_infos
                )
                self.images_number += len(dataset_image_infos)
        else:
            folder_name = FLAT_DATASET_NAME or f"Collection {collection_info.id}"
            image_infos = disambiguate_names(image_infos)
            self.image_data[""] = DatasetData(folder_name, collection_info.id, image_infos)
            self.images_number += len(image_infos)
        return collection_info.project_id

    def process(self, context: sly.app.Export.Context):
        self.selected_project = sly.io.env.project_id(raise_not_found=False)
        self.selected_dataset = sly.io.env.dataset_id(raise_not_found=False)
        self.selected_collection = COLLECTION_ID
        self.image_data = {}
        self.images_number = 0

        if self.selected_collection:
            sly.logger.info(f"App launched for collection: {self.selected_collection}")

            project_id = self._process_collection(int(self.selected_collection))
            w.workflow_input(api, project_id, type="project")
        elif self.selected_dataset:
            sly.logger.info(f"App launched from dataset: {self.selected_dataset}")

            dataset_info = api.dataset.get_info_by_id(self.selected_dataset)
            project_id = dataset_info.project_id

            self._process_datasets(project_id, dataset_id=self.selected_dataset)
            w.workflow_input(api, self.selected_dataset, type="dataset")
        else:
            sly.logger.info(f"App launched from project: {self.selected_project}")
            project_id = self.selected_project

            self._process_datasets(project_id)

            w.workflow_input(api, self.selected_project, type="project")
        self.project_name = api.project.get_info_by_id(project_id).name
        self.archive_name = self.project_name + ".tar"

        self.download_images()
        self.archive_images()

        return self.archive_path

    def archive_images(self):
        input_path = os.path.join(TMP_DIR)
        self.archive_path = os.path.join(RES_DIR, self.archive_name)

        sly.fs.archive_directory(input_path, self.archive_path)

    def download_images(self):
        progress = sly.Progress("Downloading images", self.images_number, need_info_log=True)

        for path, dataset_data in self.image_data.items():
            if path == "":
                dataset_path = os.path.join(TMP_DIR, self.project_name, dataset_data.name)
            else:
                dataset_path = os.path.join(TMP_DIR, self.project_name, path)

            os.makedirs(dataset_path, exist_ok=True)
            loop = sly.utils.get_or_create_event_loop()
            for image_infos_batch in sly.batched(dataset_data.image_infos, DOWNLOAD_BATCH_SIZE):
                image_ids = [image_info.id for image_info in image_infos_batch]
                paths = [
                    os.path.join(dataset_path, image_info.name)
                    for image_info in image_infos_batch
                ]
                coro = api.image.download_paths_async(
                    image_ids, paths, progress_cb=progress.iters_done_report
                )
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(coro, loop)
                    future.result()
                else:
                    loop.run_until_complete(coro)

    def read_dataset(self, dataset_info):
        image_infos = api.image.get_list(dataset_info.id, force_metadata_for_links=False)
        self.images_number += len(image_infos)
        return DatasetData(dataset_info.name, dataset_info.id, image_infos)


@sly.handle_exceptions(has_ui=False)
def main():
    try:
        app = ExportImages()
        app.run()
        w.workflow_output(api, app.output_file)
    finally:
        if not sly.is_development():
            sly.logger.info(f"Remove sly app directory: {SLY_APP_DATA_DIR}")
            sly.fs.remove_dir(SLY_APP_DATA_DIR)


if __name__ == "__main__":
    sly.main_wrapper("main", main)
