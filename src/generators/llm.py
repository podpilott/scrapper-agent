"""LLM client for text generation."""

from typing import Literal

from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("llm")

# DeepSeek API base URL (OpenAI-compatible)
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


class LLMClient:
    """Unified client for LLM API calls (OpenAI, Anthropic, DeepSeek)."""

    def __init__(
        self,
        provider: Literal["openai", "anthropic", "deepseek"] | None = None,
        model: str | None = None,
    ):
        """Initialize the LLM client.

        Args:
            provider: LLM provider ("openai", "anthropic", or "deepseek"). Defaults to settings.
            model: Model name. Defaults to settings or provider-specific default.
        """
        self.provider = provider or settings.llm_provider
        self.model = model or self._get_default_model()

        # Initialize the appropriate client
        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "deepseek":
            self._init_deepseek()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        logger.info("llm_client_initialized", provider=self.provider, model=self.model)

    def _get_default_model(self) -> str:
        """Get default model for the provider."""
        if settings.llm_model:
            return settings.llm_model

        defaults = {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "deepseek": "deepseek-chat",
        }
        return defaults.get(self.provider, "gpt-4o-mini")

    def _init_openai(self) -> None:
        """Initialize OpenAI client."""
        from openai import OpenAI

        api_key = settings.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.client = OpenAI(api_key=api_key.get_secret_value())

    def _init_anthropic(self) -> None:
        """Initialize Anthropic client."""
        from anthropic import Anthropic

        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = Anthropic(api_key=api_key.get_secret_value())

    def _init_deepseek(self) -> None:
        """Initialize DeepSeek client (uses OpenAI-compatible API)."""
        from openai import OpenAI

        api_key = settings.deepseek_api_key
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        self.client = OpenAI(
            api_key=api_key.get_secret_value(),
            base_url=DEEPSEEK_BASE_URL,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def generate(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> str:
        """Generate text from a prompt.

        Args:
            prompt: The prompt to send to the LLM.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            Generated text.
        """
        if self.provider == "anthropic":
            return self._generate_anthropic(prompt, max_tokens, temperature)
        else:
            # OpenAI and DeepSeek use the same API format
            return self._generate_openai_compatible(prompt, max_tokens, temperature)

    def _generate_openai_compatible(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate with OpenAI-compatible API (OpenAI, DeepSeek)."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return response.choices[0].message.content.strip()

    def _generate_anthropic(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate with Anthropic API."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text.strip()

    def generate_batch(
        self,
        prompts: list[str],
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> list[str]:
        """Generate text for multiple prompts.

        Args:
            prompts: List of prompts.
            max_tokens: Maximum tokens per response.
            temperature: Sampling temperature.

        Returns:
            List of generated texts.
        """
        results = []
        for prompt in prompts:
            try:
                result = self.generate(prompt, max_tokens, temperature)
                results.append(result)
            except Exception as e:
                logger.error("generation_failed", error=str(e))
                results.append("")

        return results
