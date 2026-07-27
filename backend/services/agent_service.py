"""Agent CRUD business logic. No HTTP concerns here — routers call these."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import Agent
from backend.schemas.agent import AgentCreate, AgentUpdate


async def list_agents(db: AsyncSession, tenant_id: uuid.UUID) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    return list(result.scalars().all())


async def create_agent(db: AsyncSession, tenant_id: uuid.UUID, payload: AgentCreate) -> Agent:
    agent = Agent(tenant_id=tenant_id, **payload.model_dump())
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def get_agent(db: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def update_agent(
    db: AsyncSession, agent_id: uuid.UUID, payload: AgentUpdate
) -> Agent | None:
    agent = await get_agent(db, agent_id)
    if not agent:
        return None

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent


async def delete_agent(db: AsyncSession, agent_id: uuid.UUID) -> None:
    agent = await get_agent(db, agent_id)
    if agent:
        await db.delete(agent)
        await db.commit()
