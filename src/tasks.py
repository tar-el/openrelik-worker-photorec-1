import logging
import os
import subprocess
import shutil
from pathlib import Path
from uuid import uuid4
from .app import celery
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TASK_NAME = "openrelik-worker-photorec.process_image"

TASK_METADATA = {
    "display_name": "PhotoRec File Recovery",
    "description": "Uses PhotoRec to recover deleted files from a disk image.",
    "version": "0.1.0",
    "task_config": [
        {
            "name": "everything", "label": "Recover all file types",
            "description": "Performs a comprehensive scan to attempt recovery of all file types supported by Photorec.",
            "type": "checkbox", "required": False,
        },
        {
            "name": "jpg", "label": "Recover only JPEGs",
            "description": "Restricts the file recovery scan to only JPEG image formats (.jpg, .jpeg).",
            "type": "checkbox", "required": False,
        },
    ],
}

@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(self, pipe_result: str = None, input_files: list = None, output_path: str = None, workflow_id: str = None, task_config: dict = None) -> str:
    task_config = task_config or {}
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []
    meta_summary = {}
    base_output_path = Path(output_path)

    for input_file in input_files:
        temp_export_dir = base_output_path / uuid4().hex
        try:
            temp_export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Error creating temp directory {temp_export_dir}: {e}")
            continue

        log_output_file = create_output_file(
            output_path,
            display_name=f"photorec_log_{Path(input_file.get('display_name')).name}.txt",
            extension=".txt", data_type="text/plain",
        )

        base_command = ["photorec", "/debug", "/log", "/d", str(temp_export_dir), "/cmd", input_file.get("path")]

        options = ["fileopt"]
        if task_config.get("everything"):
            options.append("everything,enable")
            options.append("jpg,disable")
        elif task_config.get("jpg"):
            options.append("everything,disable")
            options.append("jpg,enable")
        else: # Default behavior if nothing is checked
            options.append("everything,enable")
            options.append("jpg,disable")
        options.append("freespace,search")
        final_command = base_command + [",".join(options)]

        logger.info(f"Running command: {' '.join(final_command)}")
        try:
            with open(log_output_file.path, "w") as fh:
                subprocess.run(final_command, stdout=fh, stderr=fh, check=True)
        except subprocess.CalledProcessError as e:
            error_message = (f"Photorec command failed with return code {e.returncode}.\n"
                             f"Stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
            logger.error(error_message)
            output_files.append(log_output_file.to_dict())
            continue
        except FileNotFoundError:
            logger.error("Photorec command not found. Is it installed and in the system's PATH?")
            output_files.append(log_output_file.to_dict())
            continue

        output_files.append(log_output_file.to_dict())

        found_dirs = list(temp_export_dir.glob("recup_dir.*"))
        if not found_dirs:
            logger.warning(f"Photorec ran successfully but no files were recovered from {input_file.get('display_name')}.")
            meta_summary[input_file.get('display_name')] = "No files recovered."

        for recup_dir in found_dirs:
            recovered_count = 0
            logger.info(f"Processing recovered files in: {recup_dir}")
            for recovered_file in recup_dir.rglob("*"):
                if recovered_file.is_file():
                    recovered_count += 1
                    output_file_obj = create_output_file(
                        output_path, display_name=recovered_file.name,
                        original_path=str(recovered_file.relative_to(recup_dir)),
                        data_type="extraction:image_export:file",
                        source_file_id=input_file.get("id"),
                    )
                    recovered_file.rename(output_file_obj.path)
                    output_files.append(output_file_obj.to_dict())
            meta_summary[input_file.get('display_name')] = f"Successfully recovered {recovered_count} file(s)."

        try:
            shutil.rmtree(temp_export_dir)
        except OSError as e:
            logger.error(f"Failed to remove temp directory {temp_export_dir}: {e}")

    return create_task_result(output_files=output_files, workflow_id=workflow_id, command=["photorec", "..."], meta={"summary": meta_summary})