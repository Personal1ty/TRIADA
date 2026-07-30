from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.swarm import SwarmContract
from app.persistence.models import Base, SwarmContractVersion

_sqlite_contract_tables_ready: set[str] = set()


class SwarmContractRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_default(self, contract: SwarmContract) -> None:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            existing = await session.get(SwarmContractVersion, contract.contract_version)
            if existing is not None:
                return
            has_active = await session.scalar(
                select(SwarmContractVersion.contract_version).where(SwarmContractVersion.is_active.is_(True)).limit(1)
            )
            session.add(
                SwarmContractVersion(
                    contract_version=contract.contract_version,
                    contract=contract.model_dump(mode="json"),
                    is_active=has_active is None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    metadata_={"source": "default_seed"},
                )
            )
            await session.commit()

    async def list_versions(self) -> tuple[str, list[str], list[dict]]:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(SwarmContractVersion).order_by(SwarmContractVersion.contract_version)
                    )
                ).all()
            )
            active_version = await session.scalar(
                select(SwarmContractVersion.contract_version)
                .where(SwarmContractVersion.is_active.is_(True))
                .order_by(SwarmContractVersion.updated_at.desc(), SwarmContractVersion.contract_version.desc())
                .limit(1)
            )
        versions = [str(row.contract_version) for row in rows]
        details = [
            {
                "contract_version": str(row.contract_version),
                "is_active": bool(row.is_active),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "metadata": row.metadata_,
            }
            for row in rows
        ]
        return str(active_version or ""), versions, details

    async def get_contract(self, version: str | None = None) -> SwarmContract | None:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            if version is None:
                row = (
                    await session.scalars(
                        select(SwarmContractVersion)
                        .where(SwarmContractVersion.is_active.is_(True))
                        .order_by(SwarmContractVersion.updated_at.desc(), SwarmContractVersion.contract_version.desc())
                        .limit(1)
                    )
                ).first()
            else:
                row = await session.get(SwarmContractVersion, version)
        if row is None:
            return None
        return SwarmContract.model_validate(row.contract)

    async def save_contract(
        self,
        contract: SwarmContract,
        *,
        activate: bool = True,
        metadata: dict | None = None,
    ) -> SwarmContract:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            now = datetime.now(UTC)
            if activate:
                await session.execute(update(SwarmContractVersion).values(is_active=False, updated_at=now))
            existing = await session.get(SwarmContractVersion, contract.contract_version)
            metadata_payload = {"source": "api", **(metadata or {})}
            if existing is None:
                session.add(
                    SwarmContractVersion(
                        contract_version=contract.contract_version,
                        contract=contract.model_dump(mode="json"),
                        is_active=activate,
                        created_at=now,
                        updated_at=now,
                        metadata_=metadata_payload,
                    )
                )
            else:
                existing.contract = contract.model_dump(mode="json")
                existing.is_active = activate
                existing.updated_at = now
                existing.metadata_ = metadata_payload
            await session.commit()
        return contract

    async def _ensure_sqlite_tables(self) -> None:
        bind = self._session_factory.kw.get("bind")
        if bind is None or not bind.url.drivername.startswith("sqlite"):
            return
        engine_key = str(bind.url)
        if engine_key in _sqlite_contract_tables_ready:
            return
        async with bind.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        _sqlite_contract_tables_ready.add(engine_key)
