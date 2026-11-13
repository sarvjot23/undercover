"""Serve the context layer on the laptop: uv run -m context."""

from context.server import build_server

build_server().run(transport="streamable-http")
