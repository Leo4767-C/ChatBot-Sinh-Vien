# Gọi OpenAI hoặc local embedding model
import logging
import uuid

from FlagEmbedding import BGEM3FlagModel

from google import genai
from google.genai import types
from dotenv import load_dotenv

from app.core.config import settings
from app.schemas.enums import BotLanguage
from app.schemas.llm import GeminiResponse
import json
import re

# Load biến môi trường từ .env
load_dotenv()
logger = logging.getLogger(__name__)

# Khởi tạo client
client = genai.Client(api_key=settings.EFFECTIVE_GEMINI_API_KEY)
embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)


def get_embeddings(texts: list[str]):
    output = embedder.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=True
    )
    return output['dense_vecs'], output['lexical_weights'], output['colbert_vecs']


async def generate_answer(retrieved_context: list[str], system_prompt: str, model="gpt-3.5-turbo", temperature=0.3,
                          question: str = "", chat_histories: list[dict] = None, language: BotLanguage = BotLanguage.VIE):
    """
    Gọi Gemini API để sinh câu trả lời từ một prompt, lịch sử hội thoại và ngữ cảnh (context).
    """
    logger.info("========== CONTEXT =======")
    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")
        logger.info(f"Context {i}: {context.strip()}")
    formatted_context = "\n\n".join(context_blocks)

    full_prompt = system_prompt.replace("{{context}}", formatted_context).replace("{{language}}", language.label()).replace("{{question}}", question)

    if chat_histories:
        contents = chat_histories + [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]
    else:
        contents = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=full_prompt,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=temperature,
            max_output_tokens=1000
        )
    )

    response_text = re.sub(r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.MULTILINE).strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        logger.error("Error when parsing response")
        return {"content": response_text, "code": 0}


sys_prompt = """
# ROLE & MAIN TASK\n
Bạn là một AI Bot thông minh, đáng tin cậy. Nhiệm vụ của bạn là: tuân thủ các quy tắc dưới đây, dựa trên các đoạn ngữ cảnh được cung cấp bên dưới và những kiến thức mà bạn có \nđể trả lời câu hỏi mà người dùng đặt ra một cách tự nhiên và mạch lạc.\n\n
# PROVIDED CONTEXT\n
```{{contexts}}```\n\n
# USER QUESTION\n
```{{user_question}}```
"""


async def generate_answer_v2(retrieved_context: list[str], system_prompt: str, model="gpt-3.5-turbo", temperature=0.3,
                          question: str = "", chat_histories: list[dict] = None, language: BotLanguage = BotLanguage.VIE) -> GeminiResponse:
    logger.info("========== CONTEXT =======")
    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")
        logger.info(f"Context {i}: {context.strip()}")
    formatted_context = "\n".join(context_blocks)

    full_prompt = sys_prompt.replace("{{contexts}}", formatted_context).replace("{{language}}", language.label()).replace("{{user_question}}", question)

    if chat_histories:
        contents = chat_histories + [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]
    else:
        contents = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=full_prompt,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=temperature,
            max_output_tokens=1500,
            response_mime_type="application/json",
            response_schema=GeminiResponse.model_json_schema()
        )
    )

    result = GeminiResponse.model_validate_json(response.text)
    return result


async def generate_answer_streaming(
        retrieved_context: list[str],
        system_prompt: str,
        conversation_uid: str | uuid.UUID,
        model="gpt-3.5-turbo",
        temperature=0.3,
        question: str = "",
        chat_histories: list[dict] = None,
        language: BotLanguage = BotLanguage.VIE
):
    """
    Sinh câu trả lời dạng stream.
    """
    from app.worker.tasks import save_dialogue  # import lazy để tránh circular import

    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")
    formatted_context = "\n\n".join(context_blocks)

    full_prompt = (system_prompt.replace("{{context}}", formatted_context)
                   .replace("{{language}}", language.label())
                   .replace("{{question}}", question))

    if chat_histories:
        contents = chat_histories + [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]
    else:
        contents = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )]

    try:
        stream = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=full_prompt,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                temperature=temperature,
                max_output_tokens=1000
            )
        )

        buffer = ""
        for chunk in stream:
            delta = chunk.text or ""
            if delta:
                buffer += delta
                yield delta

        if buffer.strip():
            save_dialogue.delay(conversation_uid, question, buffer)

    except Exception as e:
        logger.exception("Streaming error")
        yield f"event:error\ndata:{str(e)}\n\n"