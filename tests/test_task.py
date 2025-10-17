import pytest
import subprocess
from pathlib import Path
from src.tasks import command as photorec_task

@pytest.mark.parametrize("task_config, expected_options", [
    ({"everything": True, "jpg": False}, "fileopt,everything,enable,jpg,disable,freespace,search"),
    ({"everything": False, "jpg": True}, "fileopt,everything,disable,jpg,enable,freespace,search"),
    ({}, "fileopt,everything,enable,jpg,disable,freespace,search"),
])
def test_command_building_logic(mocker, task_config, expected_options):
    """Verifies the photorec command is built correctly for different user options."""
    mock_run = mocker.patch("src.tasks.subprocess.run")
    mocker.patch("shutil.rmtree")
    mocker.patch("openrelik_worker_common.file_utils.create_output_file")
    mocker.patch("openrelik_worker_common.task_utils.create_task_result")
    mocker.patch("pathlib.Path.mkdir")

    photorec_task.s(
        input_files=[{"path": "/in/img.dd", "display_name": "img.dd"}],
        output_path="/out",
        task_config=task_config
    ).apply()

    mock_run.assert_called_once()
    actual_command = mock_run.call_args.args[0]
    assert actual_command[-1] == expected_options

def test_photorec_success_path(mocker, tmp_path: Path):
    """Tests the full end-to-end success path, using a real temporary filesystem."""
    mock_run = mocker.patch("src.tasks.subprocess.run")
    mock_create_task_result = mocker.patch("openrelik_worker_common.task_utils.create_task_result")
    mock_create_output_file = mocker.patch("openrelik_worker_common.file_utils.create_output_file")
    mock_create_output_file.return_value.path = str(tmp_path / "mock_file.txt")
    mock_create_output_file.return_value.to_dict.return_value = {"display_name": "mock_file.txt"}

    def simulate_photorec_run(*args, **kwargs):
        temp_dir = Path(args[0][4])
        recup_dir = temp_dir / "recup_dir.1"
        recup_dir.mkdir()
        (recup_dir / "recovered.jpg").touch()

    mock_run.side_effect = simulate_photorec_run

    photorec_task.s(
        input_files=[{"path": "/in/img.dd", "id": "123", "display_name": "img.dd"}],
        output_path=str(tmp_path),
        task_config={"everything": True}
    ).apply()

    mock_run.assert_called_once()
    mock_create_task_result.assert_called_once()

    final_result_args = mock_create_task_result.call_args.kwargs
    output_files = final_result_args["output_files"]
    assert len(output_files) >= 2

def test_photorec_handles_subprocess_error(mocker, tmp_path: Path):
    """Verifies that if photorec fails, the error is logged and the task doesn't crash."""
    mock_run = mocker.patch("src.tasks.subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd", stderr=b"Disk read error"))
    mock_logger_error = mocker.patch("src.tasks.logger.error")
    mock_create_task_result = mocker.patch("openrelik_worker_common.task_utils.create_task_result")
    mocker.patch("openrelik_worker_common.file_utils.create_output_file")

    photorec_task.s(
        input_files=[{"path": "/in/img.dd", "display_name": "img.dd"}],
        output_path=str(tmp_path),
        task_config={}
    ).apply()

    mock_run.assert_called_once()
    mock_logger_error.assert_called_once()
    
    log_message = mock_logger_error.call_args.args[0]
    assert "Stderr: Disk read error" in log_message

    final_output_files = mock_create_task_result.call_args.kwargs["output_files"]
    assert len(final_output_files) == 1