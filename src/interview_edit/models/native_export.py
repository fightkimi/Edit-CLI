from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NativeExportJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    job_id: str = Field(pattern=r"^native_[a-f0-9]{32}$")
    project_id: str
    export_id: str
    package_path: str
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    installed_draft: str | None = None
    installed_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    backend: Literal["manual", "windows-legacy"] = "manual"
    state: Literal["planned", "running", "succeeded", "failed"] = "planned"
    expected_duration_us: int = Field(gt=0, strict=True)
    output_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    output_check_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = None
    native_validation: Literal["not_run"] = "not_run"
    created_at: str

    @model_validator(mode="after")
    def terminal_evidence(self) -> "NativeExportJob":
        if self.state == "succeeded" and (not self.output_sha256 or not self.output_check_sha256):
            raise ValueError("Completion requires an output digest.")
        if self.backend == "windows-legacy" and (
            not self.installed_draft or not self.installed_sha256
        ):
            raise ValueError("Automatic export requires a bound installed draft.")
        return self
