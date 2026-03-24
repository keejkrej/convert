use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use std::error::Error;
use std::io::{self, Write};
use std::path::PathBuf;

use convert_rs::convert::{
    resolve_selection, run_convert, ConvertOptions, ProgressEvent, ProgressPhase,
};

#[derive(Parser, Debug, Clone)]
#[command(
    name = "convert-rs",
    about = "Convert an ND2 file into per-position TIFF folders."
)]
struct Cli {
    /// Path to the .nd2 file to convert.
    #[arg(long)]
    input: PathBuf,

    /// Positions to convert: "all" or comma-separated indices/slices, e.g. "0:5,10".
    #[arg(long)]
    position: String,

    /// Timepoints to convert: "all" or comma-separated indices/slices, e.g. "0:50,100".
    #[arg(long)]
    time: String,

    /// Channels to convert: "all" or comma-separated indices/slices, e.g. "0:2,4".
    #[arg(long)]
    channel: String,

    /// Output directory (will contain Pos*/... TIFF folders).
    #[arg(long)]
    output: PathBuf,

    /// Skip confirmation prompt.
    #[arg(long)]
    yes: bool,
}

struct ProgressReporter {
    bar: Option<ProgressBar>,
    last_done: u64,
}

impl ProgressReporter {
    fn new() -> Self {
        Self {
            bar: None,
            last_done: 0,
        }
    }

    fn handle(&mut self, event: ProgressEvent) {
        match event.phase {
            ProgressPhase::Start => {
                self.last_done = 0;
                let bar = ProgressBar::new(event.total as u64);
                bar.set_style(
                    ProgressStyle::with_template(
                        "{spinner:.green} {msg} [{bar:40.cyan/blue}] {pos}/{len} {percent}% {elapsed_precise}<{eta_precise}",
                    )
                    .unwrap(),
                );
                bar.set_message(event.message);
                self.bar = Some(bar);
            }
            ProgressPhase::Advance => {
                if let Some(bar) = &self.bar {
                    let done = event.done as u64;
                    let delta = done.saturating_sub(self.last_done);
                    if delta > 0 {
                        bar.inc(delta);
                        self.last_done = done;
                    }
                    bar.set_message(event.message);
                }
            }
            ProgressPhase::Finish => {
                if let Some(bar) = self.bar.take() {
                    if (event.done as u64) > self.last_done {
                        bar.inc(event.done as u64 - self.last_done);
                    }
                    bar.finish_and_clear();
                }
                println!("{}", event.message);
            }
        }
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let cli = Cli::parse();
    let options = ConvertOptions {
        input: cli.input,
        position: cli.position,
        time: cli.time,
        channel: cli.channel,
        output: cli.output,
    };

    let selection = resolve_selection(&options)?;
    let total = selection.position_indices.len()
        * selection.time_indices.len()
        * selection.channel_indices.len()
        * selection.info.n_z;

    println!(
        "ND2: {} positions, T={}, C={}, Z={}",
        selection.info.n_pos, selection.info.n_time, selection.info.n_chan, selection.info.n_z
    );
    println!();
    println!(
        "Selected {}/{} positions, {}/{} timepoints, {}/{} channels, {} z-slices",
        selection.position_indices.len(),
        selection.info.n_pos,
        selection.time_indices.len(),
        selection.info.n_time,
        selection.channel_indices.len(),
        selection.info.n_chan,
        selection.info.n_z
    );
    println!("Total frames to write: {}", total);
    println!();
    println!("Positions:");
    println!(
        "  {}",
        selection
            .position_indices
            .iter()
            .map(|idx| format!("Pos{idx}"))
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!();
    println!("Timepoints (original indices):");
    println!("  {:?}", selection.time_indices);
    println!();
    println!("Channels (original indices):");
    println!("  {:?}", selection.channel_indices);
    println!();

    if !cli.yes && !confirm("Proceed with conversion?")? {
        return Err("Aborted".into());
    }

    let mut reporter = ProgressReporter::new();
    run_convert(&options, Some(&mut |event| reporter.handle(event)))?;
    Ok(())
}

fn confirm(prompt: &str) -> io::Result<bool> {
    print!("{prompt} [y/N]: ");
    io::stdout().flush()?;
    let mut line = String::new();
    io::stdin().read_line(&mut line)?;
    Ok(matches!(
        line.trim().to_ascii_lowercase().as_str(),
        "y" | "yes"
    ))
}
