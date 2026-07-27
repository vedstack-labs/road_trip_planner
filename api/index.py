"""Vercel serverless entrypoint.

Vercel's Python runtime discovers files under ``api/`` and serves the ASGI
``app`` it finds here. All routing is delegated to the FastAPI application; see
``vercel.json`` for the catch-all rewrite that forwards every path to this
function.
"""

from app.main import app

__all__ = ["app"]
