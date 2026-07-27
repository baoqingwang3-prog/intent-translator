"""Local-first intent compiler MCP package."""

from .version import __version__
from .core import IntentCompiler
from .sdk import CompilationResult, IntentTranslator, IntentTranslatorSDK

__all__ = [
    "CompilationResult",
    "IntentCompiler",
    "IntentTranslator",
    "IntentTranslatorSDK",
    "__version__",
]
