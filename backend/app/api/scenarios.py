"""Scenario CRUD - deliberately just create + list. No update/delete: a
scenario is a label sessions point at, not something v0.2 needs to edit or
retire."""
from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.domain.models import Scenario
from app.persistence import repository as repo

router = APIRouter(prefix='/api/scenarios', tags=['scenarios'])


class ScenarioCreateRequest(BaseModel):
    id: str | None = None
    name: str
    description: str = ''
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post('', status_code=201)
def create_scenario(body: ScenarioCreateRequest, conn: sqlite3.Connection = Depends(get_db)) -> Scenario:
    scenario_id = body.id or str(uuid4())
    if repo.get_scenario(conn, scenario_id) is not None:
        raise HTTPException(status_code=409, detail=f"scenario '{scenario_id}' already exists")
    scenario = Scenario(
        id=scenario_id, name=body.name, description=body.description,
        tags=body.tags, metadata=body.metadata,
    )
    repo.create_scenario(conn, scenario)
    return scenario


@router.get('')
def list_scenarios(conn: sqlite3.Connection = Depends(get_db)) -> list[Scenario]:
    return repo.list_scenarios(conn)
