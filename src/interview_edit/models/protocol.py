from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProtocolModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class WarningPayload(ProtocolModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ArtifactReference(ProtocolModel):
    kind: str
    path: str


class ErrorPayload(ProtocolModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class JsonEnvelope(ProtocolModel):
    schema_version: str = Field(default="1", alias="schemaVersion")
    ok: bool
    command: str
    run_id: str | None = Field(default=None, alias="runId")
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[WarningPayload] = Field(default_factory=list)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    next: list[str] = Field(default_factory=list)
    error: ErrorPayload | None = None
