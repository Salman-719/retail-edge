import json
from pathlib import Path

PROJECT_FILE = Path('project.json')


def save_project(data: dict) -> None:
    PROJECT_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def load_project() -> dict | None:
    if PROJECT_FILE.exists():
        return json.loads(PROJECT_FILE.read_text(encoding='utf-8'))
    return None
