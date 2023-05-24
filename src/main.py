import os

import supervisely as sly

import src.globals as g


app = sly.Application()


def read_dataset(dataset_info):
    image_infos = g.api.image.get_list(dataset_info.id, force_metadata_for_links=False)

    g.STATE.image_data.append(
        g.DatasetData(dataset_info.name, dataset_info.id, image_infos)
    )
    g.STATE.images_number += len(image_infos)


def update_image_data():
    if g.STATE.selected_dataset:
        sly.logger.info(f"App launched from dataset: {g.STATE.selected_dataset}")

        dataset_info = g.api.dataset.get_info_by_id(g.STATE.selected_dataset)
        project_id = dataset_info.project_id

        read_dataset(dataset_info)

    else:
        sly.logger.info(f"App launched from project: {g.STATE.selected_project}")
        project_id = g.STATE.selected_project

        datasets = g.api.dataset.get_list(g.STATE.selected_project)
        for dataset in datasets:
            dataset_info = g.api.dataset.get_info_by_id(dataset.id)
            read_dataset(dataset_info)

    g.STATE.project_name = g.api.project.get_info_by_id(project_id).name
    g.STATE.archive_name = g.STATE.project_name + ".tar"


def download_images():
    progress = sly.Progress(
        "Downloading images", g.STATE.images_number, need_info_log=True
    )

    for dataset_data in g.STATE.image_data:
        for batched_image_infos in sly.batched(
            dataset_data.image_infos, batch_size=g.BATCH_SIZE
        ):
            batched_image_ids = [image_info.id for image_info in batched_image_infos]

            dataset_path = os.path.join(
                g.TMP_DIR, g.STATE.project_name, dataset_data.name
            )
            os.makedirs(dataset_path, exist_ok=True)

            paths = [
                os.path.join(dataset_path, image_info.name)
                for image_info in batched_image_infos
            ]

            g.api.image.download_paths(dataset_data.id, batched_image_ids, paths)

            progress.iters_done_report(len(batched_image_ids))


def archive_images():
    input_path = os.path.join(g.TMP_DIR, g.STATE.project_name)
    g.STATE.archive_path = os.path.join(g.RES_DIR, g.STATE.archive_name)

    sly.fs.archive_directory(input_path, g.STATE.archive_path)


def print_progress(monitor, upload_progress):
    if len(upload_progress) == 0:
        upload_progress.append(
            sly.Progress(
                message="Uploading archive",
                total_cnt=monitor.len,
                is_size=True,
            )
        )
    upload_progress[0].set_current_value(monitor.bytes_read)


def upload_archive():
    dst_path = "/download-images/" + g.STATE.archive_name

    upload_progress = []

    g.api.file.upload(
        g.STATE.selected_team,
        g.STATE.archive_path,
        dst_path,
        lambda m: print_progress(m, upload_progress),
    )


def clean_dirs():
    sly.fs.clean_dir(g.TMP_DIR, ignore_errors=True)
    sly.fs.clean_dir(g.RES_DIR, ignore_errors=True)


clean_dirs()
update_image_data()
download_images()
archive_images()
upload_archive()
clean_dirs()
