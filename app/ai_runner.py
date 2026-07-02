from app.claude_runner import generate_with_claude
from app.openai_runner import generate_with_openai
from app.novelcraft_runner import generate_with_novelcraft


AI_PROVIDER_REGISTRY = {
    "claude": {
        "label": "Claude",
        "implemented": True,
        "handler": generate_with_claude,
    },
    "openai": {
        "label": "OpenAI",
        "implemented": False,
        "handler": generate_with_openai,
    },
    "novelcraft": {
        "label": "NovelCraft",
        "implemented": False,
        "handler": generate_with_novelcraft,
    },
}


def get_available_ai_providers() -> list[dict]:
    """
    Return provider capability metadata for UI/controller layers.
    """
    providers = []

    for provider_id, meta in AI_PROVIDER_REGISTRY.items():
        providers.append(
            {
                "provider_id": provider_id,
                "label": meta["label"],
                "implemented": meta["implemented"],
            }
        )

    return providers


def generate_with_ai(prompt: str, provider: str = "claude") -> str:
    """
    Neutral AI dispatch layer.
    """
    provider = provider.strip().lower()

    if provider not in AI_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported AI provider: {provider}")

    provider_meta = AI_PROVIDER_REGISTRY[provider]

    if not provider_meta["implemented"]:
        raise NotImplementedError(f"{provider_meta['label']} provider is not implemented yet.")

    handler = provider_meta["handler"]
    return handler(prompt)