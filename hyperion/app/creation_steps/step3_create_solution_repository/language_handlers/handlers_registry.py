"""Language handlers registry for solution repository creation."""

from typing import Dict, Type, Optional, List
import logging

from .base_handler import BaseLanguageHandler
from .python_handler import PythonHandler
from ..exceptions import LanguageHandlerException

logger = logging.getLogger(__name__)


class LanguageHandlerRegistry:
    """Registry for managing language-specific handlers."""

    def __init__(self) -> None:
        """Initialize the language handler registry."""
        self._handlers: Dict[str, Type[BaseLanguageHandler]] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default language handlers."""
        self.register_handler("PYTHON", PythonHandler)

    def register_handler(
        self, language: str, handler_class: Type[BaseLanguageHandler]
    ) -> None:
        """Register a language handler.

        Args:
            language: Programming language name (e.g., 'JAVA', 'PYTHON')
            handler_class: Handler class for the language
        """
        if not issubclass(handler_class, BaseLanguageHandler):
            raise LanguageHandlerException(
                f"Handler class must inherit from BaseLanguageHandler",
                language=language,
            )

        self._handlers[language.upper()] = handler_class
        logger.info(f"Registered handler for language: {language}")

    def get_handler(self, language: str) -> BaseLanguageHandler:
        """Get a language handler instance.

        Args:
            language: Programming language name

        Returns:
            Language handler instance

        Raises:
            LanguageHandlerException: If handler not found for language
        """
        language_upper = language.upper()

        if language_upper not in self._handlers:
            raise LanguageHandlerException(
                f"No handler registered for language: {language}",
                language=language,
                details={"available_languages": list(self._handlers.keys())},
            )

        handler_class = self._handlers[language_upper]
        return handler_class()

    def is_supported(self, language: str) -> bool:
        """Check if a language is supported.

        Args:
            language: Programming language name

        Returns:
            True if language is supported, False otherwise
        """
        return language.upper() in self._handlers

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages.

        Returns:
            List of supported programming languages
        """
        return list(self._handlers.keys())

    def unregister_handler(self, language: str) -> None:
        """Unregister a language handler.

        Args:
            language: Programming language name
        """
        language_upper = language.upper()
        if language_upper in self._handlers:
            del self._handlers[language_upper]
            logger.info(f"Unregistered handler for language: {language}")

    def get_handler_info(self, language: str) -> Optional[Dict[str, str]]:
        """Get information about a language handler.

        Args:
            language: Programming language name

        Returns:
            Dictionary with handler information or None if not found
        """
        if not self.is_supported(language):
            return None

        handler = self.get_handler(language)
        return {
            "language": language,
            "file_extension": handler.get_file_extension(),
            "test_framework": handler.get_test_framework(),
            "dependency_manager": handler.get_dependency_manager_file() or "None",
        }

    def get_all_handlers_info(self) -> Dict[str, Dict[str, str]]:
        """Get information about all registered handlers.

        Returns:
            Dictionary mapping languages to their handler information
        """
        info = {}
        for language in self.get_supported_languages():
            handler_info = self.get_handler_info(language)
            if handler_info:
                info[language] = handler_info
        return info


registry = LanguageHandlerRegistry()
