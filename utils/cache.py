import functools
import hashlib
import inspect
import os
import pickle

from aiocache import Cache
from aiocache.decorators import cached
from aiocache.serializers import PickleSerializer


def default_key_builder(func, *args, **kwargs):
    module = func.__module__
    qualname = func.__qualname__
    func_name = f"{module}.{qualname}"

    try:
        if inspect.ismethod(func):
            args = args[1:]
        args_serialized = pickle.dumps(args)
        kwargs_serialized = pickle.dumps(kwargs)
    except pickle.PicklingError:
        args_serialized = str(args).encode()
        kwargs_serialized = str(kwargs).encode()

    args_hash = hashlib.sha256(args_serialized).hexdigest()
    kwargs_hash = hashlib.sha256(kwargs_serialized).hexdigest()

    key = f"{func_name}:{args_hash}:{kwargs_hash}"
    return key


cache = Cache.REDIS(
    namespace="main",
    endpoint=os.getenv("REDIS_HOST", "keto_redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    serializer=PickleSerializer(),
)


def cached_decorator(ttl=60, key_builder=default_key_builder, namespace=None):
    def wrapper(func):
        cog_name = (
            func.__qualname__.split(".")[0] if "." in func.__qualname__ else "global"
        )
        cache_namespace = f"{cog_name}---{namespace or func.__name__}"

        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            key = key_builder(func, *args, **kwargs)

            namespaced_cache = Cache.REDIS(
                namespace=cache_namespace,
                endpoint=os.getenv("REDIS_HOST", "keto_redis"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD"),
                serializer=PickleSerializer(),
            )

            result = await namespaced_cache.get(key)
            if result is not None:
                return result

            result = await func(*args, **kwargs)

            await namespaced_cache.set(key, result, ttl=ttl)
            return result

        for attr in dir(func):
            if not attr.startswith("__"):
                setattr(wrapped, attr, getattr(func, attr))

        return wrapped

    return wrapper
