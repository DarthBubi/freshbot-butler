from __future__ import annotations

import argparse

from sqlalchemy import select

from freshbot_butler.api.db import Database
from freshbot_butler.api.models import Job, PackagePhotoCapture, utc_now
from freshbot_butler.api.services.package_photo import (
    PackagePhotoService,
    create_package_photo_extractor,
)
from freshbot_butler.api.services.reminders import ReminderService
from freshbot_butler.api.settings import Settings


async def process_pending_jobs_once(
    settings: Settings,
    package_photo_extractor=None,
) -> int:
    database = Database(settings)
    await database.create_schema()
    configured_package_photo_extractor = (
        package_photo_extractor
        if package_photo_extractor is not None
        else create_package_photo_extractor(settings)
    )
    try:
        async with database.session() as session:
            expired_captures = (
                await session.execute(
                    select(PackagePhotoCapture).where(
                        PackagePhotoCapture.raw_upload.is_not(None),
                        PackagePhotoCapture.raw_upload_expires_at.is_not(None),
                        PackagePhotoCapture.raw_upload_expires_at <= utc_now(),
                    )
                )
            ).scalars().all()
            for capture in expired_captures:
                capture.raw_upload = None
                capture.raw_upload_filename = None
                capture.raw_upload_content_type = None
                capture.raw_upload_expires_at = None
                if capture.status == "processing":
                    capture.status = "failed"

            if expired_captures:
                await session.commit()

            processed_jobs = 0
            while True:
                job = await session.scalar(
                    select(Job).where(Job.status == "pending").order_by(Job.created_at.asc(), Job.id.asc())
                )
                if job is None:
                    return processed_jobs
                job.started_at = utc_now()
                try:
                    if job.queue_name == "package-photo-extraction":
                        service = PackagePhotoService(session, configured_package_photo_extractor)
                        await service.process_capture(job.payload["capture_id"])
                    elif job.queue_name == "reminder-delivery":
                        await ReminderService(session).process_job(job.payload)
                    job.status = "completed"
                    job.finished_at = utc_now()
                    await session.commit()
                    processed_jobs += 1
                except Exception:
                    job.status = "failed"
                    job.finished_at = utc_now()
                    await session.commit()
                    continue
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Freshbot Butler worker")
    parser.add_argument("--once", action="store_true", help="Process pending jobs until the queue is empty")
    args = parser.parse_args()
    settings = Settings()
    if not args.once:
        raise SystemExit("Only --once is supported for the bootstrap slice.")

    import asyncio

    processed = asyncio.run(process_pending_jobs_once(settings))
    print(f"processed_jobs={processed}")
