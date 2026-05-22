"""
Top-level pytest configuration.

  - pytest_addoption registers the --env CLI flag
  - pytest_collection_modifyitems filters tests to the selected environment
  - Session-scoped fixture loads environments.yaml once per run
  - Per-test env_config and api_client fixtures inject the right config
"""
import logging
from pathlib import Path
from typing import Any, Generator, cast

import allure
import pytest
import yaml

from src.client import ApiClient

LOG = logging.getLogger(__name__)

_ENV_NAMES = ("countries", "weather")
_CROSS_ENV_MARKER = "cross-env"
_ENV_CHOICES = _ENV_NAMES + (_CROSS_ENV_MARKER,)
_CONFIG_PATH = Path(__file__).parent / "config" / "environments.yaml"


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--env",
        action="store",
        default=None,
        choices=list(_ENV_CHOICES),
        help=(
            "Target environment to run. "
            "Choices: countries, weather, cross-env. "
            "Omit to run all."
        ),
    )


# ---------------------------------------------------------------------------
# Collection filtering
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Deselect tests that don't belong to the selected --env."""
    selected_env = config.getoption("--env")
    if selected_env is None:
        return

    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        markers = {m.name for m in item.iter_markers()}
        has_cross_env = _CROSS_ENV_MARKER in markers

        if selected_env == _CROSS_ENV_MARKER:
            if has_cross_env:
                kept.append(item)
            else:
                deselected.append(item)
            continue

        if has_cross_env:
            deselected.append(item)
            continue

        item_envs = {m.name for m in item.iter_markers() if m.name in _ENV_NAMES}
        if item_envs and selected_env not in item_envs:
            deselected.append(item)
        else:
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Attach a consistent Allure parent suite per active environment marker."""
    dynamic: Any = allure.dynamic
    if item.get_closest_marker("countries"):
        dynamic.parent_suite("Countries Environment")
    elif item.get_closest_marker("weather"):
        dynamic.parent_suite("Weather Environment")
    elif item.get_closest_marker(_CROSS_ENV_MARKER):
        dynamic.parent_suite("Cross-Environment Workflows")


# ---------------------------------------------------------------------------
# Session-scoped environment config loader
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def all_env_configs() -> dict[str, Any]:
    """Load environments.yaml once for the entire test session."""
    LOG.info("Loading environment configs from %s", _CONFIG_PATH)
    with open(_CONFIG_PATH) as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return cast(dict[str, Any], data["environments"])


# ---------------------------------------------------------------------------
# Per-test fixtures — inject correct env based on marker
# ---------------------------------------------------------------------------


@pytest.fixture
def env_config(request: pytest.FixtureRequest, all_env_configs: dict[str, Any]) -> dict[str, Any]:
    """
    Return the environment config dict for the test's environment marker.

    Tests must carry @pytest.mark.countries or @pytest.mark.weather.
    Config keys: base_url, max_response_time, min_results_count.
    """
    for env_name in _ENV_NAMES:
        if request.node.get_closest_marker(env_name):
            cfg: dict[str, Any] = all_env_configs[env_name]
            LOG.info(
                "env_config → %s (base_url=%s, max_response_time=%s, "
                "min_results_count=%s, extras=%s)",
                env_name,
                cfg["base_url"],
                cfg.get("max_response_time"),
                cfg.get("min_results_count"),
                {
                    k: cfg[k]
                    for k in (
                        "region_min_country_count",
                        "temperature_min_c",
                        "temperature_max_c",
                    )
                    if k in cfg
                },
            )
            return cfg
    pytest.skip("No environment marker (@pytest.mark.countries / @pytest.mark.weather) found")


@pytest.fixture
def api_client(env_config: dict[str, Any]) -> Generator[ApiClient, None, None]:
    """
    Provide a configured ApiClient for the test's environment.

    max_response_time is read from environments.yaml — never hardcoded in tests.
    """
    client = ApiClient(
        base_url=env_config["base_url"],
        max_response_time=env_config["max_response_time"],
    )
    yield client
    client._session.close()


@pytest.fixture
def countries_env_config(all_env_configs: dict[str, Any]) -> dict[str, Any]:
    """Direct access to countries environment config for cross-env tests."""
    cfg: dict[str, Any] = all_env_configs["countries"]
    return cfg


@pytest.fixture
def weather_env_config(all_env_configs: dict[str, Any]) -> dict[str, Any]:
    """Direct access to weather environment config for cross-env tests."""
    cfg: dict[str, Any] = all_env_configs["weather"]
    return cfg


@pytest.fixture
def countries_api_client(countries_env_config: dict[str, Any]) -> Generator[ApiClient, None, None]:
    """Dedicated countries client for cross-environment workflow tests."""
    client = ApiClient(
        base_url=countries_env_config["base_url"],
        max_response_time=countries_env_config["max_response_time"],
    )
    yield client
    client._session.close()


@pytest.fixture
def weather_api_client(weather_env_config: dict[str, Any]) -> Generator[ApiClient, None, None]:
    """Dedicated weather client for cross-environment workflow tests."""
    client = ApiClient(
        base_url=weather_env_config["base_url"],
        max_response_time=weather_env_config["max_response_time"],
    )
    yield client
    client._session.close()
