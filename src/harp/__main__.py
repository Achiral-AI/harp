"""Entrypoint: ``python -m harp``."""

from __future__ import annotations

import logging

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )
    uvicorn.run(
        "harp.server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        proxy_headers=True,
        access_log=False,
    )


if __name__ == "__main__":
    main()
