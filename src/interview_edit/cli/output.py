from __future__ import annotations

import typer

from interview_edit.errors import InterviewEditError
from interview_edit.models.protocol import ErrorPayload, JsonEnvelope


def emit(envelope: JsonEnvelope, *, json_output: bool, human_lines: list[str]) -> None:
    if json_output:
        typer.echo(envelope.model_dump_json(by_alias=True, exclude_none=True))
        return
    for line in human_lines:
        typer.echo(line)


def emit_expected_error(error: InterviewEditError, *, command: str, json_output: bool) -> None:
    details = dict(error.details)
    raw_run_id = details.pop("runId", None)
    run_id = raw_run_id if isinstance(raw_run_id, str) else None
    if json_output:
        envelope = JsonEnvelope(
            ok=False,
            command=command,
            runId=run_id,
            error=ErrorPayload(
                code=error.code,
                message=error.message,
                details=details,
            ),
        )
        typer.echo(envelope.model_dump_json(by_alias=True, exclude_none=True))
    else:
        typer.echo(f"Error [{error.code}]: {error.message}", err=True)
        if run_id is not None:
            typer.echo(f"Run: {run_id}", err=True)
