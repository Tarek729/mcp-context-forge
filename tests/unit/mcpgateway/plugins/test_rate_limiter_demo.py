import pytest
import time
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    GlobalContext,
    ToolPreInvokePayload,
)
from plugins.rate_limiter_demo.rate_limiter import RateLimiterDemoPlugin


@pytest.fixture
def plugin_config():
    """Create a plugin configuration for testing."""
    return PluginConfig(
        name="RateLimiterDemo",
        kind="plugins.rate_limiter_demo.rate_limiter.RateLimiterDemoPlugin",
        hooks=["tool_pre_invoke"],
        mode="enforce",
        priority=50,
        config={
            "max_requests": 5,
            "time_window": 60,
            "block_on_limit": True,
        },
    )


@pytest.fixture
def plugin(plugin_config):
    """Create a plugin instance for testing."""
    return RateLimiterDemoPlugin(plugin_config)


@pytest.fixture
def context():
    """Create a plugin context for testing."""
    global_ctx = GlobalContext(
        request_id="test-request-123",
        user="test@example.com",
        tenant_id="test-tenant",
    )
    return PluginContext(global_context=global_ctx)


@pytest.fixture
def payload():
    """Create a tool pre-invoke payload for testing."""
    return ToolPreInvokePayload(
        name="test_tool",
        args={"arg1": "value1"},
    )


def test_plugin_initialization(plugin):
    """Test that the plugin initializes correctly."""
    assert plugin.max_requests == 5
    assert plugin.time_window == 60
    assert plugin.block_on_limit is True
    assert plugin._rate_limits == {}


@pytest.mark.asyncio
async def test_first_request_allowed(plugin, payload, context):
    """Test that the first request is allowed."""
    result = await plugin.tool_pre_invoke(payload, context)
    
    assert result.continue_processing is True
    assert result.violation is None
    assert result.metadata["rate_limit_status"] == "ok"
    assert result.metadata["current_count"] == 1
    assert result.metadata["remaining"] == 4


@pytest.mark.asyncio
async def test_requests_within_limit(plugin, payload, context):
    """Test that requests within the limit are allowed."""
    # Make 5 requests (the limit)
    for i in range(5):
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.metadata["current_count"] == i + 1


@pytest.mark.asyncio
async def test_request_over_limit_blocked(plugin, payload, context):
    """Test that requests over the limit are blocked."""
    # Make 5 requests (the limit)
    for _ in range(5):
        await plugin.tool_pre_invoke(payload, context)
    
    # 6th request should be blocked
    result = await plugin.tool_pre_invoke(payload, context)
    
    assert result.continue_processing is False
    assert result.violation is not None
    assert result.violation.code == "RATE_LIMIT_EXCEEDED"
    assert result.violation.http_status_code == 429
    assert "Retry-After" in result.violation.http_headers


@pytest.mark.asyncio
async def test_rate_limit_resets_after_time_window(plugin, payload, context):
    """Test that rate limit resets after the time window expires."""
    # Create a plugin with a short time window for testing
    config = PluginConfig(
        name="RateLimiterDemo",
        kind="plugins.rate_limiter_demo.rate_limiter.RateLimiterDemoPlugin",
        hooks=["tool_pre_invoke"],
        mode="enforce",
        priority=50,
        config={
            "max_requests": 2,
            "time_window": 1,  # 1 second window
            "block_on_limit": True,
        },
    )
    short_window_plugin = RateLimiterDemoPlugin(config)
    
    # Make 2 requests (the limit)
    for _ in range(2):
        result = await short_window_plugin.tool_pre_invoke(payload, context)
        assert result.continue_processing is True
    
    # 3rd request should be blocked
    result = await short_window_plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is False
    
    # Wait for time window to expire
    time.sleep(1.1)
    
    # Request should be allowed again
    result = await short_window_plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True
    assert result.metadata["current_count"] == 1


@pytest.mark.asyncio
async def test_different_users_tracked_separately(plugin, payload):
    """Test that different users have separate rate limits."""
    # User 1
    context1 = PluginContext(
        global_context=GlobalContext(
            request_id="test-request-user1",
            user="user1@example.com",
            tenant_id="test"
        )
    )
    
    # User 2
    context2 = PluginContext(
        global_context=GlobalContext(
            request_id="test-request-user2",
            user="user2@example.com",
            tenant_id="test"
        )
    )
    
    # Make 5 requests for user1
    for _ in range(5):
        result = await plugin.tool_pre_invoke(payload, context1)
        assert result.continue_processing is True
    
    # User1's 6th request should be blocked
    result = await plugin.tool_pre_invoke(payload, context1)
    assert result.continue_processing is False
    
    # User2's first request should still be allowed
    result = await plugin.tool_pre_invoke(payload, context2)
    assert result.continue_processing is True
    assert result.metadata["current_count"] == 1


@pytest.mark.asyncio
async def test_permissive_mode(payload, context):
    """Test that permissive mode logs but doesn't block."""
    config = PluginConfig(
        name="RateLimiterDemo",
        kind="plugins.rate_limiter_demo.rate_limiter.RateLimiterDemoPlugin",
        hooks=["tool_pre_invoke"],
        mode="permissive",
        priority=50,
        config={
            "max_requests": 2,
            "time_window": 60,
            "block_on_limit": False,  # Permissive mode
        },
    )
    permissive_plugin = RateLimiterDemoPlugin(config)
    
    # Make 3 requests (over the limit of 2)
    for _ in range(3):
        result = await permissive_plugin.tool_pre_invoke(payload, context)
        # All requests should be allowed in permissive mode
        assert result.continue_processing is True
        assert result.violation is None


@pytest.mark.asyncio
async def test_rate_limit_headers(plugin, payload, context):
    """Test that rate limit headers are included in responses."""
    result = await plugin.tool_pre_invoke(payload, context)
    
    assert "X-RateLimit-Limit" in result.http_headers
    assert "X-RateLimit-Remaining" in result.http_headers
    assert "X-RateLimit-Reset" in result.http_headers
    
    assert result.http_headers["X-RateLimit-Limit"] == "5"
    assert result.http_headers["X-RateLimit-Remaining"] == "4"
