"""Day-1 LLM smoke test.

Exercises the entire seam end to end:
    app core -> LLMService -> provider wrapper -> vendor API (NVIDIA by default)

Run:  uv run python scripts/check_llm.py
"""
import asyncio
import sys
from pathlib import Path

# Allow running as a plain script (`python scripts/check_llm.py`) from the
# project root by putting that root on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm.factory import build_llm_service  # noqa: E402


async def main() -> int:
    s = get_settings()
    print(f"provider={s.LLM_PROVIDER}  model_fast={s.LLM_MODEL_FAST}")

    if not s.LLM_API_KEY:
        print(
            "\n✗ LLM_API_KEY is not set.\n"
            "  Add your NVIDIA key to concierge/.env (get a free one at build.nvidia.com):\n"
            "      LLM_PROVIDER=nvidia\n"
            "      LLM_API_KEY=nvapi-xxxxxxxx\n"
            "  Then re-run:  uv run python scripts/check_llm.py"
        )
        return 1

    if " " in s.LLM_API_KEY or s.LLM_API_KEY.startswith("#"):
        print(
            "\n✗ LLM_API_KEY looks malformed (contains a space or a '#').\n"
            "  Make sure the key is alone on its line in .env, with no trailing comment."
        )
        return 1

    svc = None
    try:
        svc = build_llm_service(s)  # construction can raise too — keep it inside
        reply = await svc.generate(
            "Reply with exactly the single word: PONG",
            tier="fast",
            system="You are a health check. Reply with one word only.",
        )
        print(f"✓ {svc.provider_name} replied: {reply!r}")
        return 0
    except Exception as e:  # noqa: BLE001 - smoke test reports any failure
        print(f"✗ LLM call failed: {type(e).__name__}: {e}")
        return 2
    finally:
        if svc is not None:
            await svc.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
