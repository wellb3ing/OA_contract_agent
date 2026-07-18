"""FastAPI server for the contract check agent chat API.

Provides a single SSE endpoint ``POST /api/chat`` that accepts chat
messages and an optional file upload, then streams function-calling
progress and the final LLM response back to the client.
"""

import json
import os
import shutil
import sys
import tempfile
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from contract_agent.tracing import init_tracing
from contract_agent.function_calling import run_function_calling_loop

init_tracing()  # enable LangSmith before any LLM calls

app = FastAPI(title="合同校验 Agent API", version="1.0.0")

# Allow all origins for internal-tool use (no auth required)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(
    messages: str = Form(..., description="JSON string, chat history [{role, content}, ...]"),
    file: Optional[UploadFile] = File(None, description="Uploaded contract file (PDF/image)"),
):
    """Chat endpoint — returns an SSE event stream.

    **Request** (multipart/form-data):
        - ``messages``: JSON-encoded list of ``{"role": "user", "content": "..."}``.
        - ``file`` (optional): uploaded contract file (PDF or image).

    **Response**: ``text/event-stream`` with events ``delta``, ``tool_start``,
    ``tool_end``, ``report``, ``done``, ``error``.
    """
    # --- Parse messages ---
    try:
        parsed_messages = json.loads(messages)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="messages must be valid JSON string")

    if not isinstance(parsed_messages, list):
        raise HTTPException(status_code=400, detail="messages must be a JSON array")

    # --- Save uploaded file (stream to disk to handle large files) ---
    file_path: Optional[str] = None
    tmp_dir: Optional[str] = None
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
    if file and file.filename:
        suffix = os.path.splitext(file.filename)[1] or ".pdf"
        tmp_dir = tempfile.mkdtemp()
        file_path = os.path.join(tmp_dir, f"upload{suffix}")

        # Read in chunks to avoid loading the whole file into memory
        total = 0
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1 MB chunks
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    f.close()
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大（{total / 1024 / 1024:.0f} MB），上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
                    )
                f.write(chunk)
        print(f"[server] 文件已保存: {file_path} ({total} bytes)", flush=True)
    else:
        print(f"[server] 无文件上传, file={file}, filename={getattr(file, 'filename', None)}", flush=True)

    print(f"[server] 开始 function calling loop, file_path={file_path}", flush=True)

    # --- Return SSE stream ---
    async def generate():
        try:
            async for event in run_function_calling_loop(parsed_messages, file_path):
                yield event
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
