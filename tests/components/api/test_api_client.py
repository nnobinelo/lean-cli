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
import re
from typing import Any
from unittest import mock

import pytest
from responses import RequestsMock

from lean.components.api.api_client import APIClient
from lean.components.util.http_client import HTTPClient
from lean.constants import API_BASE_URL
from lean.models.errors import AuthenticationError, RequestFailedError


def test_get_logger():
    logger = mock.MagicMock()
    logger.debug_logging_enabled = mock.PropertyMock()
    logger.debug_logging_enabled = False
    return logger

def test_get_makes_get_request_to_given_endpoint(requests_mock: RequestsMock) -> None:
    requests_mock.add(requests_mock.GET, API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    api.get("endpoint")

    assert len(requests_mock.calls) == 1
    assert requests_mock.calls[0].request.url == API_BASE_URL + "endpoint"


def test_get_attaches_parameters_to_url(requests_mock: RequestsMock) -> None:
    requests_mock.add(requests_mock.GET, API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    api.get("endpoint", {"key1": "value1", "key2": "value2"})

    assert len(requests_mock.calls) == 1
    assert requests_mock.calls[0].request.url == API_BASE_URL + "endpoint?key1=value1&key2=value2"


def test_post_makes_post_request_to_given_endpoint(requests_mock: RequestsMock) -> None:
    requests_mock.add(requests_mock.POST, API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    api.post("endpoint")

    assert len(requests_mock.calls) == 1
    assert requests_mock.calls[0].request.url == API_BASE_URL + "endpoint"


def test_post_sets_body_of_request_as_json(requests_mock: RequestsMock) -> None:
    requests_mock.add(requests_mock.POST, API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    api.post("endpoint", {"key1": "value1", "key2": "value2"})

    assert len(requests_mock.calls) == 1
    assert requests_mock.calls[0].request.url == API_BASE_URL + "endpoint"

    body = json.loads(requests_mock.calls[0].request.body)

    assert body["key1"] == "value1"
    assert body["key2"] == "value2"


def test_post_sets_body_of_request_as_form_data(requests_mock: RequestsMock) -> None:
    requests_mock.add(requests_mock.POST, API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    api.post("endpoint", {"key1": "value1", "key2": "value2"}, data_as_json=False)

    assert len(requests_mock.calls) == 1
    assert requests_mock.calls[0].request.url == API_BASE_URL + "endpoint"

    assert requests_mock.calls[0].request.body == "key1=value1&key2=value2"


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_makes_authenticated_requests(method: str, requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    getattr(api, method)("endpoint")

    assert len(requests_mock.calls) == 1

    headers = requests_mock.calls[0].request.headers
    assert "Timestamp" in headers
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_returns_data_when_success_is_true(method: str, requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    response = getattr(api, method)("endpoint")

    assert "success" in response
    assert response["success"]


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_authentication_error_on_http_500(method: str, requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", status=500)

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(AuthenticationError):
        getattr(api, method)("endpoint")


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_request_failed_error_on_failing_response_non_http_500(method: str,
                                                                                 requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", status=404)

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(RequestFailedError):
        getattr(api, method)("endpoint")


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_authentication_error_on_error_complaining_about_hash(method: str,
                                                                                requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(),
                      API_BASE_URL + "endpoint",
                      '{ "success": false, "errors": ["Hash doesn\'t match."] }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(AuthenticationError):
        getattr(api, method)("endpoint")


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_request_failed_error_when_response_contains_errors(method: str,
                                                                              requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(),
                      API_BASE_URL + "endpoint",
                      '{ "success": false, "errors": ["Error 1", "Error 2"] }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(RequestFailedError) as error:
        getattr(api, method)("endpoint")

    assert str(error.value) == "Error 1\nError 2"


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_request_failed_error_when_response_contains_messages(method: str,
                                                                                requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(),
                      API_BASE_URL + "endpoint",
                      '{ "success": false, "messages": ["Message 1", "Message 2"] }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(RequestFailedError) as error:
        getattr(api, method)("endpoint")

    assert str(error.value) == "Message 1\nMessage 2"


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_raises_request_failed_error_when_response_contains_internal_error(method: str,
                                                                                      requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(),
                      API_BASE_URL + "endpoint",
                      '{ "success": false, "Message": "Internal Error 21" }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(RequestFailedError) as error:
        getattr(api, method)("endpoint")

    assert str(error.value) == "Internal Error 21"


@pytest.mark.parametrize("method,status_code,expected_error", [("get", 500, AuthenticationError),
                                                               ("post", 500, AuthenticationError),
                                                               ("get", 502, RequestFailedError),
                                                               ("post", 502, RequestFailedError)])
def test_api_client_retries_request_when_response_is_http_5xx_error(method: str,
                                                                    status_code: int,
                                                                    expected_error: Any,
                                                                    requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", status=status_code)

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    with pytest.raises(expected_error):
        getattr(api, method)("endpoint")

    requests_mock.assert_call_count(API_BASE_URL + "endpoint", 2)


@pytest.mark.parametrize("method", ["get", "post"])
def test_api_client_sets_user_agent(method: str, requests_mock: RequestsMock) -> None:
    requests_mock.add(method.upper(), API_BASE_URL + "endpoint", '{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")
    getattr(api, method)("endpoint")

    assert len(requests_mock.calls) == 1

    headers = requests_mock.calls[0].request.headers
    assert headers["User-Agent"].startswith("Lean CLI ")


def test_is_authenticated_returns_true_when_authenticated_request_succeeds(requests_mock: RequestsMock) -> None:
    requests_mock.assert_all_requests_are_fired = False
    requests_mock.add(requests_mock.GET, re.compile(".*"), body='{ "success": true }')
    requests_mock.add(requests_mock.POST, re.compile(".*"), body='{ "success": true }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    assert api.is_authenticated()


def test_is_authenticated_returns_false_when_authenticated_request_fails(requests_mock: RequestsMock) -> None:
    requests_mock.assert_all_requests_are_fired = False
    requests_mock.add(requests_mock.GET, re.compile(".*"), body='{ "success": false }')
    requests_mock.add(requests_mock.POST, re.compile(".*"), body='{ "success": false }')

    logger = test_get_logger()
    api = APIClient(logger, HTTPClient(logger), "123", "456")

    assert not api.is_authenticated()
