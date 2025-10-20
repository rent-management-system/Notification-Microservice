import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def async_retry(tries=3, delay=1, backoff=2, exceptions=(Exception,)):
    def deco(func):
        @wraps(func)
        async def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    logger.warning(f"Exception: {e}, Retrying in {mdelay} seconds...")
                    await asyncio.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return await func(*args, **kwargs) # Last attempt
        return f_retry
    return deco
