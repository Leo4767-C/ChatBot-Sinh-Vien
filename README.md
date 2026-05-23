# StudyBot - Conversational RAG Assistant

StudyBot is an academic assistant system that helps students look up academic regulations, admission scores, training programs, and research materials. The system is built on a RAG (Retrieval-Augmented Generation) architecture optimized for the Vietnamese language, combining Hybrid Search, advanced table extraction, and a Multi-turn Conversational RAG mechanism.

## Technical Architecture & Technology Stack

The system follows a fully decoupled architecture between Frontend and Backend to optimize scalability and response performance:

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
- **FastAPI & Uvicorn**: Uses an asynchronous processing model (Asynchronous ASGI) to optimize server resources and handle high concurrency.
- **SQLAlchemy 2.0 & aiosqlite**: Manages the relational database (SQLite) in non-blocking mode for storing message history and session metadata.
- **Celery / Background Tasks**: Asynchronously processes conversation data storage and system logging tasks to minimize end-user latency.

### 2. RAG & Vector Engine (Qdrant & BAAI/bge-m3)
- **Hybrid Search Engine**: Uses the multilingual BAAI/bge-m3 model to represent text in two simultaneous vector formats:
  - **Dense Vector (1024 dimensions)**: Captures deep semantics and contextual meaning of queries.
  - **Sparse Vector**: Performs exact matching on keywords and domain-specific terminology.
- **Reciprocal Rank Fusion (RRF)**: Leverages Qdrant DB's Fusion Query feature to combine rankings from Dense and Sparse searches, improving retrieval accuracy over standard vector search.
- **Table-Aware Chunking**: A dedicated table extraction module (`table_extractor.py`) parses tabular data from PDFs and normalizes it into Markdown format before indexing (`is_table=True`), overcoming the table structure loss limitation of traditional RAG systems.

### 3. LLM Orchestration & Prompt Engineering
- **Google Gemini SDK**: Serves as the answer generator based on the provided context.
- **Conversational Query Rewriting**: For follow-up queries, the rewriter module automatically analyzes recent conversation history to disambiguate and expand short queries into semantically complete questions before routing them to the Vector DB.
- **Multimodal Comprehension**: Supports image-based document or lecture inputs, automatically performing OCR and summarization through the Gemini Vision API.

### 4. Frontend Application (Next.js)
- **Next.js App Router & TypeScript**: Ensures codebase integrity, optimizes SEO, and improves page load performance.
- **Server-Sent Events (SSE) Client**: Receives streaming responses from the Backend to deliver real-time display effects.
- **Web Speech API**: Integrates the browser's native Speech-to-Text engine to support voice input.

## Project Directory Structure

```text
chatbot-student/
├── Backend/                    # FastAPI Python Service
│   ├── app/
│   │   ├── core/               # Configuration initialization (config.py)
│   │   ├── models/             # DB schema definitions (database.py)
│   │   ├── routers/            # API endpoints (chat, sessions, document)
│   │   ├── rag/                # RAG Pipeline, Embedder, Retriever, Extractor
│   │   └── llm/                # Gemini API service connector
│   ├── main.py                 # Application entry point
│   ├── ingest.py               # Data processing and indexing script
│   └── requirements.txt        # Python dependencies
│
└── Frontend/                   # Next.js Application
    ├── src/
    │   ├── app/                # Page structure (page.tsx, layout.tsx)
    │   ├── components/         # UI components (ChatInput, MessageBubble)
    │   ├── hooks/              # Custom Hook for Web Speech API
    │   └── lib/                # API Client for FastAPI
    └── package.json
```

## Installation & Deployment Guide

### 1. Configure Environment Variables
Create a `.env` file in the `Backend/` directory with the following structure:
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

### 2. Start the Backend & Vector Database (Qdrant)

Docker must be installed on the server to run Qdrant:
```bash
# Start the Qdrant DB container
docker run -d -p 6333:6333 -p 6334:6334 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant
```

Install Python dependencies and start the FastAPI server:
```bash
cd Backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the uvicorn server in hot-reload mode
python main.py
```
*Backend API is available at:* `http://localhost:8000`

### 3. Knowledge Document Ingestion (Data Ingestion Pipeline)

To ingest regulation documents, admission scores (PDF, Docx, TXT) into the Qdrant Vector Database:
1. Place the supported document files (`.pdf`, `.docx`, `.txt`, `.md`) in the `Backend/data/` directory.
2. Run the ingestion script:
```bash
# Ingest new data from the data/ directory (includes checksum mechanism to skip unchanged files)
python ingest.py

# Clear all existing data in Qdrant and re-index from scratch
python ingest.py --clear
```

### 4. Start the Frontend (Next.js)

Create a `.env.local` file in the `Frontend/` directory:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Install Node.js packages and run the application in Development mode:
```bash
cd Frontend

# Install packages via npm or pnpm
npm install

# Start the Next.js dev server
npm run dev
```
*Frontend is available at:* `http://localhost:3000`

## Hybrid Search Mechanism Details

The core logic for executing hybrid search with RRF is implemented in `retriever.py`. During a query, the system concurrently executes two processing streams through the Qdrant client:

1. **Dense Query**: Retrieves dense vectors from the `bge-m3` model to find text segments with the highest semantic similarity (`Prefetch dense`).
2. **Sparse Query**: Computes sparse keyword weights (`lexical_weights`) from `bge-m3` for exact matching of abbreviations or domain-specific course codes (`Prefetch sparse`).
3. **Reciprocal Rank Fusion (RRF)**: Qdrant aggregates the ranking lists from both search streams using the RRF method with the formula:
   $$\text{Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
   *(Where $r_m(d)$ is the rank of document $d$ in result list $m$, and the constant $k = 60$)*.

This combination ensures the system captures deep contextual understanding of questions while maintaining high accuracy for specific keywords.

## Future Development Roadmap (Production Readiness)

- **RAG Evaluation**: Integrate measurement tools (e.g., Ragas, TruLens) for continuous monitoring and evaluation of Faithfulness and Context Recall metrics.
- **Vector DB Clustering**: Deploy a cluster architecture for Qdrant on cloud computing environments to support data distribution and query load balancing.
- **Embedding Pipeline Optimization**: Migrate the `BAAI/bge-m3` embedding model to dedicated inference servers (Triton Inference Server) or apply hardware acceleration techniques using ONNX/TensorRT formats on GPU.
