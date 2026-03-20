# 🎓 StudyBot — Chatbot Hỗ Trợ Sinh Viên

Chatbot AI thông minh sử dụng Google Gemini, Next.js và FastAPI.

---

## 📁 Cấu trúc thư mục

```
chatbot-student/
├── backend/                    # FastAPI Python
│   ├── main.py                 # Entry point, CORS, routes
│   ├── gemini_service.py       # Logic gọi Gemini API
│   ├── schemas.py              # Pydantic models
│   ├── requirements.txt
│   └── .env                    # GEMINI_API_KEY (tự tạo)
│
└── frontend/                   # Next.js
    ├── src/
    │   ├── app/
    │   │   ├── page.tsx        # Trang chat chính
    │   │   ├── layout.tsx      # Root layout + fonts
    │   │   └── globals.css
    │   ├── components/
    │   │   ├── ChatMessage.tsx       # Bong bóng chat + TypingIndicator
    │   │   ├── ChatInput.tsx         # Ô nhập liệu + Voice button
    │   │   └── MarkdownRenderer.tsx  # Render markdown/code/ảnh
    │   ├── hooks/
    │   │   └── useVoiceInput.ts      # Hook Web Speech API
    │   └── lib/
    │       └── api.ts                # API client gọi FastAPI
    ├── next.config.mjs
    ├── tailwind.config.ts
    └── package.json
```

---

## 🚀 Hướng dẫn cài đặt

### Bước 1: Lấy Gemini API Key

1. Truy cập [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Đăng nhập Google Account
3. Nhấn **"Create API Key"**
4. Copy key vừa tạo

---

### Bước 2: Cài đặt Backend (FastAPI)

```bash
# 1. Di chuyển vào thư mục backend
cd chatbot-student/backend

# 2. Tạo virtual environment (khuyến nghị)
python -m venv venv

# 3. Kích hoạt virtual environment
# Trên macOS/Linux:
source venv/bin/activate
# Trên Windows:
venv\Scripts\activate

# 4. Cài đặt dependencies
pip install -r requirements.txt

# 5. Tạo file .env từ template
cp .env.example .env

# 6. Mở file .env và điền API key của bạn
# GEMINI_API_KEY=AIza...your_key_here
```

**Chạy Backend:**
```bash
# Cách 1: Chạy trực tiếp (có auto-reload khi dev)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Cách 2: Chạy qua Python
python main.py
```

✅ Backend chạy tại: `http://localhost:8000`
📖 API Docs (Swagger): `http://localhost:8000/docs`

---

### Bước 3: Cài đặt Frontend (Next.js)

```bash
# 1. Di chuyển vào thư mục frontend
cd chatbot-student/frontend

# 2. Cài đặt Node packages
npm install
# hoặc: yarn install / pnpm install

# 3. File .env.local đã có sẵn với nội dung:
# NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Chạy Frontend:**
```bash
npm run dev
```

✅ Frontend chạy tại: `http://localhost:3000`

---

### Bước 4: Chạy cả 2 server cùng lúc

**Option A: Dùng 2 terminal**
```bash
# Terminal 1 — Backend
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend  
cd frontend && npm run dev
```

**Option B: Dùng script (macOS/Linux)**

Tạo file `start.sh` ở thư mục gốc:
```bash
#!/bin/bash
echo "🚀 Khởi động StudyBot..."

# Khởi động Backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
echo "✅ Backend PID: $BACKEND_PID"

# Khởi động Frontend
cd ../frontend
npm run dev &
FRONTEND_PID=$!
echo "✅ Frontend PID: $FRONTEND_PID"

echo ""
echo "📌 Backend:  http://localhost:8000"
echo "📌 Frontend: http://localhost:3000"
echo ""
echo "Nhấn Ctrl+C để dừng tất cả..."

# Chờ và cleanup khi Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
```

```bash
chmod +x start.sh
./start.sh
```

**Option C: Dùng `concurrently` (Windows-friendly)**
```bash
# Cài concurrently
npm install -g concurrently

# Chạy từ thư mục gốc
concurrently \
  "cd backend && uvicorn main:app --reload --port 8000" \
  "cd frontend && npm run dev"
```

---

## 🧪 Test API thủ công

```bash
# Test health check
curl http://localhost:8000/health

# Test chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Giải thích về Machine Learning"}
    ]
  }'
```

---

## 🎤 Về tính năng Voice Input

Voice Input sử dụng **Web Speech API** — API tích hợp sẵn của trình duyệt, không cần key hay server.

**Trình duyệt hỗ trợ:**
| Trình duyệt | Hỗ trợ |
|-------------|--------|
| Chrome / Edge | ✅ Đầy đủ |
| Firefox | ⚠️ Cần bật flag |
| Safari (macOS 14.1+) | ✅ |
| Mobile Chrome | ✅ |

**Lưu ý:** Trình duyệt sẽ hỏi xin quyền truy cập microphone lần đầu.

---

## 🖼️ Về tính năng Hình ảnh minh họa

Gemini được cấu hình trong System Instruction để tự động chèn ảnh Unsplash khi giải thích khái niệm phức tạp.

**Format ảnh Gemini trả về:**
```markdown
![Mô tả ảnh](https://source.unsplash.com/800x400/?machine-learning,neural-network)
```

Frontend dùng `react-markdown` + custom `img` component để render có fallback khi ảnh lỗi.

---

## 🔧 Các lỗi thường gặp

| Lỗi | Nguyên nhân | Cách sửa |
|-----|-------------|----------|
| `CORS error` | Frontend không kết nối được Backend | Đảm bảo Backend đang chạy ở port 8000 |
| `GEMINI_API_KEY not configured` | Chưa tạo file `.env` | Tạo `.env` từ `.env.example` |
| `503 Service Unavailable` | Gemini API lỗi/quota hết | Kiểm tra API key và quota tại Google AI Studio |
| `Microphone not working` | Không dùng Chrome | Dùng Chrome hoặc Edge |
| `Module not found` | Chưa install packages | Chạy `pip install -r requirements.txt` và `npm install` |

---

## 🔮 Mở rộng thêm

- **Streaming response**: Thêm `stream=True` trong Gemini call + Server-Sent Events ở FastAPI
- **Lưu lịch sử**: Tích hợp SQLite/PostgreSQL để lưu conversation history
- **Auth**: Thêm đăng nhập sinh viên bằng email trường
- **RAG**: Upload tài liệu học và để Gemini trả lời dựa trên tài liệu đó
- **TTS**: Text-to-Speech để đọc câu trả lời bằng giọng nói
