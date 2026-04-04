import logging
import time
from typing import Any, Dict, Tuple

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class RateLimiterDemoPlugin(Plugin):
    """A simple rate limiter plugin that tracks requests per user."""

    def __init__(self, config: PluginConfig):
        """Initialize the rate limiter plugin.
        
        Args:
            config: Plugin configuration containing rate limit settings.
        """
        super().__init__(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Get configuration
        self.max_requests = config.config.get("max_requests", 5)
        self.time_window = config.config.get("time_window", 60)
        self.block_on_limit = config.config.get("block_on_limit", True)
        
        # In-memory storage: {user_email: (count, window_start_time)}
        self._rate_limits: Dict[str, Tuple[int, float]] = {}
        
        self.logger.info(
            f"RateLimiterDemoPlugin initialized: {self.max_requests} requests per {self.time_window}s"
        )

    async def tool_pre_invoke(
        self, 
        payload: ToolPreInvokePayload, 
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Check rate limit before tool invocation.
        
        Args:
            payload: The tool invocation payload.
            context: Plugin execution context with user information.
            
        Returns:
            ToolPreInvokeResult indicating whether to allow or block the request.
        """
        # Get user email from context
        user_email = context.global_context.user or "anonymous"
        current_time = time.time()
        
        # Check if user has existing rate limit entry
        if user_email in self._rate_limits:
            count, window_start = self._rate_limits[user_email]
            
            # Check if we're still in the same time window
            if current_time - window_start < self.time_window:
                # Still in the same window
                if count >= self.max_requests:
                    # Rate limit exceeded
                    time_remaining = int(self.time_window - (current_time - window_start))
                    
                    violation_msg = (
                        f"Rate limit exceeded: {count}/{self.max_requests} requests. "
                        f"Try again in {time_remaining} seconds."
                    )
                    
                    self.logger.warning(f"Rate limit exceeded for user {user_email}")
                    
                    if self.block_on_limit:
                        return ToolPreInvokeResult(
                            continue_processing=False,
                            violation=PluginViolation(
                                reason="Rate limit exceeded",
                                description=violation_msg,
                                code="RATE_LIMIT_EXCEEDED",
                                details={
                                    "user": user_email,
                                    "current_count": count,
                                    "max_requests": self.max_requests,
                                    "time_window": self.time_window,
                                    "retry_after": time_remaining,
                                },
                                http_status_code=429,
                                http_headers={
                                    "X-RateLimit-Limit": str(self.max_requests),
                                    "X-RateLimit-Remaining": "0",
                                    "X-RateLimit-Reset": str(int(window_start + self.time_window)),
                                    "Retry-After": str(time_remaining),
                                },
                            ),
                        )
                    else:
                        # Permissive mode - log but allow
                        return ToolPreInvokeResult(
                            metadata={
                                "rate_limit_warning": violation_msg,
                                "current_count": count,
                                "max_requests": self.max_requests,
                            }
                        )
                else:
                    # Increment counter
                    self._rate_limits[user_email] = (count + 1, window_start)
                    remaining = self.max_requests - (count + 1)
                    
                    self.logger.debug(
                        f"Request {count + 1}/{self.max_requests} for user {user_email}"
                    )
                    
                    return ToolPreInvokeResult(
                        metadata={
                            "rate_limit_status": "ok",
                            "current_count": count + 1,
                            "max_requests": self.max_requests,
                            "remaining": remaining,
                        },
                        http_headers={
                            "X-RateLimit-Limit": str(self.max_requests),
                            "X-RateLimit-Remaining": str(remaining),
                            "X-RateLimit-Reset": str(int(window_start + self.time_window)),
                        },
                    )
            else:
                # Time window expired, start new window
                self._rate_limits[user_email] = (1, current_time)
                self.logger.debug(f"New rate limit window started for user {user_email}")
                
                return ToolPreInvokeResult(
                    metadata={
                        "rate_limit_status": "ok",
                        "current_count": 1,
                        "max_requests": self.max_requests,
                        "remaining": self.max_requests - 1,
                    },
                    http_headers={
                        "X-RateLimit-Limit": str(self.max_requests),
                        "X-RateLimit-Remaining": str(self.max_requests - 1),
                        "X-RateLimit-Reset": str(int(current_time + self.time_window)),
                    },
                )
        else:
            # First request from this user
            self._rate_limits[user_email] = (1, current_time)
            self.logger.debug(f"First request from user {user_email}")
            
            return ToolPreInvokeResult(
                metadata={
                    "rate_limit_status": "ok",
                    "current_count": 1,
                    "max_requests": self.max_requests,
                    "remaining": self.max_requests - 1,
                },
                http_headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": str(self.max_requests - 1),
                    "X-RateLimit-Reset": str(int(current_time + self.time_window)),
                },
            )
