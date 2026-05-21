import logging
from .base import StreamChunk, Provider, DEFAULT_MODEL, DEFAULT_PROVIDER, CONTEXT_WINDOW_TURNS

log = logging.getLogger(__name__)

_registry: dict[str, Provider] = {}


def setup() -> None:
    """Initialize available providers. Called after load_dotenv() in lifespan."""
    from .openai_provider import OpenAIProvider
    try:
        _registry["openai"] = OpenAIProvider()
        log.info("openai provider registered")
    except Exception as e:
        log.warning("openai provider unavailable: %s", e)

    try:
        from .anthropic_provider import AnthropicProvider
        _registry["anthropic"] = AnthropicProvider()
        log.info("anthropic provider registered")
    except ImportError:
        log.debug("anthropic package not installed")
    except Exception as e:
        log.debug("anthropic provider unavailable: %s", e)


def get_provider(name: str) -> Provider:
    p = _registry.get(name)
    if p is None:
        raise ValueError(f"unknown provider: {name!r}. Available: {list(_registry)}")
    return p


def list_providers() -> list[dict]:
    return [{"name": name} for name in _registry]


__all__ = [
    "StreamChunk", "Provider",
    "DEFAULT_MODEL", "DEFAULT_PROVIDER", "CONTEXT_WINDOW_TURNS",
    "setup", "get_provider", "list_providers",
]
