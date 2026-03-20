import os


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.default_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def _extract_text(self, *args, **kwargs) -> str:
        if "content" in kwargs and kwargs["content"] is not None:
            return str(kwargs["content"])
        if "text" in kwargs and kwargs["text"] is not None:
            return str(kwargs["text"])
        if "prompt" in kwargs and kwargs["prompt"] is not None:
            return str(kwargs["prompt"])
        if "messages" in kwargs and kwargs["messages"] is not None:
            messages = kwargs["messages"]
            return " ".join(
                m[1] if isinstance(m, (list, tuple)) and len(m) > 1 else str(m)
                for m in messages
            )
        if args:
            first = args[0]
            if isinstance(first, list):
                return " ".join(
                    m[1] if isinstance(m, (list, tuple)) and len(m) > 1 else str(m)
                    for m in first
                )
            return str(first)
        return ""

    def count_tokens(self, *args, model: str | None = None, **kwargs) -> int:
        text = self._extract_text(*args, **kwargs)
        if not text:
            return 0

        # Đếm local thay vì gọi API countTokens
        # Nhanh hơn rất nhiều, đủ dùng cho chunking
        words = len(text.split())
        chars = len(text)

        approx_by_words = int(words * 1.3)
        approx_by_chars = int(chars / 4)

        return max(1, approx_by_words, approx_by_chars)

    def count_message_tokens(self, messages, model: str | None = None) -> int:
        return self.count_tokens(messages=messages, model=model)

    def invoke(self, prompt: str, model: str | None = None, temperature: float = 0):
        raise NotImplementedError("invoke() không dùng trong ingest local tối ưu này")

    async def ainvoke(self, prompt: str, model: str | None = None, temperature: float = 0):
        raise NotImplementedError("ainvoke() không dùng trong ingest local tối ưu này")


llm_client = LLMClient()