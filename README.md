# convert

Dedicated CLI home for format conversion workflows.

This repo now contains two separate packages:

- `python/` – Python CLI package
- `rust/` – Rust CLI package

The reader libraries stay library-only:

- `nd2-rs`
- `czi-rs`

## Python Package

```bash
cd python
uv sync
uv run convert --input sample.nd2 --position all --time all --channel all --output out -y
```

## Rust Package

```bash
cd rust
cargo run -- --input sample.nd2 --position all --time all --channel all --output out --yes
```

Both CLIs currently target the same ND2-to-TIFF workflow and write:

- `Pos{index}` folders inside the output directory
- `time_map.csv` in each position folder
- TIFF files named like `img_channel000_position000_time000000000_z000.tif`
