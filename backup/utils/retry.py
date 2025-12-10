"""
Retry logic with exponential backoff and circuit breaker
"""
import asyncio
import time
import logging
from typing import Callable, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker pattern to skip failing sources"""
    
    def __init__(self, failure_threshold: int = 3, timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = {}
        self.last_failure_time = {}
    
    def is_open(self, key: str) -> bool:
        """Check if circuit is open (should skip)"""
        if key not in self.failures:
            return False
        
        failures = self.failures[key]
        last_failure = self.last_failure_time.get(key, 0)
        
        # If too many failures and recent, circuit is open
        if failures >= self.failure_threshold:
            if time.time() - last_failure < self.timeout:
                return True
            else:
                # Reset after timeout
                self.failures[key] = 0
                return False
        
        return False
    
    def record_failure(self, key: str):
        """Record a failure"""
        self.failures[key] = self.failures.get(key, 0) + 1
        self.last_failure_time[key] = time.time()
    
    def record_success(self, key: str):
        """Record a success (reset failures)"""
        self.failures[key] = 0


# Global circuit breaker
_circuit_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    """Get global circuit breaker instance"""
    return _circuit_breaker


async def retry_async(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    circuit_breaker_key: Optional[str] = None
) -> Any:
    """
    Retry async function with exponential backoff
    
    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exceptions to catch and retry
        circuit_breaker_key: Key for circuit breaker (if None, no circuit breaker)
    """
    if circuit_breaker_key:
        breaker = get_circuit_breaker()
        if breaker.is_open(circuit_breaker_key):
            logger.warning(f"Circuit breaker open for {circuit_breaker_key}, skipping")
            raise Exception(f"Circuit breaker open for {circuit_breaker_key}")
    
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            result = await func()
            # Record success if circuit breaker is used
            if circuit_breaker_key:
                get_circuit_breaker().record_success(circuit_breaker_key)
            return result
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}, retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"All {max_retries + 1} attempts failed: {e}")
                # Record failure in circuit breaker
                if circuit_breaker_key:
                    get_circuit_breaker().record_failure(circuit_breaker_key)
                raise
    
    # Should never reach here, but just in case
    if circuit_breaker_key:
        get_circuit_breaker().record_failure(circuit_breaker_key)
    raise last_exception


def retry_sync(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    circuit_breaker_key: Optional[str] = None
) -> Any:
    """
    Retry sync function with exponential backoff
    """
    if circuit_breaker_key:
        breaker = get_circuit_breaker()
        if breaker.is_open(circuit_breaker_key):
            logger.warning(f"Circuit breaker open for {circuit_breaker_key}, skipping")
            raise Exception(f"Circuit breaker open for {circuit_breaker_key}")
    
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            result = func()
            # Record success if circuit breaker is used
            if circuit_breaker_key:
                get_circuit_breaker().record_success(circuit_breaker_key)
            return result
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}, retrying in {delay:.1f}s")
                time.sleep(delay)
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"All {max_retries + 1} attempts failed: {e}")
                # Record failure in circuit breaker
                if circuit_breaker_key:
                    get_circuit_breaker().record_failure(circuit_breaker_key)
                raise
    
    # Should never reach here, but just in case
    if circuit_breaker_key:
        get_circuit_breaker().record_failure(circuit_breaker_key)
    raise last_exception

