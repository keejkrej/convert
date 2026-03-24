"""ND2 to TIFF conversion core."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .slices import parse_slice_string


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    done: int
    total: int
    message: str


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(frozen=True)
class ND2Info:
    n_pos: int
    n_time: int
    n_chan: int
    n_z: int


def emit_progress(
    callback: ProgressCallback | None,
    *,
    phase: str,
    done: int,
    total: int,
    message: str,
) -> None:
    """Route a structured progress event to the configured callback."""
    if callback is None:
        return
    callback(ProgressEvent(phase=phase, done=done, total=total, message=message))


def inspect_nd2(input_nd2: Path) -> ND2Info:
    """Read ND2 dimensions without converting frames."""
    import nd2

    handle = nd2.ND2File(str(input_nd2))
    try:
        sizes = handle.sizes
        return ND2Info(
            n_pos=sizes.get("P", 1),
            n_time=sizes.get("T", 1),
            n_chan=sizes.get("C", 1),
            n_z=sizes.get("Z", 1),
        )
    finally:
        handle.close()


def resolve_selection(
    input_nd2: Path,
    position_slice: str,
    time_slice: str,
    channel_slice: str,
) -> tuple[ND2Info, list[int], list[int], list[int]]:
    """Load ND2 metadata and resolve selected positions and timepoints."""
    info = inspect_nd2(input_nd2)
    pos_indices = parse_slice_string(position_slice, info.n_pos)
    time_indices = parse_slice_string(time_slice, info.n_time)
    channel_indices = parse_slice_string(channel_slice, info.n_chan)
    return info, pos_indices, time_indices, channel_indices


def read_frame_2d(handle, p: int, t: int, c: int, z: int) -> np.ndarray:
    """Read a 2D YxX frame at the given P/T/C/Z coordinate."""
    sizes = handle.sizes
    dim_order = [dim for dim in sizes.keys() if dim not in ("Y", "X")]
    coord_shape = tuple(sizes[dim] for dim in dim_order)
    idx = tuple({"P": p, "T": t, "C": c, "Z": z}.get(dim, 0) for dim in dim_order)
    seq_index = int(np.ravel_multi_index(idx, coord_shape))
    frame = handle.read_frame(seq_index)
    if frame.ndim == 3:
        return frame[0]
    return np.asarray(frame)


def run_convert(
    input_nd2: Path,
    position_slice: str,
    time_slice: str,
    channel_slice: str,
    output: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Convert an ND2 file into per-position TIFF folders."""
    import nd2
    import tifffile

    handle = nd2.ND2File(str(input_nd2))
    try:
        sizes = handle.sizes
        n_pos = sizes.get("P", 1)
        n_time = sizes.get("T", 1)
        n_chan = sizes.get("C", 1)
        n_z = sizes.get("Z", 1)

        pos_indices = parse_slice_string(position_slice, n_pos)
        time_indices = parse_slice_string(time_slice, n_time)
        channel_indices = parse_slice_string(channel_slice, n_chan)

        total = len(pos_indices) * len(time_indices) * len(channel_indices) * n_z
        emit_progress(
            on_progress,
            phase="start",
            done=0,
            total=total,
            message=(
                f"Selected {len(pos_indices)} positions, {len(time_indices)} timepoints, "
                f"{len(channel_indices)} channels, {n_z} z-slices. Total frames: {total}"
            ),
        )

        output.mkdir(parents=True, exist_ok=True)

        done = 0
        for p_idx in pos_indices:
            pos_dir = output / f"Pos{p_idx}"
            pos_dir.mkdir(exist_ok=True)

            with open(pos_dir / "time_map.csv", "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["t", "t_real"])
                for t_new, t_orig in enumerate(time_indices):
                    writer.writerow([t_new, t_orig])

            for t_new, t_orig in enumerate(time_indices):
                for c_orig in channel_indices:
                    for z in range(n_z):
                        frame = read_frame_2d(handle, p_idx, t_orig, c_orig, z)
                        filename = (
                            f"img_channel{c_orig:03d}"
                            f"_position{p_idx:03d}"
                            f"_time{t_new:09d}"
                            f"_z{z:03d}.tif"
                        )
                        tifffile.imwrite(str(pos_dir / filename), frame)
                        done += 1

                        emit_progress(
                            on_progress,
                            phase="advance",
                            done=done,
                            total=total,
                            message="Writing TIFFs",
                        )

        emit_progress(
            on_progress,
            phase="finish",
            done=done,
            total=total,
            message=f"Wrote {output}",
        )
    finally:
        handle.close()
