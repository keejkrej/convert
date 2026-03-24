"""CLI entrypoint for the standalone ND2 converter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from .convert import ProgressEvent, resolve_selection, run_convert

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    help="Convert an ND2 file into per-position TIFF folders.",
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


class RichProgressReporter:
    def __init__(self) -> None:
        self._console = Console(stderr=True)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
            transient=False,
        )
        self._task_id: TaskID | None = None
        self._last_done = 0

    def __call__(self, event: ProgressEvent) -> None:
        if event.phase == "start":
            self._last_done = 0
            self._progress.start()
            self._task_id = self._progress.add_task(event.message, total=event.total)
            return

        if self._task_id is None:
            self._progress.start()
            self._task_id = self._progress.add_task(event.message, total=event.total)

        increment = max(0, event.done - self._last_done)
        if increment:
            self._progress.update(self._task_id, advance=increment, description=event.message)
            self._last_done = event.done

        if event.phase == "finish":
            self._progress.update(self._task_id, completed=event.done, description=event.message)
            self._progress.stop()
            self._task_id = None
            sys.stdout.write(f"{event.message}\n")


@app.callback()
def convert(
    input: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            dir_okay=False,
            help="Path to the .nd2 file to convert.",
        ),
    ],
    position: Annotated[
        str,
        typer.Option(
            "--position",
            help='Positions to convert: "all" or comma-separated indices/slices, e.g. "0:5,10".',
        ),
    ],
    time: Annotated[
        str,
        typer.Option(
            "--time",
            help='Timepoints to convert: "all" or comma-separated indices/slices, e.g. "0:50,100".',
        ),
    ],
    channel: Annotated[
        str,
        typer.Option(
            "--channel",
            help='Channels to convert: "all" or comma-separated indices/slices, e.g. "0:2,4".',
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Output directory (will contain Pos*/... TIFF folders).",
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    try:
        info, pos_indices, time_indices, channel_indices = resolve_selection(
            input,
            position,
            time,
            channel,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    total = len(pos_indices) * len(time_indices) * len(channel_indices) * info.n_z

    typer.echo(f"ND2: {info.n_pos} positions, T={info.n_time}, C={info.n_chan}, Z={info.n_z}")
    typer.echo("")
    typer.echo(
        f"Selected {len(pos_indices)}/{info.n_pos} positions, "
        f"{len(time_indices)}/{info.n_time} timepoints, "
        f"{len(channel_indices)}/{info.n_chan} channels, {info.n_z} z-slices"
    )
    typer.echo(f"Total frames to write: {total}")
    typer.echo("")
    typer.echo("Positions:")
    typer.echo(f"  {', '.join(f'Pos{i}' for i in pos_indices)}")
    typer.echo("")
    typer.echo("Timepoints (original indices):")
    typer.echo(f"  {time_indices}")
    typer.echo("")
    typer.echo("Channels (original indices):")
    typer.echo(f"  {channel_indices}")
    typer.echo("")

    if not yes and not typer.confirm("Proceed with conversion?"):
        raise typer.Abort()

    progress = RichProgressReporter()
    try:
        run_convert(
            input,
            position,
            time,
            channel,
            output,
            on_progress=progress,
        )
    except ValueError as exc:
        sys.stderr.write("\n")
        sys.stderr.write(f"Error: {exc}\n")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        sys.stderr.write("Interrupted.\n")
        raise typer.Exit(code=130) from None

    sys.stderr.write("\n")


def main() -> None:
    app(prog_name="convert")
