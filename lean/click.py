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

import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import click

from lean.constants import DEFAULT_LEAN_CONFIG_FILE_NAME
from lean.container import container
from lean.models.errors import MoreInfoError


class LeanCommand(click.Command):
    """A click.Command wrapper with some Lean CLI customization."""

    def __init__(self, requires_lean_config: bool = False, requires_docker: bool = False, *args, **kwargs):
        """Creates a new LeanCommand instance.

        :param requires_lean_config: True if this command requires a Lean config, False if not
        :param requires_docker: True if this command uses Docker, False if not
        :param args: the args that are passed on to the click.Command constructor
        :param kwargs: the kwargs that are passed on to the click.Command constructor
        """
        self._requires_lean_config = requires_lean_config
        self._requires_docker = requires_docker

        super().__init__(*args, **kwargs)

        # By default the width of help messages is min(terminal_width, max_content_width)
        # max_content_width defaults to 80, which we increase to 120 to improve readability on wide terminals
        self.context_settings["max_content_width"] = 120

    def invoke(self, ctx):
        if self._requires_lean_config:
            try:
                # This method will throw if the directory cannot be found
                container.lean_config_manager().get_cli_root_directory()
            except Exception:
                # Abort with a display-friendly error message if the command requires a Lean config
                raise MoreInfoError(
                    "This command requires a Lean configuration file, run `lean init` in an empty directory to create one, or specify the file to use with --lean-config",
                    "https://www.lean.io/docs/lean-cli/user-guides/troubleshooting#02-Common-errors")

        if self._requires_docker and "pytest" not in sys.modules:
            # The CLI uses temporary directories in /tmp because sometimes it may leave behind files owned by root
            # These files cannot be deleted by the CLI itself, so we rely on the OS to empty /tmp on reboot
            # The Snap version of Docker does not provide access to files outside $HOME, so we can't support it
            if platform.system() == "Linux":
                docker_path = shutil.which("docker")
                if docker_path is not None and docker_path.startswith("/snap"):
                    raise MoreInfoError(
                        "The Lean CLI does not work with the Snap version of Docker, please re-install Docker via the official installation instructions",
                        "https://docs.docker.com/engine/install/")

            # A usual Docker installation on Linux requires the user to use sudo to run Docker
            # If we detect that this is the case and the CLI was started without sudo we elevate automatically
            if platform.system() == "Linux" and os.getuid() != 0 and container.docker_manager().is_missing_permission():
                container.logger().info(
                    "This command requires access to Docker, you may be asked to enter your password")

                args = ["sudo", "--preserve-env=HOME", sys.executable, *sys.argv]
                os.execlp(args[0], *args)

        update_manager = container.update_manager()
        update_manager.show_announcements()

        result = super().invoke(ctx)

        update_manager.warn_if_cli_outdated()

        return result

    def get_params(self, ctx):
        params = super().get_params(ctx)

        # Add --lean-config option if the command requires a Lean config
        if self._requires_lean_config:
            params.insert(len(params) - 1, click.Option(["--lean-config"],
                                                        type=PathParameter(exists=True, file_okay=True, dir_okay=False),
                                                        help=f"The Lean configuration file that should be used (defaults to the nearest {DEFAULT_LEAN_CONFIG_FILE_NAME})",
                                                        expose_value=False,
                                                        is_eager=True,
                                                        callback=self._parse_config_option))

        # Add --verbose option
        params.insert(len(params) - 1, click.Option(["--verbose"],
                                                    help="Enable debug logging",
                                                    is_flag=True,
                                                    default=False,
                                                    expose_value=False,
                                                    is_eager=True,
                                                    callback=self._parse_verbose_option))

        ctx.obj = params

        return params

    def _parse_config_option(self, ctx: click.Context, param: click.Parameter, value: Optional[Path]) -> None:
        """Parses the --config option."""
        if value is not None:
            lean_config_manager = container.lean_config_manager()
            lean_config_manager.set_default_lean_config_path(value)

    def _parse_verbose_option(self, ctx: click.Context, param: click.Parameter, value: Optional[bool]) -> None:
        """Parses the --verbose option."""
        if value:
            logger = container.logger()
            logger.enable_debug_logging()


class PathParameter(click.ParamType):
    """A limited version of click.Path which uses pathlib.Path."""

    def __init__(self, exists: bool = False, file_okay: bool = True, dir_okay: bool = True):
        """Creates a new PathParameter instance.

        :param exists: True if the path needs to point to an existing object, False if not
        :param file_okay: True if the path may point to a file, False if not
        :param dir_okay: True if the path may point to a directory, False if not
        """
        self._exists = exists
        self._file_okay = file_okay
        self._dir_okay = dir_okay

        if file_okay and not dir_okay:
            self.name = "file"
            self._path_type = "File"
        elif dir_okay and not file_okay:
            self.name = "directory"
            self._path_type = "Directory"
        else:
            self.name = "path"
            self._path_type = "Path"

    def convert(self, value: str, param: click.Parameter, ctx: click.Context) -> Path:
        path = Path(value).expanduser().resolve()

        if not container.path_manager().is_path_valid(path):
            self.fail(f"{self._path_type} '{value}' is not a valid path.", param, ctx)

        if self._exists and not path.exists():
            self.fail(f"{self._path_type} '{value}' does not exist.", param, ctx)

        if not self._file_okay and path.is_file():
            self.fail(f"{self._path_type} '{value}' is a file.", param, ctx)

        if not self._dir_okay and path.is_dir():
            self.fail(f"{self._path_type} '{value}' is a directory.", param, ctx)

        return path


class DateParameter(click.ParamType):
    """A click parameter which returns datetime.datetime objects and requires yyyyMMdd input."""

    name = "date"

    def get_metavar(self, param: click.Parameter) -> str:
        return "[yyyyMMdd]"

    def convert(self, value: str, param: click.Parameter, ctx: click.Context) -> datetime:
        for date_format in ["%Y%m%d", "%Y-%m-%d"]:
            try:
                return datetime.strptime(value, date_format)
            except ValueError:
                pass

        self.fail(f"'{value}' does not match the yyyyMMdd format.", param, ctx)


def is_non_interactive(ctx: click.Context, non_interactive_parameters: List[str]) -> bool:
    """Checks whether a command invocation is to be seen as non-interactive.

    In a non-interactive invocation the CLI is not supposed to prompt the user for input.

    :param ctx: the click context of the invocation
    :param non_interactive_parameters: the names of the non-interactive parameters
    :return: True if the user provided at least one non-interactive parameter, False if not
    """
    return any(param in ctx.params and ctx.params[param] is not None for param in non_interactive_parameters)


def ensure_parameters_exist(ctx: click.Context, parameters: List[str]) -> None:
    """Ensures the user provided certain parameters, raises an error if not.

    :param ctx: the click context of the invocation
    :param parameters: the parameters the user must have provided
    """
    missing_parameters = [param for param in ctx.params.keys() if ctx.params[param] is None and param in parameters]
    if len(missing_parameters) == 0:
        return

    missing_parameters = sorted(missing_parameters, key=lambda param: parameters.index(param))
    help_records = []

    for name in missing_parameters:
        parameter = next(param for param in ctx.obj if param.name == name)
        help_records.append(parameter.get_help_record(ctx))

    help_formatter = click.HelpFormatter(max_width=120)
    help_formatter.write_dl(help_records)

    raise RuntimeError(f"""
You are missing the following parameter{"s" if len(missing_parameters) > 1 else ""}:
{''.join(help_formatter.buffer)}
    """.strip())
