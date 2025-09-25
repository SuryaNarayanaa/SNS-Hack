"""FastAPI entry point for the SNS Hack backend."""

from __future__ import annotations

import os
from fastapi import FastAPI


app = FastAPI(title="SNS Hack API", version="0.1.0")


@app.get("/")
async def read_root() -> dict[str, str]:
    """Return a friendly greeting so callers know the service is alive."""

    return {"message": "Hello from sns-hack!"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic readiness probe for infrastructure monitors."""

    return {"status": "ok"}


def main() -> None:
    """Run a development server when executed as a module."""

    port = int(os.getenv("PORT", "8000"))

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("UVICORN_RELOAD", "true").lower() == "true")


if __name__ == "__main__":
    main()
