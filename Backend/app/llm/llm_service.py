import os
import google.generativeai as genai
from typing import List, Sequence

class LLMClient:
    def __init__(self):
        # Lấy Key từ môi trường
        self.api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        # Đổi thành model hiện có và ổn định nhất
        self.default_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        if self.api_key:
            genai.configure(api_key=self.api_key)

    async def generate_answer_stream(
        self,
        model: str,
        conv_histories: List[dict] | Sequence[dict],
        sys_prompt: str,
        question: str,
        temperature: float = 0.7,
        max_output_tokens: int = 2048,
    ):
        """Hàm gọi Gemini API thực tế với stream"""
        try:
            # Cấu hình model
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            }
            
            # Khởi tạo model với System Instruction (Prompt hệ thống)
            gemini_model = genai.GenerativeModel(
                model_name=model or self.default_model,
                system_instruction=sys_prompt,
                generation_config=generation_config
            )

            # Chuyển đổi lịch sử chat sang định dạng Gemini (user/model)
            history = []
            for msg in conv_histories:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})

            chat_session = gemini_model.start_chat(history=history)
            
            # Trả về async generator để frontend nhận từng chữ
            response = await chat_session.send_message_async(question, stream=True)
            return response
        except Exception as e:
            print(f"Error calling Gemini: {e}")
            return None

    def count_tokens(self, text: str) -> int:
        if not text: return 0
        return int(len(text.split()) * 1.3) # Ước tính nhanh số lượng token

llm_client = LLMClient()