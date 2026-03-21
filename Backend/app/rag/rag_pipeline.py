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

        # CẬP NHẬT 1: Đưa bot_instruction vào để Bot nghe lời cấu hình từ DB
        sys_prompt = (
            f"Bạn là Trợ lý Nghiên cứu Khoa học của trường đại học. "
            f"Nhiệm vụ của bạn là trả lời câu hỏi dựa trên ngữ cảnh được cung cấp dưới đây.\n"
            f"CHỈ THỊ ĐẶC BIỆT CỦA BOT: {bot_instruction}\n\n"
            f"NGỮ CẢNH (CONTEXT):\n{final_context}\n\n"
            f"HƯỚNG DẪN:\n"
            f"1. Nếu câu trả lời có trong NGỮ CẢNH, hãy ưu tiên sử dụng thông tin đó.\n"
            f"2. Nếu không có trong NGỮ CẢNH, hãy dùng kiến thức chuyên môn của bạn nhưng phải nêu rõ 'Dựa trên kiến thức chung...'.\n"
            f"3. Sử dụng Markdown để trình bày (in đậm, danh sách).\n"
            f"4. Nếu người dùng yêu cầu hình ảnh, hãy sử dụng cú pháp: ![mô tả](/images/ten_file_anh.png) nếu ảnh có trong ngữ cảnh."
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

            # CẬP NHẬT 2: Quản lý kết nối Database an toàn (Chống rò rỉ Memory/DB)
            db_session = SessionLocal()
            try:
                async for result in processor.stream_process(
                    llm_stream, retrieved_chunks, conversation_uid, db_session
                ):
                    if is_start_yield:
                        start_yield = int(time.time() * 1000)
                        is_start_yield = False
                    yield result
            finally:
                db_session.close() # Dù lỗi hay chạy xong đều tự động ngắt kết nối

            metadata = processor.get_metadata()
            scores = metadata.get('scores', [])
            media_refs = metadata.get('media_refs')
            json_data = processor.get_json()

            # async task
            save_data.delay(bot_model, conversation_uid, question, json_data, scores, media_refs, start_yield - start)
        else:
            logger.info("Not support for non-stream")