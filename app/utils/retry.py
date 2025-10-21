import asyncio
import structlog
from functools import wraps
from datetime import datetime, timedelta

logger = structlog.get_logger()

class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED"

    def _open(self):
        self.state = "OPEN"
        self.last_failure_time = datetime.utcnow()
        logger.warning("Circuit Breaker OPEN", event="circuit_breaker_state_change", state=self.state, service="SES")

    def _half_open(self):
        self.state = "HALF_OPEN"
        logger.info("Circuit Breaker HALF-OPEN", event="circuit_breaker_state_change", state=self.state, service="SES")

    def _close(self):
        self.state = "CLOSED"
        self.failures = 0
        self.last_failure_time = None
        logger.info("Circuit Breaker CLOSED", event="circuit_breaker_state_change", state=self.state, service="SES")

    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if (datetime.utcnow() - self.last_failure_time).total_seconds() > self.reset_timeout:
                    self._half_open()
                else:
                    logger.warning("Circuit Breaker OPEN, blocking call", event="circuit_breaker_blocked", service="SES")
                    raise CircuitBreakerOpenException("Circuit breaker is open")

            try:
                result = await func(*args, **kwargs)
                if self.state == "HALF_OPEN":
                    self._close()
                return result
            except Exception as e:
                self.failures += 1
                self.last_failure_time = datetime.utcnow()
                logger.warning("Circuit Breaker failure recorded", event="circuit_breaker_failure", failures=self.failures, state=self.state, service="SES")
                if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
                    self._open()
                raise e
        return wrapper

class CircuitBreakerOpenException(Exception):
    pass

def async_retry(tries=3, delay=1, backoff=2, exceptions=(Exception,), circuit_breaker: CircuitBreaker = None):
    def deco(func):
        @wraps(func)
        async def f_retry(*args, **kwargs):
            if circuit_breaker and circuit_breaker.state == "OPEN":
                if (datetime.utcnow() - circuit_breaker.last_failure_time).total_seconds() > circuit_breaker.reset_timeout:
                    circuit_breaker._half_open()
                else:
                    logger.warning("Circuit Breaker OPEN, blocking retry attempt", event="circuit_breaker_blocked_retry", service="SES")
                    raise CircuitBreakerOpenException("Circuit breaker is open, blocking retry")

            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    if circuit_breaker:
                        return await circuit_breaker(func)(*args, **kwargs)
                    else:
                        return await func(*args, **kwargs)
                except exceptions as e:
                    logger.warning("Exception during retry", event="retry_exception", error=str(e), delay=mdelay, error_type=type(e).__name__, service="SES")
                    await asyncio.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
                except CircuitBreakerOpenException:
                    raise # Re-raise if circuit breaker opens during a retry loop
            
            if circuit_breaker:
                return await circuit_breaker(func)(*args, **kwargs)
            else:
                return await func(*args, **kwargs) # Last attempt
        return f_retry
    return deco
