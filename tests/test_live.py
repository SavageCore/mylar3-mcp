"""Integration tests against a real Mylar3 instance.

Skipped unless MYLAR_URL and MYLAR_API_KEY are set. Run with:
    uv run pytest -m integration

These tests only read data, plus one reversible write test (pause/resume) that
uses the series ID from MYLAR_TEST_COMIC_ID and never snatches, deletes, or
modifies your library.
"""

import os

import pytest
from fastmcp import Client

import mylar_mcp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("MYLAR_URL") and os.environ.get("MYLAR_API_KEY")),
        reason="requires MYLAR_URL and MYLAR_API_KEY",
    ),
]


@pytest.fixture(autouse=True)
def configure_client():
    mylar_mcp._client = mylar_mcp.build_client(
        os.environ["MYLAR_URL"], os.environ["MYLAR_API_KEY"], os.environ.get("MYLAR_HTTP_ROOT", "/")
    )
    mylar_mcp._API_KEY = os.environ["MYLAR_API_KEY"]
    mylar_mcp._HTTP_ROOT = os.environ.get("MYLAR_HTTP_ROOT", "/")
    yield


async def call(name, **kwargs):
    async with Client(mylar_mcp.mcp) as c:
        return await c.call_tool(name, kwargs)


async def test_get_index_returns_list():
    result = await call("mylar_get_index")
    assert isinstance(result.data, list)


async def test_get_version_has_current_version():
    result = await call("mylar_get_version")
    assert isinstance(result.data, dict)
    assert "current_version" in result.data


async def test_list_providers_has_keys():
    result = await call("mylar_list_providers")
    assert isinstance(result.data, dict)
    assert "newznabs" in result.data
    assert "torznabs" in result.data


async def test_get_logs_returns_list():
    result = await call("mylar_get_logs")
    assert isinstance(result.data, list)


async def test_pause_resume_roundtrip():
    comic_id = os.environ.get("MYLAR_TEST_COMIC_ID")
    if not comic_id:
        pytest.skip("set MYLAR_TEST_COMIC_ID to run the pause/resume roundtrip")
    await call("mylar_pause_comic", id=comic_id)
    try:
        info = await call("mylar_get_comic_info", id=comic_id)
        assert info.data["Status"] == "Paused"
    finally:
        await call("mylar_resume_comic", id=comic_id)
    info = await call("mylar_get_comic_info", id=comic_id)
    assert info.data["Status"] == "Active"
