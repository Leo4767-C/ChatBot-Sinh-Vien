# StudyBot - Conversational RAG Assistant

StudyBot là hệ thống trợ lý học đường hỗ trợ sinh viên tra cứu quy chế học vụ, điểm chuẩn, chương trình đào tạo và tài liệu nghiên cứu. Hệ thống được phát triển dựa trên kiến trúc RAG (Retrieval-Augmented Generation) tối ưu hóa cho ngôn ngữ tiếng Việt, kết hợp tìm kiếm lai (Hybrid Search), trích xuất bảng biểu nâng cao và cơ chế xử lý đàm thoại đa lượt (Multi-turn conversational RAG).

## Kiến trúc Kỹ thuật & Công nghệ sử dụng

Hệ thống được thiết kế theo mô hình decoupled hoàn toàn giữa Frontend và Backend nhằm tối ưu hóa khả năng mở rộng (scalability) và hiệu năng phản hồi:

```text
                  +-----------------------------------+
                  |        Next.js Frontend           |
                  +-----------------+-----------------+
                                    | HTTP / SSE Stream
                                    v
                  +-----------------+-----------------+
                  |        FastAPI Backend            |
                  +-------+-----------------+---------+
                          |                 |
         SQLAlchemy Async |                 | Dense & Sparse Embeddings (BGE-M3)
                          v                 v
                  +-------+-------+ +-------+-------+
                  |  SQLite (DB)  | |  Qdrant (VDB)  |
                  +---------------+ +---------------+
```

### 1. Backend Service (FastAPI)
- **FastAPI & Uvicorn**: Sử dụng mô hình xử lý bất đồng bộ (Asynchronous ASGI) để tối ưu hóa tài nguyên máy chủ và xử lý số lượng kết nối đồng thời (concurrency) cao.
- **SQLAlchemy 2.0 & aiosqlite**: Quản lý cơ sở dữ liệu quan hệ (SQLite) ở chế độ non-blocking để lưu trữ lịch sử tin nhắn và thông tin phiên giao dịch (session metadata).
- **Celery / Background Tasks**: Xử lý bất đồng bộ các tác vụ lưu trữ dữ liệu hội thoại và ghi chép nhật ký hệ thống nhằm giảm thiểu độ trễ cho người dùng cuối.

### 2. RAG & Vector Engine (Qdrant & BAAI/bge-m3)
- **Hybrid Search Engine**: Sử dụng mô hình đa ngôn ngữ BAAI/bge-m3 để biểu diễn văn bản dưới hai định dạng vector đồng thời:
  - **Dense Vector (1024 chiều)**: Phản ánh ngữ nghĩa và ngữ cảnh sâu của truy vấn.
  - **Sparse Vector**: Khớp chính xác các từ khóa và thuật ngữ chuyên ngành.
- **Reciprocal Rank Fusion (RRF)**: Tích hợp tính năng Fusion Query của Qdrant DB để kết hợp xếp hạng kết quả từ tìm kiếm Dense và Sparse, cải thiện độ chính xác tra cứu so với tìm kiếm vector tiêu chuẩn.
- **Table-Aware Chunking**: Module trích xuất bảng biểu chuyên dụng (`table_extractor.py`) phân tách dữ liệu bảng trong PDF và chuẩn hóa sang định dạng Markdown trước khi lập chỉ mục (`is_table=True`), khắc phục hạn chế mất cấu trúc bảng của các hệ thống RAG truyền thống.

### 3. LLM Orchestration & Prompt Engineering
- **Google Gemini SDK**: Đảm nhận vai trò tạo câu trả lời (Generator) dựa trên ngữ cảnh được cung cấp.
- **Conversational Query Rewriting**: Đối với các truy vấn tiếp nối (follow-up), module rewriter tự động phân tích lịch sử hội thoại gần nhất để làm rõ nghĩa và mở rộng các truy vấn ngắn thành câu hỏi hoàn chỉnh ngữ nghĩa trước khi định tuyến chúng đến Vector DB.
- **Multimodal Comprehension**: Hỗ trợ xử lý dữ liệu đầu vào là hình ảnh tài liệu hoặc bài giảng, tự động thực hiện OCR và tóm tắt thông qua Gemini Vision API.

### 4. Frontend Application (Next.js)
- **Next.js App Router & TypeScript**: Đảm bảo tính toàn vẹn của mã nguồn, tối ưu hóa SEO và cải thiện hiệu năng tải trang.
- **Server-Sent Events (SSE) Client**: Tiếp nhận dữ liệu dạng luồng (streaming response) từ Backend để tạo hiệu ứng hiển thị thời gian thực.
- **Web Speech API**: Tích hợp công cụ nhận diện giọng nói (Speech-to-Text) nguyên bản của trình duyệt để hỗ trợ nhập liệu bằng giọng nói.

## Cấu trúc Thư mục Dự án

```text
chatbot-student/
├── Backend/                    # FastAPI Python Service
│   ├── app/
│   │   ├── core/               # Khởi tạo cấu hình (config.py)
│   │   ├── models/             # Định nghĩa Schema DB (database.py)
│   │   ├── routers/            # Các API endpoints (chat, sessions, document)
│   │   ├── rag/                # Pipeline RAG, Embedder, Retriever, Extractor
│   │   └── llm/                # Trình kết nối dịch vụ Gemini API
│   ├── main.py                 # Entry point khởi chạy ứng dụng
│   ├── ingest.py               # Script xử lý và lập chỉ mục dữ liệu
│   └── requirements.txt        # Các thư viện phụ thuộc
│
└── Frontend/                   # Next.js Application
    ├── src/
    │   ├── app/                # Cấu trúc trang (page.tsx, layout.tsx)
    │   ├── components/         # Giao diện UI (ChatInput, MessageBubble)
    │   ├── hooks/              # Custom Hook xử lý Web Speech API
    │   └── lib/                # API Client gọi đến FastAPI
    └── package.json
```

## Hướng dẫn Cài đặt & Vận hành

### 1. Chuẩn bị biến môi trường
Tạo tệp `.env` tại thư mục `Backend/` với cấu trúc sau:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
DATABASE_URL=sqlite+aiosqlite:///./app.db
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=nckh_docs
COLLECTION_NAME=nckh_docs
EMBEDDING_VECTOR_SIZE=1024
DEVICE=cpu
```

### 2. Khởi chạy Backend & Vector Database (Qdrant)

Yêu cầu máy chủ đã cài đặt Docker để vận hành Qdrant:
```bash
# Khởi chạy container Qdrant DB
docker run -d -p 6333:6333 -p 6334:6334 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant
```

Cài đặt các thư viện phụ thuộc Python và khởi chạy FastAPI server:
```bash
cd Backend

# Khởi tạo và kích hoạt môi trường ảo
python -m venv venv
source venv/bin/activate # Trên Windows: venv\Scripts\activate

# Cài đặt thư viện
pip install -r requirements.txt

# Khởi chạy uvicorn server ở chế độ hot-reload
python main.py
```
*Backend API hoạt động tại địa chỉ:* `http://localhost:8000`

### 3. Nạp Tài liệu Tri thức (Data Ingestion Pipeline)

Để đưa tài liệu quy chế, điểm chuẩn (PDF, Docx, TXT) vào cơ sở dữ liệu Vector Qdrant:
1. Đặt các tệp tài liệu hỗ trợ (`.pdf`, `.docx`, `.txt`, `.md`) vào thư mục `Backend/data/`.
2. Chạy script nạp dữ liệu:
```bash
# Nạp dữ liệu mới trong thư mục data/ (có cơ chế checksum bỏ qua file không thay đổi)
python ingest.py

# Xóa toàn bộ dữ liệu hiện có trong Qdrant và lập chỉ mục lại từ đầu
python ingest.py --clear
```

### 4. Khởi chạy Frontend (Next.js)

Tạo tệp `.env.local` tại thư mục `Frontend/`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Cài đặt các gói Node.js và chạy ứng dụng ở chế độ Development:
```bash
cd Frontend

# Cài đặt package thông qua npm hoặc pnpm
npm install

# Khởi chạy Next.js dev server
npm run dev
```
*Frontend chạy tại địa chỉ:* `http://localhost:3000`

## Chi tiết Cơ chế Tìm kiếm lai (Hybrid Search)

Logic cốt lõi để thực thi tìm kiếm lai kết hợp RRF được hiện thực hóa tại `retriever.py`. Trong quá trình truy vấn, hệ thống thực thi đồng thời hai luồng xử lý thông qua Qdrant client:

1. **Dense Query**: Truy xuất vector dày đặc từ model `bge-m3` nhằm tìm kiếm các phân đoạn văn bản có độ tương đồng cao nhất về mặt ngữ nghĩa (`Prefetch dense`).
2. **Sparse Query**: Tính toán đối chiếu các trọng số từ khóa thưa thớt (`lexical_weights`) từ `bge-m3` để khớp chính xác các thuật ngữ viết tắt hoặc mã học phần đặc thù (`Prefetch sparse`).
3. **Reciprocal Rank Fusion (RRF)**: Qdrant tổng hợp các danh sách xếp hạng từ cả hai luồng tìm kiếm bằng phương pháp RRF theo công thức:
   $$\text{Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
   *(Trong đó $r_m(d)$ là thứ hạng của tài liệu $d$ trong danh sách kết quả $m$, và hằng số $k = 60$)*.

Sự kết hợp này đảm bảo hệ thống vừa nắm bắt được ngữ cảnh sâu của câu hỏi, vừa duy trì độ chính xác cao đối với các từ khóa cụ thể.

## Hướng Phát triển Mở rộng (Production Readiness)

- **RAG Evaluation**: Tích hợp các công cụ đo lường (ví dụ: Ragas, TruLens) để giám sát và đánh giá liên tục các chỉ số Faithfulness và Context Recall.
- **Vector DB Clustering**: Triển khai kiến trúc cụm (cluster) cho Qdrant trên môi trường điện toán đám mây để hỗ trợ phân tán dữ liệu và cân bằng tải truy vấn.
- **Embedding Pipeline Optimization**: Chuyển đổi mô hình tạo vector `BAAI/bge-m3` sang các server suy luận chuyên dụng (Triton Inference Server) hoặc áp dụng kỹ thuật tăng tốc phần cứng thông qua định dạng ONNX/TensorRT trên GPU.
