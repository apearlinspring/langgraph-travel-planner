"""
Pytest defaults for layered test execution.
"""
import os

import pytest


TEST_ENV_DEFAULTS = {
    "APP_ENV": "test",
    "DASHSCOPE_API_KEY": "test-key-dashscope",
    "LANGSMITH_API_KEY": "test-key-langsmith",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
    "POSTGRES_DB": "test_db",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_password",
}


for key, value in TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("travel-planner-test-layers")
    group.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Include integration tests that talk to real external services or heavy workflows.",
    )
    group.addoption(
        "--integration-only",
        action="store_true",
        default=False,
        help="Run only integration tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    run_integration = config.getoption("--run-integration")
    integration_only = config.getoption("--integration-only")
    if run_integration and integration_only:
        raise pytest.UsageError(
            "Use either --run-integration or --integration-only, not both."
        )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_integration = config.getoption("--run-integration")
    integration_only = config.getoption("--integration-only")

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    for item in items:
        is_integration = item.get_closest_marker("integration") is not None
        if not is_integration:
            item.add_marker(pytest.mark.unit)

        if integration_only:
            if is_integration:
                selected.append(item)
            else:
                deselected.append(item)
            continue

        if not run_integration and is_integration:
            deselected.append(item)
            continue

        selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
