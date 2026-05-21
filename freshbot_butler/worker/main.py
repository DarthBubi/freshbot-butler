from __future__ import annotations

import argparse

from sqlalchemy import select

from freshbot_butler.api.db import Database
from freshbot_butler.api.models import Job, utc_now
from freshbot_butler.api.services.package_photo import DemoPackagePhotoExtractor, PackagePhotoExtractor, PackagePhotoService
from freshbot_butler.api.settings import Settings


async def process_pending_jobs_once(
    settings: Settings,
    package_photo_extractor: PackagePhotoExtractor | None = None,
) -> int:
    database = Database(settings)
    await database.create_schema()
    async with database.session() as session:
        job = await session.scalar(
            select(Job).where(Job.status == "pending").order_by(Job.created_at.asc())
        )
        if job is None:
            await database.dispose()
            return 0
        job.started_at = utc_now()
        if job.queue_name == "package-photo-extraction":
            service = PackagePhotoService(session, package_photo_extractor or DemoPackagePhotoExtractor())
            await service.process_capture(job.payload["capture_id"])
        job.status = "completed"
        job.finished_at = utc_now()
        await session.commit()
    await database.dispose()
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Freshbot Butler worker")
    parser.add_argument("--once", action="store_true", help="Process a single pending job")
    args = parser.parse_args()
    settings = Settings()
    if not args.once:
        raise SystemExit("Only --once is supported for the bootstrap slice.")

    import asyncio

    processed = asyncio.run(process_pending_jobs_once(settings))
    print(f"processed_jobs={processed}")
