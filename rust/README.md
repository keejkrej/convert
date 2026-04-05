# convert-rs

Rust CLI package for standalone ND2 to TIFF conversion.

This package is intended for co-development with the sibling `nd2-rs` repo and
uses it via a local path dependency in this workspace layout.

## Usage

```bash
cargo run -- --input sample.nd2 --position all --time all --channel all --output out --yes
```
