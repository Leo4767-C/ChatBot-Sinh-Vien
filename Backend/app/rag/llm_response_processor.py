import json
import logging

from partialjson.json_parser import JSONParser

from app.schemas.llm import GeminiResponse
from app.services.chunk_service import ChunkService

logger = logging.getLogger(__name__)
chunk_service = ChunkService()

TOPIC = 'topic'
TOPIC_TAG = '[TOPIC]'
CONTENT = 'content'
CONTENT_TAG = '[CONTENT]'
REFS = 'refs'
REFS_TAG = '[REFS]'
CITATION_TAG = '[CITATION]'
ERROR_TAG = '[ERROR]'
DONE_TAG = '[DONE]'
UUID_TAG = '[UUID]'


class LLMResponseProcessor:
    def __init__(self):
        self.parser = JSONParser()
        self.full_json = ""
        self.metadata = dict()

    def get_metadata(self):
        return self.metadata

    def get_json(self):
        return self.full_json

    async def stream_process(self, stream, contexts, conv_uid, db):
        """
        Async generator — hỗ trợ cả sync và async stream từ Gemini.
        """
        logger.info("Start stream processing...")
        try:
            last_topic = ""
            content_yielded_len = 0

            async def iter_stream():
                import inspect
                if inspect.isasyncgen(stream):
                    async for chunk in stream:
                        yield chunk
                else:
                    for chunk in stream:
                        yield chunk

            async for chunk in iter_stream():
                candidate = chunk.candidates[0] if chunk.candidates else None
                if not candidate or not candidate.content or not candidate.content.parts:
                    continue

                text = candidate.content.parts[0].text or ""
                self.full_json += text

                try:
                    obj = self.parser.parse(self.full_json)
                except Exception:
                    logger.exception("Failed to parse %s", self.full_json)
                    obj = None

                if not obj:
                    continue

                current_topic = obj.get(TOPIC)
                if current_topic and isinstance(current_topic, str) and current_topic != last_topic:
                    yield f"{TOPIC_TAG}{current_topic}"
                    last_topic = current_topic

                content = obj.get(CONTENT)
                if content and isinstance(content, str):
                    delta = content[content_yielded_len:]
                    if delta:
                        yield f"{CONTENT_TAG}{delta}"
                        content_yielded_len = len(content)

            if self.full_json:
                logger.info(f"Generated answer: {self.full_json}")

                try:
                    response = GeminiResponse.model_validate_json(self.full_json)
                except Exception:
                    logger.exception("Failed to validate LLM response JSON: %s", self.full_json)
                    yield f"{CONTENT_TAG}Không thể xử lý phản hồi từ AI."
                    yield f"{UUID_TAG}{conv_uid}"
                    yield DONE_TAG
                    return

                media_refs = []
                citations = dict()
                refs = response.refs if (hasattr(response, "refs") and response.refs) else []

                if refs:
                    point_ids = [p.id for p in contexts]
                    chunks = chunk_service.get_chunks_by_point_ids(db, point_ids)
                    chunk_map = {row[0].point_id: row for row in chunks}
                    chunks = [chunk_map[pid] for pid in point_ids if pid in chunk_map]

                    for i, (chunk, document_title) in enumerate(chunks, start=1):
                        if i not in refs:
                            continue

                        media_refs += chunk.media_refs if chunk.media_refs and len(chunk.media_refs) else []
                        document_id = chunk.document_id
                        if document_id not in citations:
                            citations[document_id] = {
                                "id": document_id,
                                "title": document_title,
                                "pages": set(),
                            }

                        if chunk.pages:
                            citations[document_id]["pages"].update(
                                int(p) for p in chunk.pages if str(p).strip().isdigit()
                            )

                    if len(media_refs):
                        yield f"\n{REFS_TAG}{json.dumps(media_refs, ensure_ascii=False)}"

                final_citations = []
                for doc in citations.values():
                    final_citations.append({
                        "id": doc["id"],
                        "title": doc["title"],
                        "pages": sorted(list(doc["pages"])),
                    })
                yield CITATION_TAG + json.dumps(final_citations, ensure_ascii=False)

                # FIX: dùng chunk.point_id (str Qdrant ID) thay vì c.id (UUID của Qdrant point, không phải DB chunk id)
                # scores lưu [point_id, score] để sau đó map về chunk DB trong save_data task
                scores = [
                    [str(c.id), c.score if (order in refs) else 0]
                    for order, c in enumerate(contexts, start=1)
                ]
                self.metadata = {"scores": scores, "media_refs": media_refs}

            yield f"{UUID_TAG}{conv_uid}"
            yield DONE_TAG

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                logger.warning("Gemini API quota exceeded: %s", err_str)
                yield f"{CONTENT_TAG}Xin lỗi, hệ thống đang tạm thời quá tải. Vui lòng thử lại sau ít phút."
            else:
                logger.exception("Error process stream")
                yield f"{CONTENT_TAG}Xin lỗi, hệ thống đang gặp lỗi khi tạo câu trả lời."
            yield f"{UUID_TAG}{conv_uid}"
            yield DONE_TAG
        finally:
            try:
                db.close()
            except Exception:
                pass