# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean CLI v1.0. Copyright 2021 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from unittest import mock

import pytest

from lean.components.config.lean_config_manager import LeanConfigManager
from lean.components.config.output_config_manager import OutputConfigManager
from lean.components.config.project_config_manager import ProjectConfigManager
from lean.components.config.storage import Storage
from lean.components.docker.lean_runner import LeanRunner
from lean.components.util.platform_manager import PlatformManager
from lean.components.util.project_manager import ProjectManager
from lean.components.util.temp_manager import TempManager
from lean.components.util.xml_manager import XMLManager
from lean.constants import DEFAULT_ENGINE_IMAGE
from lean.models.utils import DebuggingMethod
from lean.models.docker import DockerImage
from lean.models.modules import NuGetPackage
from tests.test_helpers import create_fake_lean_cli_directory

ENGINE_IMAGE = DockerImage.parse(DEFAULT_ENGINE_IMAGE)


def create_lean_runner(docker_manager: mock.Mock) -> LeanRunner:
    logger = mock.Mock()
    logger.debug_logging_enabled = False

    cli_config_manager = mock.Mock()
    cli_config_manager.user_id.get_value.return_value = "123"
    cli_config_manager.api_token.get_value.return_value = "456"

    project_config_manager = ProjectConfigManager(XMLManager())

    cache_storage = Storage(str(Path("~/.lean/cache").expanduser()))
    lean_config_manager = LeanConfigManager(logger,
                                            cli_config_manager,
                                            project_config_manager,
                                            mock.Mock(),
                                            cache_storage)
    output_config_manager = OutputConfigManager(lean_config_manager)

    module_manager = mock.Mock()
    module_manager.get_installed_packages.return_value = [NuGetPackage(name="QuantConnect.Brokerages", version="1.0.0")]

    xml_manager = XMLManager()
    project_manager = ProjectManager(project_config_manager, lean_config_manager, xml_manager, PlatformManager())

    return LeanRunner(logger,
                      project_config_manager,
                      lean_config_manager,
                      output_config_manager,
                      docker_manager,
                      module_manager,
                      project_manager,
                      TempManager(),
                      xml_manager)


@pytest.mark.parametrize("release", [False, True])
def test_run_lean_compiles_csharp_project_in_correct_configuration(release: bool) -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "CSharp Project" / "Main.cs",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         release,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    build_command = next((cmd for cmd in kwargs["commands"] if cmd.startswith("dotnet build")), None)
    assert build_command is not None

    assert f"Configuration={'Release' if release else 'Debug'}" in build_command


def test_run_lean_runs_lean_container_detached() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "CSharp Project" / "Main.cs",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         True)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert kwargs.get("detach", False)


def test_run_lean_runs_lean_container() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert args[0] == ENGINE_IMAGE
    assert any(cmd for cmd in kwargs["commands"] if cmd.endswith("dotnet QuantConnect.Lean.Launcher.dll"))


def test_run_lean_mounts_config_file() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert any([mount["Target"] == "/Lean/Launcher/bin/Debug/config.json" for mount in kwargs["mounts"]])


def test_run_lean_mounts_data_directory() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert any([volume["bind"] == "/Lean/Data" for volume in kwargs["volumes"].values()])

    key = next(key for key in kwargs["volumes"].keys() if kwargs["volumes"][key]["bind"] == "/Lean/Data")
    assert key == str(Path.cwd() / "data")


def test_run_lean_mounts_output_directory() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert any([volume["bind"] == "/Results" for volume in kwargs["volumes"].values()])

    key = next(key for key in kwargs["volumes"].keys() if kwargs["volumes"][key]["bind"] == "/Results")
    assert key == str(Path.cwd() / "output")


def test_run_lean_mounts_storage_directory() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert any([volume["bind"] == "/Storage" for volume in kwargs["volumes"].values()])

    key = next(key for key in kwargs["volumes"].keys() if kwargs["volumes"][key]["bind"] == "/Storage")
    assert key == str(Path.cwd() / "Python Project" / "storage")


def test_run_lean_creates_output_directory_when_not_existing_yet() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    assert (Path.cwd() / "output").is_dir()


def test_lean_runner_copies_code_to_output_directory() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    source_content = (Path.cwd() / "Python Project" / "main.py").read_text(encoding="utf-8")
    copied_content = (Path.cwd() / "output" / "code" / "main.py").read_text(encoding="utf-8")
    assert source_content == copied_content


def test_run_lean_compiles_python_project() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    build_command = next((cmd for cmd in kwargs["commands"] if cmd.startswith("python -m compileall")), None)
    assert build_command is not None

def test_run_lean_mounts_project_directory_when_running_python_algorithm() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         None,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert str(Path.cwd() / "Python Project") in kwargs["volumes"]


def test_run_lean_exposes_5678_when_debugging_with_ptvsd() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "Python Project" / "main.py",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         DebuggingMethod.PTVSD,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert kwargs["ports"]["5678"] == "5678"


def test_run_lean_sets_image_name_when_debugging_with_vsdbg() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "CSharp Project" / "Main.cs",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         DebuggingMethod.VSDBG,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert kwargs["name"] == "lean_cli_vsdbg"


def test_run_lean_exposes_ssh_when_debugging_with_rider() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = True

    lean_runner = create_lean_runner(docker_manager)

    lean_runner.run_lean({},
                         "backtesting",
                         Path.cwd() / "CSharp Project" / "Main.cs",
                         Path.cwd() / "output",
                         ENGINE_IMAGE,
                         DebuggingMethod.Rider,
                         False,
                         False)

    docker_manager.run_image.assert_called_once()
    args, kwargs = docker_manager.run_image.call_args

    assert kwargs["ports"]["22"] == "2222"


def test_run_lean_raises_when_run_image_fails() -> None:
    create_fake_lean_cli_directory()

    docker_manager = mock.Mock()
    docker_manager.run_image.return_value = False

    lean_runner = create_lean_runner(docker_manager)

    with pytest.raises(Exception):
        lean_runner.run_lean({},
                             "backtesting",
                             Path.cwd() / "Python Project" / "main.py",
                             Path.cwd() / "output",
                             ENGINE_IMAGE,
                             DebuggingMethod.PTVSD,
                             False,
                             False)

    docker_manager.run_image.assert_called_once()
