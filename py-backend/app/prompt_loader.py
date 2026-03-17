from __future__ import annotations

from app.config import settings


def render_prompt(template_name: str, **kwargs) -> str:
    template_path = settings.prompts_dir / template_name
    text = template_path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
