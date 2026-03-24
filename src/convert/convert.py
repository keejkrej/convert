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


@dataclass(frozen=True)
class FrameLookup:
    sequence_axes: tuple[str, ...]
    index_by_coords: dict[tuple[int, ...], int]


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


def build_frame_lookup(handle) -> FrameLookup:
    """Build a lookup from ND2 loop coordinates to sequence frame index."""
    loop_indices = tuple(handle.loop_indices)
    if not loop_indices:
        return FrameLookup(sequence_axes=(), index_by_coords={(): 0})

    sequence_axes = tuple(
        axis
        for axis in ("P", "T", "C", "Z")
        if any(axis in frame_indices for frame_indices in loop_indices)
    )
    index_by_coords = {
        tuple(frame_indices.get(axis, 0) for axis in sequence_axes): seq_index
        for seq_index, frame_indices in enumerate(loop_indices)
    }
    return FrameLookup(sequence_axes=sequence_axes, index_by_coords=index_by_coords)


def read_frame_2d(handle, lookup: FrameLookup, p: int, t: int, c: int, z: int) -> np.ndarray:
    """Read a 2D YxX frame at the given P/T/C/Z coordinate."""
    coords = {"P": p, "T": t, "C": c, "Z": z}
    seq_key = tuple(coords[axis] for axis in lookup.sequence_axes)
    if seq_key not in lookup.index_by_coords:
        raise ValueError(
            f"No ND2 frame found for coordinates P={p}, T={t}, C={c}, Z={z}"
        )

    seq_index = lookup.index_by_coords[seq_key]
    frame = handle.read_frame(seq_index)
    frame = np.asarray(frame)

    if "C" not in lookup.sequence_axes and handle.sizes.get("C", 1) > 1:
        if frame.ndim >= 3 and frame.shape[0] == handle.sizes["C"]:
            frame = frame[c]
        elif frame.ndim >= 3 and frame.shape[-1] == handle.sizes["C"]:
            frame = frame[..., c]
        else:
            raise ValueError(
                "Unable to locate the channel axis in ND2 frame data for in-pixel channels"
            )

    if frame.ndim == 3 and frame.shape[0] == 1:
        frame = frame[0]
    elif frame.ndim == 3 and frame.shape[-1] == 1:
        frame = frame[..., 0]

    return np.asarray(frame)


def write_tiff(path: Path, frame: np.ndarray) -> None:
    """Write a TIFF, replacing an existing file first for robust reruns on Windows."""
    import tifffile

    if path.exists():
        path.unlink()
    tifffile.imwrite(str(path), frame)


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

    handle = nd2.ND2File(str(input_nd2))
    try:
        sizes = handle.sizes
        n_pos = sizes.get("P", 1)
        n_time = sizes.get("T", 1)
        n_chan = sizes.get("C", 1)
        n_z = sizes.get("Z", 1)
        frame_lookup = build_frame_lookup(handle)

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
                        frame = read_frame_2d(handle, frame_lookup, p_idx, t_orig, c_orig, z)
                        filename = (
                            f"img_channel{c_orig:03d}"
                            f"_position{p_idx:03d}"
                            f"_time{t_new:09d}"
                            f"_z{z:03d}.tif"
                        )
                        write_tiff(pos_dir / filename, frame)
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


class _FakeHandle:
    def __init__(self, sizes: dict[str, int], loop_indices: tuple[dict[str, int], ...], frames: list[np.ndarray]):
        self.sizes = sizes
        self.loop_indices = loop_indices
        self._frames = frames

    def read_frame(self, index: int) -> np.ndarray:
        return self._frames[index]


def test_build_frame_lookup_omits_in_pixel_channel() -> None:
    handle = _FakeHandle(
        sizes={"P": 1, "T": 2, "C": 2, "Z": 1, "Y": 3, "X": 4},
        loop_indices=({"T": 0}, {"T": 1}),
        frames=[
            np.arange(24, dtype=np.uint16).reshape(2, 3, 4),
            np.arange(24, 48, dtype=np.uint16).reshape(2, 3, 4),
        ],
    )

    lookup = build_frame_lookup(handle)

    assert lookup.sequence_axes == ("T",)
    assert lookup.index_by_coords == {(0,): 0, (1,): 1}


def test_read_frame_2d_extracts_in_pixel_channel() -> None:
    handle = _FakeHandle(
        sizes={"P": 1, "T": 1, "C": 2, "Z": 1, "Y": 2, "X": 3},
        loop_indices=({},),
        frames=[np.array([[[1, 2, 3], [4, 5, 6]], [[10, 11, 12], [13, 14, 15]]], dtype=np.uint16)],
    )

    lookup = build_frame_lookup(handle)
    frame = read_frame_2d(handle, lookup, 0, 0, 1, 0)

    np.testing.assert_array_equal(frame, np.array([[10, 11, 12], [13, 14, 15]], dtype=np.uint16))


def test_read_frame_2d_uses_channel_in_sequence_lookup() -> None:
    handle = _FakeHandle(
        sizes={"P": 1, "T": 1, "C": 2, "Z": 1, "Y": 2, "X": 2},
        loop_indices=({"C": 0}, {"C": 1}),
        frames=[
            np.array([[1, 2], [3, 4]], dtype=np.uint16),
            np.array([[5, 6], [7, 8]], dtype=np.uint16),
        ],
    )

    lookup = build_frame_lookup(handle)
    frame = read_frame_2d(handle, lookup, 0, 0, 1, 0)

    np.testing.assert_array_equal(frame, np.array([[5, 6], [7, 8]], dtype=np.uint16))
