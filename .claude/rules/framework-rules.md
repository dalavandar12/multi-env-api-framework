# Framework Architecture Rules

These constraints define how the framework is structured. Violations break the separation
of concerns that keeps the project maintainable and extensible.

---

## 1. Test Files Must Not Import from Other Test Files

Shared logic — helper functions, shared fixtures, reusable assertions — belongs in `src/`
or `utils/`, not in a test file that other tests then import. If you find yourself writing
`from tests.test_countries import some_helper`, move `some_helper` to `src/` instead.

---

## 2. All Configs in `config/` — No Hardcoded Environment Values in Python

Environment-specific values (base URLs, thresholds, feature flags) live exclusively in
`config/environments.yaml`. Python code reads config through the `env_config` fixture
supplied by `conftest.py`. Never write:

```python
BASE_URL = "https://restcountries.com"  # WRONG
MAX_TIME = 2.0                          # WRONG
```

---

## 3. `--env` Is the Single Entry Point for Environment Selection

The `--env` CLI flag is the only supported mechanism for selecting which environment to
run against. It is registered in `conftest.py:pytest_addoption` and applied in
`conftest.py:pytest_collection_modifyitems`, which deselects tests whose markers do not
match the requested environment. Do not use `-m countries` or `-m weather` as a substitute
— marker expressions are for other filtering needs.

---

## 4. `ApiClient` Must Only Be Instantiated via the `api_client` Fixture

Direct instantiation of `ApiClient` in test code is forbidden:

```python
# WRONG — never do this in a test
client = ApiClient(base_url="https://restcountries.com")

# CORRECT — accept the fixture
def test_something(self, api_client: ApiClient, env_config: dict) -> None: ...
```

The `api_client` fixture in `conftest.py` is the sole factory. This guarantees that each
test gets a clean session with the correct base URL for the active environment.

---

## 5. Adding a New API Domain Requires All Four of These Changes

When onboarding a new REST API (beyond countries and weather), all four of the following
must be added together — a partial addition is considered incomplete and will fail review:

1. **Endpoint methods** — a new module under `src/` (e.g., `src/github_client.py`) with
   typed methods wrapping `ApiClient.get()`
2. **Validators** — new validator functions added to `src/validators.py`
3. **Environment entry** — a new top-level key in `config/environments.yaml` with at
   minimum `base_url` and `max_response_time`
4. **Pytest marker** — a new marker registered in `pytest.ini` under `[pytest] markers`

---

## 6. Retry and Polling Logic via `@poller` — No Manual Sleep Loops

Any test that polls an endpoint or retries on transient failures must use the `@poller`
decorator from `utils/poller.py`. Manual `time.sleep()` loops in test code are forbidden.

```python
from utils.poller import poller

@poller(max_attempts=5, delay=1.0)
def fetch_until_ready(api_client: ApiClient) -> dict: ...
```

---

## 7. CI Is Defined in `.github/workflows/ci.yml`

The authoritative CI definition is `.github/workflows/ci.yml`. It runs the `lint` job
first, then the `test` job (which runs both environments sequentially and uploads Allure
results as the `allure-results` artifact). Do not add parallel workflow files or duplicate
test execution steps outside this file.
