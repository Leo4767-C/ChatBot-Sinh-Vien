# ================== IMPORT ==================
import logging
import uuid
import json
import re

from FlagEmbedding import BGEM3FlagModel
import google.generativeai as genai
from dotenv import load_dotenv

from app.core.config import settings
from app.schemas.enums import BotLanguage
from app.schemas.llm import GeminiResponse

# ================== CONFIG ==================
load_dotenv()
logger = logging.getLogger(__name__)

# Gemini config
genai.configure(api_key=settings.EFFECTIVE_GEMINI_API_KEY)

# Model Gemini
model = genai.GenerativeModel("gemini-pro")

# Embedding model
embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

# ================== EMBEDDING ==================
def get_embeddings(texts: list[str]):
    output = embedder.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=True
    )
    return output['dense_vecs'], output['lexical_weights'], output['colbert_vecs']


# ================== SIMPLE GEMINI ==================
def ask_gemini(prompt: str):
    response = model.generate_content(prompt)
    return response.text


# ================== GENERATE ANSWER ==================
async def generate_answer(
    retrieved_context: list[str],
    system_prompt: str,
    temperature=0.3,
    question: str = "",
    chat_histories: list = None,
    language: BotLanguage = BotLanguage.VIE
):
    logger.info("========== CONTEXT =======")

    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")

    formatted_context = "\n\n".join(context_blocks)

    full_prompt = (
        system_prompt
        .replace("{{context}}", formatted_context)
        .replace("{{language}}", language.label())
        .replace("{{question}}", question)
    )

    try:
        response = model.generate_content(full_prompt)

        response_text = re.sub(
            r"^```json\s*|\s*```$",
            "",
            response.text.strip(),
            flags=re.MULTILINE
        ).strip()

        try:
            return json.loads(response_text)
        except:
            return {"content": response_text, "code": 0}

    except Exception as e:
        logger.error(str(e))
        return {"content": str(e), "code": -1}


# ================== V2 ==================
sys_prompt = """
# ROLE & MAIN TASK
Bạn là một AI Bot thông minh, đáng tin cậy.

# PROVIDED CONTEXT
```{{contexts}}```

# USER QUESTION
```{{user_question}}```
"""


async def generate_answer_v2(
    retrieved_context: list[str],
    system_prompt: str,
    temperature=0.3,
    question: str = "",
    chat_histories: list = None,
    language: BotLanguage = BotLanguage.VIE
) -> GeminiResponse:

    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")

    formatted_context = "\n".join(context_blocks)

    full_prompt = (
        sys_prompt
        .replace("{{contexts}}", formatted_context)
        .replace("{{user_question}}", question)
    )

    response = model.generate_content(full_prompt)

    try:
        return GeminiResponse.model_validate_json(response.text)
    except:
        return GeminiResponse(content=response.text, code=0)


# ================== STREAMING ==================
async def generate_answer_streaming(
    retrieved_context: list[str],
    system_prompt: str,
    conversation_uid: str | uuid.UUID,
    temperature=0.3,
    question: str = "",
    chat_histories: list = None,
    language: BotLanguage = BotLanguage.VIE
):
    from app.worker.tasks import save_dialogue

    context_blocks = []
    for i, context in enumerate(retrieved_context, start=1):
        context_blocks.append(f"[CONTEXT {i}]: {context.strip()}")

    formatted_context = "\n\n".join(context_blocks)

    full_prompt = (
        system_prompt
        .replace("{{context}}", formatted_context)
        .replace("{{language}}", language.label())
        .replace("{{question}}", question)
    )

    try:
        stream = model.generate_content(full_prompt, stream=True)

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