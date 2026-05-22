# Code Style Rules

These rules govern all Python source and test code in this framework.

---

## 1. Validators Live in `src/validators.py`

Never write assertion or schema-check logic inline in test files. All response validation
functions belong in `src/validators.py`. Test files call these functions; they do not
reimplement them.

```python
# src/validators.py  — correct home for this logic
def validate_country_schema(data: dict) -> None:
    assert "name" in data
    assert "population" in data
    ...

# tests/countries/test_countries.py  — test calls the validator
from src.validators import validate_country_schema
validate_country_schema(response.json()[0])
```

---

## 2. All HTTP Logic in `src/client.py`

Test files interact with the network exclusively through the `ApiClient` class defined in
`src/client.py`. Calls in tests must look like:

```python
response = api_client.get("/v3.1/name/france")
response = api_client.get("/v1/forecast", params={"latitude": 48.85, "longitude": 2.35})
```

Do not import `requests` directly in test files, and do not construct URLs manually in
tests. All session management, base URL prepending, default headers, and timeout handling
are encapsulated in `ApiClient`.

---

## 3. Environment Config Belongs in `config/environments.yaml`

Base URLs, timeouts, response-time thresholds, and any other environment-specific values
must live in `config/environments.yaml`. Never put these values in Python source files,
test files, or as default argument values.

```yaml
# config/environments.yaml  — the single source of truth
countries:
  base_url: https://restcountries.com
  max_response_time: 2.0

weather:
  base_url: https://api.open-meteo.com
  max_response_time: 3.0
```

---

## 4. Type Hints on All Functions and Methods

mypy strict mode is enforced via `setup.cfg`. Every function and method signature must
include complete type annotations, including return types.

```python
# CORRECT
def validate_country_schema(data: dict[str, object]) -> None: ...

def get(self, path: str, params: dict[str, object] | None = None) -> requests.Response: ...

# WRONG — missing annotations
def validate_country_schema(data): ...
```

---

## 5. Import Order

Follow this three-block order, with a blank line separating each block:

```python
# Block 1 — stdlib
import json
import logging
import pathlib
from typing import Any

# Block 2 — third-party
import allure
import pytest
import pytest_check as check
import requests

# Block 3 — project
from src.client import ApiClient
from src.validators import validate_country_schema
from utils.poller import poller
```

isort with `known_third_party = allure,pytest,pytest_check,requests` and
`known_first_party = src,utils` enforces this automatically if configured.

---

## 6. Max Line Length: 100

flake8 is configured in `setup.cfg` with `max-line-length = 100`. All lines must stay at or
under 100 characters. Use implicit string concatenation or backslash continuation for long
strings; use parentheses for long function calls.

---

## 7. Logging — No `print()`

Use the module-level logger pattern everywhere in source and test code:

```python
import logging

LOG = logging.getLogger(__name__)

LOG.info("Fetching country data for %s", country_name)
LOG.debug("Response status: %s", response.status_code)
```

Never use `print()` in `src/`, `utils/`, `tests/`, or `conftest.py`. The `print()` builtin
is reserved for scripts explicitly intended for human-readable stdout output, none of which
exist in this framework.

---

## 8. `ApiClient` Is Not a Singleton

A fresh `ApiClient` instance is created for every test via the `api_client` fixture defined
in `conftest.py`. Do not store `ApiClient` at module level, do not share a single instance
across tests, and do not instantiate `ApiClient` directly in test code.

```python
# conftest.py — the fixture provides a clean instance per test
@pytest.fixture
def api_client(env_config: dict[str, object]) -> ApiClient:
    return ApiClient(base_url=str(env_config["base_url"]))
```
