from __future__ import annotations

import json
import sys
from pathlib import Path

from freshbot_butler.api.main import create_app
from freshbot_butler.api.settings import Settings


def main() -> None:
    output_path = Path(sys.argv[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(Settings())
    output_path.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
