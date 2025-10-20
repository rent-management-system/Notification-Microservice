from fastapi import FastAPI, Request, Response, HTTPException
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.core.logging import configure_logging, logger
from app.routers import notifications
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.services.notification import retry_failed_notifications
from fastapi_limiter import FastAPILimiter
from redis.asyncio import Redis
import os

# Configure logging
configure_logging()

# Database setup
engine = create_async_engine(settings.DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# Scheduler setup
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Notification Microservice starting up...")

    # Initialize FastAPI-Limiter
    redis = Redis(host="localhost", port=6379, db=0) # Assuming Redis is running locally or accessible
    await FastAPILimiter.init(redis)
    logger.info("FastAPI-Limiter initialized.")

    # Start scheduler
    scheduler.add_job(
        retry_failed_notifications,
        IntervalTrigger(minutes=5),
        args=[AsyncSessionLocal()], # Pass a new session for the job
        id="retry_failed_notifications_job",
        name="Retry Failed Notifications",
        misfire_grace_time=60 # seconds
    )
    scheduler.start()
    logger.info("Scheduler started.")

    yield

    logger.info("Notification Microservice shutting down...")
    # Shut down scheduler
    scheduler.shutdown()
    logger.info("Scheduler shut down.")

    # Close FastAPI-Limiter
    await FastAPILimiter.close()
    logger.info("FastAPI-Limiter closed.")

app = FastAPI(lifespan=lifespan, title="Notification Microservice", version="1.0.0")

app.include_router(notifications.router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
