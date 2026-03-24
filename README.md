# convert

Minimal standalone ND2 to TIFF converter that mirrors the behavior of
`../mupattern/mupattern-py convert`.

## Install

```powershell
uv sync
```

## Usage

```powershell
uv run convert --input sample.nd2 --position all --time all --channel all --output out -y
```

The command writes:

- `Pos{index}` folders inside the output directory
- `time_map.csv` in each position folder
- TIFF files named like `img_channel000_position000_time000000000_z000.tif`
