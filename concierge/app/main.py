"""FastAPI application factory + lifespan. On boot it logs whether the datastores
are reachable; it does not crash if they aren't, so `/health` can report the truth."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import engine, ping_db
from .logging import configure_logging
from .routers import email as email_router
from .routers import health, knowledge, webchat
from .services.redis import get_redis_client, ping_redis

settings = get_settings()
configure_logging(settings.LOG_LEVEL)  # PII-redacting logs (Day 6)
log = logging.getLogger("concierge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting PythaFlow Concierge v%s (env=%s)", settings.APP_VERSION, settings.ENV)
    log.info("db reachable:    %s", await ping_db())
    log.info("redis reachable: %s", await ping_redis())
    yield
    await engine.dispose()
    await get_redis_client().aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="PythaFlow Concierge",
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    # The active brain. Tests override app.state.orchestrator with the echo or a
    # fake, so they never touch the network.
    from .orchestrator.engine import LLMOrchestrator

    app.state.orchestrator = LLMOrchestrator()
    app.include_router(health.router)
    app.include_router(webchat.router)
    app.include_router(knowledge.router)
    app.include_router(email_router.router)
    # The manual test page is a development affordance only — never exposed
    # outside a dev/test environment.
    if settings.ENV.lower() in {"dev", "development", "local", "test"}:
        app.include_router(webchat.dev_router)
        log.info("dev chat page mounted at /dev/chat")
    return app


app = create_app()
