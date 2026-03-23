import json
import logging
import os
import re

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


def _normalize_source_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return "Không rõ nguồn"

    title = os.path.basename(title)

    title = re.sub(
        r"\[(BẢNG|TABLE|CONTEXT)\s*\d+\]",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()

    title = re.sub(r"\s+", " ", title).strip(" -–—:,")
    return title or "Không rõ nguồn"


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

                        if chunk.media_refs and len(chunk.media_refs):
                            media_refs += chunk.media_refs

                        document_id = chunk.document_id
                        normalized_title = _normalize_source_title(document_title)

                        if document_id not in citations:
                            citations[document_id] = {
                                "id": document_id,
                                "title": normalized_title,
                            }

                    if len(media_refs):
                        yield f"\n{REFS_TAG}{json.dumps(media_refs, ensure_ascii=False)}"

                final_citations = []
                seen_titles = set()

                for doc in citations.values():
                    title = _normalize_source_title(doc["title"])
                    if not title or title in seen_titles:
                        continue

                    seen_titles.add(title)
                    final_citations.append({
                        "id": doc["id"],
                        "title": title,
                    })

                yield CITATION_TAG + json.dumps(final_citations, ensure_ascii=False)

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