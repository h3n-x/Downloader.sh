"""Export the OpenAPI schema: ``python -m downloader.api.openapi > openapi.json``.

The committed schema is the contract consumed by the frontend; CI fails on drift.
"""

from __future__ import annotations

import json
import sys

from downloader.api.app import create_app
from downloader.config import Settings
from downloader.domain.providers import PROVIDERS


def main() -> None:
    settings = Settings(environment="test")
    schema = create_app(settings).openapi()
    # Single source of truth for the frontend's static "supported platforms" list.
    schema["info"]["x-providers"] = [
        {"slug": p.slug, "name": p.name} for p in PROVIDERS if p.slug in settings.providers
    ]
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
