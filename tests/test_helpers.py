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

import json
from datetime import datetime
from pathlib import Path

from lean.commands.create_project import (DEFAULT_CSHARP_MAIN, DEFAULT_CSHARP_NOTEBOOK, DEFAULT_PYTHON_MAIN,
                                          DEFAULT_PYTHON_NOTEBOOK)
from lean.models.api import QCLanguage, QCLiveResults, QCProject, QCFullOrganization, \
    QCOrganizationData, QCOrganizationCredit


def create_fake_lean_cli_directory() -> None:
    """Creates a directory structure similar to the one created by `lean init` with a Python and a C# project."""
    (Path.cwd() / "data").mkdir()

    files = {
        (Path.cwd() / "lean.json"): """
{
    // data-folder documentation
    "data-folder": "data"
}
        """,
        (Path.cwd() / "Python Project" / "main.py"): DEFAULT_PYTHON_MAIN.replace("$NAME$", "PythonProject"),
        (Path.cwd() / "Python Project" / "research.ipynb"): DEFAULT_PYTHON_NOTEBOOK,
        (Path.cwd() / "Python Project" / "config.json"): json.dumps({
            "algorithm-language": "Python",
            "parameters": {}
        }),
        (Path.cwd() / "CSharp Project" / "Main.cs"): DEFAULT_CSHARP_MAIN.replace("$NAME$", "CSharpProject"),
        (Path.cwd() / "CSharp Project" / "research.ipynb"): DEFAULT_CSHARP_NOTEBOOK,
        (Path.cwd() / "CSharp Project" / "config.json"): json.dumps({
            "algorithm-language": "CSharp",
            "parameters": {}
        }),
        (Path.cwd() / "CSharp Project" / "CSharp Project.csproj"): """
<Project Sdk="Microsoft.NET.Sdk">
    <PropertyGroup>
        <Configuration Condition=" '$(Configuration)' == '' ">Debug</Configuration>
        <Platform Condition=" '$(Platform)' == '' ">AnyCPU</Platform>
        <TargetFramework>net6.0</TargetFramework>
        <OutputPath>bin/$(Configuration)</OutputPath>
        <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
        <NoWarn>CS0618</NoWarn>
    </PropertyGroup>
    <ItemGroup>
        <PackageReference Include="QuantConnect.Lean" Version="2.5.11940" />
    </ItemGroup>
</Project>
        """
    }

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w+") as file:
            file.write(content)


def create_api_project(id: int, name: str) -> QCProject:
    """Creates a fake API project response."""
    return QCProject(
        projectId=id,
        organizationId="123",
        name=name,
        description="Description",
        modified=datetime.now(),
        created=datetime.now(),
        language=QCLanguage.Python,
        collaborators=[],
        leanVersionId=10500,
        leanPinnedToMaster=True,
        parameters=[],
        liveResults=QCLiveResults(eStatus="Unknown"),
        libraries=[]
    )

def create_api_organization() -> QCFullOrganization:
    return QCFullOrganization(id="1",
                              name="a",
                              seats=1,
                              type="type",
                              credit=QCOrganizationCredit(movements=[], balance=1000000),
                              products=[],
                              data=QCOrganizationData(signedTime=None, current=False),
                              members=[])
