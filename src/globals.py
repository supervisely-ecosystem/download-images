import os

from collections import namedtuple

import supervisely as sly

from dotenv import load_dotenv

if sly.is_development():
    load_dotenv("local.env")
    load_dotenv(os.path.expanduser("~/supervisely.env"))

api: sly.Api = sly.Api.from_env()

SLY_APP_DATA_DIR = sly.app.get_data_dir()
TMP_DIR = os.path.join(SLY_APP_DATA_DIR, "tmp")
RES_DIR = os.path.join(SLY_APP_DATA_DIR, "res")
os.makedirs(TMP_DIR, exist_ok=True)
os.makedirs(RES_DIR, exist_ok=True)

BATCH_SIZE = 500


DatasetData = namedtuple("DatasetData", ["name", "id", "image_infos"])


class State:
    def __init__(self):
        self.selected_team = sly.io.env.team_id()
        self.selected_workspace = sly.io.env.workspace_id()
        self.selected_project = sly.io.env.project_id(raise_not_found=False)
        self.selected_dataset = sly.io.env.dataset_id(raise_not_found=False)

        self.project_name = None

        self.image_data = []
        self.images_number = 0

        self.archive_name = None
        self.archive_path = None


STATE = State()
