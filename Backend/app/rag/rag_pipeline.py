from datetime import datetime, timezone
import logging
import time
import uuid
from typing import List, Sequence

from qdrant_client import QdrantClient, AsyncQdrantClient

from app.core.database import SessionLocal
from app.llm.llm_service import llm_client
from app.rag.llm_response_processor import LLMResponseProcessor
from app.rag.retriever import Retriever
from app.core.config import settings
from app.schemas.enums import ModelType
from app.worker.tasks import save_data

logger = logging.getLogger(__name__)
kwargs = {"url": settings.QDRANT_URL, "api_key": settings.QDRANT_API_KEY}
qdrant_client = QdrantClient(**kwargs, prefer_grpc=False)
async_qdrant = AsyncQdrantClient(**kwargs, prefer_grpc=False)


class RAGPipeline:
    def __init__(self):
        self.retriever = Retriever(
            client=qdrant_client,
            async_client=async_qdrant
        )

    async def run(
        self,
        question: str,
        bot_id: int,
        bot_instruction: str,
        bot_model: ModelType | str,
        conv_histories: List[dict] | Sequence[dict],
        conversation_uid: str | uuid.UUID,
        org: str = None,
        start: int = 0,
        stream: bool = False
    ):
        retrieved_chunks = await self.retriever.retrieve_v3(question, bot_id)
        logger.info("Retrieved %s chunks", len(retrieved_chunks))

        contexts = []
        for chunk in retrieved_chunks[:4]:
            payload = chunk.payload or {}
            text = (payload.get("content") or "").strip()
            if not text:
                continue
            contexts.append(text)

        final_context = "\n\n---\n\n".join(contexts)
        question_lower = (question or "").lower().strip()

        is_need_yes_no_question = (
            question_lower.startswith("có cần")
            or "có cần" in question_lower
        )

        if is_need_yes_no_question:
            answer_style = (
                "Đây là câu hỏi dạng Có/Không. "
                "Chỉ trả lời đúng 3 phần theo đúng thứ tự sau:\n"
                "1. Có hoặc Không ở dòng đầu.\n"
                "2. Đối tượng áp dụng: ...\n"
                "3. Đối tượng không áp dụng: ...\n\n"
                "DỪNG LẠI sau 3 phần này. "
                "KHÔNG giải thích thêm. "
                "KHÔNG liệt kê các cách đáp ứng. "
                "KHÔNG nêu điều kiện chi tiết. "
                "KHÔNG mở rộng sang phần yêu cầu, chứng chỉ, kỳ thi hoặc ví dụ. "
                "KHÔNG dùng bullet list. "
                "KHÔNG dùng bảng. "
                "KHÔNG lặp lại ý đã nêu. "
                "KHÔNG chèn ký hiệu tham chiếu như [BẢNG 1], [CONTEXT 2], [1], [2]."
            )
            max_tokens = min(settings.MAX_OUTPUT_TOKENS, 220)
        else:
            answer_style = (
                "Trả lời rõ ràng, đúng trọng tâm, ưu tiên nội dung có trong context. "
                "Nếu nội dung ngắn, các ý đồng đều và dễ đối chiếu, có thể trình bày bằng bảng Markdown. "
                "Nếu nội dung dài hoặc mỗi ý không đồng đều, hãy dùng bullet list. "
                "Không dùng HTML như <br>. "
                "Không nhắc tới [CONTEXT], [BẢNG], [TABLE], tài liệu nội bộ, hay cách bạn suy luận. "
                "Không chèn ký hiệu tham chiếu như [BẢNG 1], [CONTEXT 2], [1], [2]. "
                "Không lặp lại ý đã nói."
            )
            max_tokens = min(settings.MAX_OUTPUT_TOKENS, 500)

        sys_prompt = (
            f"Bạn là Trợ lý Nghiên cứu Khoa học của trường đại học. "
            f"Nhiệm vụ của bạn là trả lời câu hỏi dựa trên ngữ cảnh được cung cấp dưới đây.\n"
            f"CHỈ THỊ ĐẶC BIỆT CỦA BOT: {bot_instruction}\n\n"
            f"NGỮ CẢNH:\n{final_context}\n\n"
            f"HƯỚNG DẪN CHUNG:\n"
            f"1. Nếu câu trả lời có trong NGỮ CẢNH, hãy ưu tiên sử dụng thông tin đó.\n"
            f"2. Nếu không có trong NGỮ CẢNH, hãy dùng kiến thức chuyên môn của bạn nhưng phải nêu rõ 'Dựa trên kiến thức chung...'.\n"
            f"3. Sử dụng tiếng Việt rõ ràng, dễ đọc.\n"
            f"4. Có thể dùng bảng Markdown nếu nội dung ngắn, các dòng/ý đồng đều và dễ đối chiếu.\n"
            f"5. Không dùng bảng Markdown nếu nội dung dài hoặc có nhiều câu giải thích trong một ý.\n"
            f"6. Không dùng HTML như <br>.\n"
            f"7. Không trình bày theo kiểu hai cột hoặc 'A — B' nếu không phải bảng Markdown chuẩn.\n"
            f"8. Không nhắc đến [CONTEXT], [BẢNG], [TABLE], tài liệu nội bộ, hay cách bạn suy luận.\n"
            f"9. Không được chèn ký hiệu tham chiếu như [BẢNG 1], [CONTEXT 2], [1], [2] vào nội dung trả lời.\n"
            f"10. Nếu có nhiều ý, hãy dùng bullet list ngắn gọn khi không phù hợp để lập bảng.\n"
            f"11. Nếu một bullet cần giải thích thêm, thêm 1 dòng con bắt đầu bằng '- '.\n"
            f"12. Không lặp lại nội dung đã nói ở trên.\n"
            f"13. Nếu người dùng hỏi rộng, hãy tóm tắt trước thay vì trích lại toàn bộ tài liệu.\n"
            f"14. Không được mở đầu một mục rồi bỏ dở, ví dụ 'có các cách sau' mà không liệt kê.\n\n"
            f"YÊU CẦU RIÊNG CHO CÂU HỎI NÀY:\n"
            f"{answer_style}\n\n"
            f"Nếu câu hỏi là dạng 'Có cần ... không?', tuyệt đối không trả lời vượt quá phạm vi người dùng hỏi.\n"
        )

        processor = LLMResponseProcessor()

        if stream:
            llm_stream = await llm_client.generate_answer_stream(
                model=bot_model,
                conv_histories=conv_histories,
                sys_prompt=sys_prompt,
                question=question,
                temperature=0.1,
                max_output_tokens=max_tokens,
            )

            if not llm_stream:
                yield "[CONTENT]Xin lỗi, hiện tại không lấy được phản hồi từ mô hình."
                yield "[DONE]"
                return

            is_start_yield = True
            start_yield = start
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
                db_session.close()

            metadata = processor.get_metadata()
            scores = metadata.get("scores", [])
            media_refs = metadata.get("media_refs")
            json_data = processor.get_json()

            save_data.delay(
                bot_model,
                conversation_uid,
                question,
                json_data,
                scores,
                media_refs,
                start_yield - start
            )
        else:
            logger.info("Not support for non-stream")