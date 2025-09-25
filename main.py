"""FastAPI entry point for the SNS Hack backend."""

from __future__ import annotations

import asyncio
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from agent import supervisor  # Import the compiled supervisor graph

app = FastAPI(title="Neptune - Mental Healthcare App", version="0.1.0")


@app.get("/")
async def read_root() -> dict[str, str]:
    """Return a friendly greeting so callers know the service is alive."""

    return {"message": "Hello from sns-hack!"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic readiness probe for infrastructure monitors."""

    return {"status": "ok"}


@app.post("/chat")
async def chat(request: dict[str, str]) -> StreamingResponse:
    """Stream a chat response from the LangGraph supervisor agent."""
    message = request.get("message", "")
    user_context = request.get("user_context", "")
    
    # Prepare initial state for the graph
    initial_state = {
        "messages": [HumanMessage(content=message)],
        "user_context": user_context or "No additional context provided."
    }
    
    # Async generator to stream events from the graph
    async def generate_response():
        async for event in supervisor.astream_events(initial_state, version="v2"):
            if event["event"] == "on_chat_model_stream":
                # Stream the content chunk
                chunk_data = event["data"].get("chunk")
                if chunk_data and hasattr(chunk_data, "content"):
                    chunk = chunk_data.content
                    if chunk:
                        yield f"data: {chunk}\n\n"
            elif event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                # End of the graph execution
                yield "data: [DONE]\n\n"
                break
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


def main() -> None:
    """Run a development server when executed as a module."""

    port = int(os.getenv("PORT", "8000"))

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("UVICORN_RELOAD", "true").lower() == "true")


if __name__ == "__main__":
    main()
