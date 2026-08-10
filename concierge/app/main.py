"""FastAPI application factory + lifespan. On boot it logs whether the datastores
are reachable; it does not crash if they aren't, so `/health` can report the truth."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import SessionLocal, engine, ping_db
from .logging import configure_logging
from .routers import (
    approvals,
    conversations,
    health,
    knowledge,
    stream,
    takeover,
    webchat,
)
from .routers import (
    console_auth as console_router,
)
from .routers import (
    email as email_router,
)
from .routers import (
    whatsapp as whatsapp_router,
)
from .services.redis import get_redis_client, ping_redis

settings = get_settings()
configure_logging(settings.LOG_LEVEL)  # PII-redacting logs (Day 6)
log = logging.getLogger("concierge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting PythaFlow Concierge v%s (env=%s)", settings.APP_VERSION, settings.ENV)
    log.info("db reachable:    %s", await ping_db())
    log.info("redis reachable: %s", await ping_redis())
    # Day 12: start the reminder scheduler as a background task
    reminder_task = asyncio.create_task(_start_reminder_scheduler())
    yield
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    await get_redis_client().aclose()


async def _start_reminder_scheduler():
    """Import and run the reminder scheduler (lazy import to avoid circular deps)."""
    from .reminders import run_scheduler

    redis = get_redis_client()
    await run_scheduler(SessionLocal, redis=redis)


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
    app.include_router(whatsapp_router.router)
    app.include_router(approvals.router)
    # Day 17: staff console — conversations API + SSE stream + the page.
    app.include_router(conversations.router)
    app.include_router(stream.router)
    app.include_router(console_router.router)
    # Day 18: human takeover — staff pause/resume the AI and reply as the venue.
    app.include_router(takeover.router)
    # Day 15: WhatsApp outbound transport — delivers confirmations/reminders
    # over WhatsApp when the conversation's channel is whatsapp.
    from .channels.whatsapp.factory import build_whatsapp_client
    from .channels.whatsapp.transport import WhatsAppTransport
    from .notifications import NOTIF_ESCALATED, NOTIF_MESSAGE_SENT, register_subscriber

    register_subscriber(
        NOTIF_MESSAGE_SENT,
        WhatsAppTransport(
            build_whatsapp_client(),
            template_confirm=settings.WHATSAPP_TEMPLATE_CONFIRM,
            template_reminder=settings.WHATSAPP_TEMPLATE_REMINDER,
        ).handle_event,
    )
    # Day 19: escalation alerts to real channels — chosen per tenant via
    # Tenant.config["notify"]; no-op subscribers when a channel isn't set up.
    from .notifications.email import EmailSubscriber
    from .notifications.slack import SlackSubscriber

    register_subscriber(NOTIF_ESCALATED, SlackSubscriber().handle_event)
    register_subscriber(NOTIF_ESCALATED, EmailSubscriber().handle_event)
    # The manual test page is a development affordance only — never exposed
    # outside a dev/test environment.
    if settings.ENV.lower() in {"dev", "development", "local", "test"}:
        app.include_router(webchat.dev_router)
        log.info("dev chat page mounted at /dev/chat")
    return app


app = create_app()
