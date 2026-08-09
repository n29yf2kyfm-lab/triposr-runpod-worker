import pytest

from app.providers import ebay


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only (no trio dependency)."""
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_ebay_caches():
    """
    The taxonomy caches are process-global by design (Taxonomy is capped at
    5,000 calls/day for the whole application), so tests must reset them or a
    cached result from one test silently answers the next.
    """
    ebay._aspect_cache.clear()
    ebay._tree_id_cache.clear()
    ebay._app_token_cache.clear()
    yield
    ebay._aspect_cache.clear()
    ebay._tree_id_cache.clear()
    ebay._app_token_cache.clear()
