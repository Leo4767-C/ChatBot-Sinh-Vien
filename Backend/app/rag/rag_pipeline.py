from datetime import datetime, timezone
import logging
import time
import uuid

from app.core.database import SessionLocal
from app.llm.llm_service import llm_client
from app.rag.llm_response_processor import LLMResponseProcessor
from app.rag.retriever import Retriever
from typing import List, Sequence
from app.core.config import settings
from app.schemas.enums import ModelType
from app.services.message_chunk_service import MessageChunkService

from app.services.message_service import MessageService
from qdrant_client import QdrantClient, AsyncQdrantClient

from app.worker.tasks import save_data

logger = logging.getLogger(__name__)
kwargs = {"url": settings.QDRANT_URL, "api_key": settings.QDRANT_API_KEY}
qdrant_client = QdrantClient(**kwargs, prefer_grpc=False)
async_qdrant = AsyncQdrantClient(**kwargs, prefer_grpc=False)
message_service = MessageService()
message_chunk_service = MessageChunkService()


class RAGPipeline:
    def __init__(self):
        self.retriever = Retriever(
            client=qdrant_client,
            async_client=async_qdrant
        )

    async def run(
            self,
            question: str,
            bot_id: int, bot_instruction: str, bot_model: ModelType | str,
            conv_histories: List[dict] | Sequence[dict],
            conversation_uid: str | uuid.UUID,
            org: str = None,
            start: int = 0,
            stream: bool = False
    ):
        retrieved_chunks = await self.retriever.retrieve_v3(question, bot_id)

        logger.info(f"Retrieved {len(retrieved_chunks)} chunks")

        contexts = []
        for i, chunk in enumerate(retrieved_chunks, start=1):
            text = chunk.payload.get('content', '')
            created_at = chunk.payload.get('created_at', '_')
            contexts.append(f"[CONTEXT {i}][Updated {created_at}]: {text.strip()}")

        final_context = "\n\n".join(contexts)

        sys_prompt = (
            bot_instruction.replace("{{org}}", org or "")
            .replace("{{context}}", final_context)
            .replace("{{at_time}}", datetime.now(timezone.utc).isoformat())
            .replace("{{question}}", question)
        )

        processor = LLMResponseProcessor()

        if stream:
            llm_stream = await llm_client.generate_answer_stream(
                model=bot_model,
                conv_histories=conv_histories,
                sys_prompt=sys_prompt,
                question=question,
                temperature=settings.TEMPERATURE,
                max_output_tokens=settings.MAX_OUTPUT_TOKENS,
            )

            if not llm_stream:
                yield "[CONTENT]Xin lỗi, hiện tại không lấy được phản hồi từ mô hình."
                yield "[DONE]"
                return

            is_start_yield = True
            start_yield = start

            # Fix Bug #3: stream_process giờ là async generator, dùng `async for`
            # Fix Bug #2: DB session được đóng bên trong stream_process (finally block)
            async for result in processor.stream_process(
                llm_stream, retrieved_chunks, conversation_uid, SessionLocal()
            ):
                if is_start_yield:
                    start_yield = int(time.time() * 1000)
                    is_start_yield = False
                yield result

            metadata = processor.get_metadata()
            scores = metadata.get('scores', [])
            media_refs = metadata.get('media_refs')
            json_data = processor.get_json()

            # async task
            save_data.delay(bot_model, conversation_uid, question, json_data, scores, media_refs, start_yield - start)
        else:
            logger.info("Not support for non-stream")