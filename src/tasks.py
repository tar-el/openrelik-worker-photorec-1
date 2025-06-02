# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import shutil
import os
from pathlib import Path
from uuid import uuid4
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-photorec.process_image"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "ProtoRec Image Processing",
    "description": "Processes images using ProtoRec.",
    "version": "0.1.0",
    # Configuration that will be rendered as a web for in the UI, and any data entered
    # by the user will be available to the task function when executing (task_config).
    "task_config": [
        {
            "name": "everything",
            "label": "everything",
            "description": "everything",
            "type": "checkbox",
            "required": False,
        },
        {
            "name": "jpg",
            "label": "jpg",
            "description": "jpg",
            "type": "checkbox",
            "required": False,
        },
    ],
}

@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Run photorec on input files.

    Args:
        pipe_result: Base64-encoded result from the previous Celery task, if any.
        input_files: List of input file dictionaries (unused if pipe_result exists).
        output_file_path: Path to the output directory.
        workflow_id: ID of the workflow.
        task_config: User configuration for the task.

    Returns:
        Log file containing task results.
        Directory containing the output files.
    """
    input_files = get_input_files(pipe_result, input_files or [])
    output_files = []
    export_directory = os.path.join(output_path, uuid4().hex)
    export_directory_out = export_directory + '.1'
    try:
        os.mkdir(export_directory)
    except OSError as e:
        print(f"Error: Cannot list directory contents. Reason: {e}")
    base_command = ["photorec", '/debug', '/log', '/d', export_directory, '/cmd' ]
    items = []

    for input_file in input_files:
        output_file = create_output_file(
            output_path,
            display_name=input_file.get("display_name"),
            extension=".txt",
            data_type="text/plain",
        )

        command = base_command + [input_file.get("path")]
#        command.append('fileopt,everything')

#        if task_config.get("everything"):
#            command.append(',enable')
#        else:
#            command.append(',disable')

#       if task_config.get("jpg"):
#            command.append(',enable')
#        else:
#            command.append(',disable')
#        command.append(',freespace,search')
        command.append('fileopt,everything,enable,jpg,enable,freespace,search')

        # Run the command
        with open(output_file.path, "w") as fh:
            subprocess.Popen(command, stdout=fh)
            logger.info('command' + str(command))

        output_files.append(output_file.to_dict())

        # Check files in export directory
        if export_directory:
            logger.info('output_path: ' + output_path)
            logger.info('export_directory: ' + export_directory)
            export_directory_path = Path(export_directory_out)
            logger.info('export_directory_out is: ' + str(export_directory_path))

            if os.path.isdir(export_directory_out):
                logger.info('directory found')
                try:
                    items = os.listdir(export_directory_out)
                    if not items:
                        logger.info('the directory is empty')
                except OSError as e:
                    print(f"Error: Cannot list directory contents. Reason: {e}")
            else:
                logger.info('directory not found')

            for item in items:
                # Construct the full path of the item
                item_path = os.path.join(export_directory_path, item)
                # Check if the item is a file
                if os.path.isfile(item_path):
                    logger.info(f"'{item}' is a file.")
                else:
                    logger.info(f"'{item}' is not a file.")

            extracted_files = [f for f in export_directory_path.glob("**/*") if f.is_file()]
            logger.info('extracted_files contains: ' + str(extracted_files))
            for file in extracted_files:
                logger.info('extracted file:' + file)
                original_path = str(file.relative_to(export_directory_path))
                output_file = create_output_file(
                    output_path,
                    display_name=file.name,
                    original_path=original_path,
                    data_type="extraction:image_export:file",
                    source_file_id=input_file.get("id"),
                )
                os.rename(file.absolute(), output_file.path)
                output_files.append(output_file.to_dict())
        else:
            if os.path.exists(export_directory_path):
                print(f"Error: The path points to a file, not a directory.")
            else:
                print(f"Error: Directory not found.")

        # Finally clean up the export directory
        #try:
        #    shutil.rmtree(export_directory)
        #except OSError as e:
        #    logger.info(e.errno)
        #try:
        #    shutil.rmtree(export_directory_out)          
        #except OSError as e:
        #    logger.info(e.errno)
    
    if not output_files:
        raise RuntimeError("No output files were created.")

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=base_command,
        meta={},
    )
