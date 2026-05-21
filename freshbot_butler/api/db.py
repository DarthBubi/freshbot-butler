from collections.abc import AsyncIterator

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from freshbot_butler.api.models import Base
from freshbot_butler.api.settings import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        connect_args: dict[str, object] = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self._engine = create_async_engine(settings.database_url, connect_args=connect_args)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            if self._engine.dialect.name == "sqlite":
                await connection.run_sync(self._migrate_sqlite_schema)

    async def dispose(self) -> None:
        await self._engine.dispose()

    def session(self) -> AsyncIterator[AsyncSession]:
        return self._session_factory()

    @staticmethod
    def _migrate_sqlite_schema(connection) -> None:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())

        if "batches" in table_names:
            batch_columns = {column["name"] for column in inspector.get_columns("batches")}
            if "quantity_amount" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN quantity_amount INTEGER")
            if "quantity_unit" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN quantity_unit VARCHAR(64)")
            if "lifecycle_state" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN lifecycle_state VARCHAR(32) DEFAULT 'sealed'")
            if "opened_at" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN opened_at DATETIME")
            if "date_type" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN date_type VARCHAR(32)")
            if "expires_on" not in batch_columns:
                connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN expires_on DATE")

        if "households" in table_names:
            household_columns = {column["name"] for column in inspector.get_columns("households")}
            if "daily_digest_enabled" not in household_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE households ADD COLUMN daily_digest_enabled BOOLEAN DEFAULT 1"
                )
            if "urgent_push_enabled" not in household_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE households ADD COLUMN urgent_push_enabled BOOLEAN DEFAULT 0"
                )
