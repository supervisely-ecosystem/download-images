import os

from collections import namedtuple

import supervisely as sly
from dotenv import load_dotenv

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


class ExportImages(sly.app.Export):
    def process(self, context: sly.app.Export.Context):
        self.selected_project = sly.io.env.project_id(raise_not_found=False)
        self.selected_dataset = sly.io.env.dataset_id(raise_not_found=False)
        self.image_data = []
        self.images_number = 0

        if self.selected_dataset:
            sly.logger.info(f"App launched from dataset: {self.selected_dataset}")

            dataset_info = api.dataset.get_info_by_id(self.selected_dataset)
            project_id = dataset_info.project_id

            self.read_dataset(dataset_info)

        else:
            sly.logger.info(f"App launched from project: {self.selected_project}")
            project_id = self.selected_project

            datasets = api.dataset.get_list(self.selected_project)
            for dataset in datasets:
                dataset_info = api.dataset.get_info_by_id(dataset.id)
                self.read_dataset(dataset_info)

        self.project_name = api.project.get_info_by_id(project_id).name
        self.archive_name = self.project_name + ".tar"

        self.download_images()
        self.archive_images()

        return self.archive_path

    def archive_images(self):
        input_path = os.path.join(TMP_DIR, self.project_name)
        self.archive_path = os.path.join(RES_DIR, self.archive_name)

        sly.fs.archive_directory(input_path, self.archive_path)

    def download_images(self):
        progress = sly.Progress(
            "Downloading images", self.images_number, need_info_log=True
        )

        for dataset_data in self.image_data:
            for batched_image_infos in sly.batched(
                dataset_data.image_infos,
            ):
                batched_image_ids = [
                    image_info.id for image_info in batched_image_infos
                ]

                dataset_path = os.path.join(
                    TMP_DIR, self.project_name, dataset_data.name
                )
                os.makedirs(dataset_path, exist_ok=True)

                paths = [
                    os.path.join(dataset_path, image_info.name)
                    for image_info in batched_image_infos
                ]

                api.image.download_paths(dataset_data.id, batched_image_ids, paths)

                progress.iters_done_report(len(batched_image_ids))

    def read_dataset(self, dataset_info):
        image_infos = api.image.get_list(
            dataset_info.id, force_metadata_for_links=False
        )

        self.image_data.append(
            DatasetData(dataset_info.name, dataset_info.id, image_infos)
        )
        self.images_number += len(image_infos)


app = ExportImages()
app.run()
