use nd2_rs::Nd2File;
use std::fmt::{Display, Formatter};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use tiff::encoder::{colortype::Gray16, TiffEncoder};

use crate::slices::parse_slice_string;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgressPhase {
    Start,
    Advance,
    Finish,
}

#[derive(Debug, Clone)]
pub struct ProgressEvent {
    pub phase: ProgressPhase,
    pub done: usize,
    pub total: usize,
    pub message: String,
}

#[derive(Debug, Clone, Copy)]
pub struct Nd2Info {
    pub n_pos: usize,
    pub n_time: usize,
    pub n_chan: usize,
    pub n_z: usize,
    pub width: usize,
    pub height: usize,
}

#[derive(Debug, Clone)]
pub struct ConversionSelection {
    pub info: Nd2Info,
    pub position_indices: Vec<usize>,
    pub time_indices: Vec<usize>,
    pub channel_indices: Vec<usize>,
}

#[derive(Debug, Clone)]
pub struct ConvertOptions {
    pub input: PathBuf,
    pub position: String,
    pub time: String,
    pub channel: String,
    pub output: PathBuf,
}

#[derive(Debug)]
pub enum ConvertError {
    Io(std::io::Error),
    Nd2(nd2_rs::Nd2Error),
    Slice(String),
    Tiff(tiff::TiffError),
}

impl Display for ConvertError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(err) => write!(f, "{err}"),
            Self::Nd2(err) => write!(f, "{err}"),
            Self::Slice(err) => write!(f, "{err}"),
            Self::Tiff(err) => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for ConvertError {}

impl From<std::io::Error> for ConvertError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<nd2_rs::Nd2Error> for ConvertError {
    fn from(value: nd2_rs::Nd2Error) -> Self {
        Self::Nd2(value)
    }
}

impl From<tiff::TiffError> for ConvertError {
    fn from(value: tiff::TiffError) -> Self {
        Self::Tiff(value)
    }
}

pub fn inspect_nd2(input: &Path) -> Result<Nd2Info, ConvertError> {
    let mut nd2 = Nd2File::open(input)?;
    let sizes = nd2.sizes()?;
    Ok(Nd2Info {
        n_pos: *sizes.get("P").unwrap_or(&1),
        n_time: *sizes.get("T").unwrap_or(&1),
        n_chan: *sizes.get("C").unwrap_or(&1),
        n_z: *sizes.get("Z").unwrap_or(&1),
        height: *sizes.get("Y").unwrap_or(&1),
        width: *sizes.get("X").unwrap_or(&1),
    })
}

pub fn resolve_selection(options: &ConvertOptions) -> Result<ConversionSelection, ConvertError> {
    let info = inspect_nd2(&options.input)?;
    let position_indices =
        parse_slice_string(&options.position, info.n_pos).map_err(ConvertError::Slice)?;
    let time_indices =
        parse_slice_string(&options.time, info.n_time).map_err(ConvertError::Slice)?;
    let channel_indices =
        parse_slice_string(&options.channel, info.n_chan).map_err(ConvertError::Slice)?;

    Ok(ConversionSelection {
        info,
        position_indices,
        time_indices,
        channel_indices,
    })
}

pub fn run_convert<F>(
    options: &ConvertOptions,
    mut on_progress: Option<&mut F>,
) -> Result<(), ConvertError>
where
    F: FnMut(ProgressEvent),
{
    let selection = resolve_selection(options)?;
    let total = selection.position_indices.len()
        * selection.time_indices.len()
        * selection.channel_indices.len()
        * selection.info.n_z;

    emit_progress(
        on_progress.as_deref_mut(),
        ProgressPhase::Start,
        0,
        total,
        format!(
            "Selected {} positions, {} timepoints, {} channels, {} z-slices. Total frames: {}",
            selection.position_indices.len(),
            selection.time_indices.len(),
            selection.channel_indices.len(),
            selection.info.n_z,
            total
        ),
    );

    fs::create_dir_all(&options.output)?;

    let mut nd2 = Nd2File::open(&options.input)?;
    let mut done = 0usize;

    for &p_idx in &selection.position_indices {
        let pos_dir = options.output.join(format!("Pos{p_idx}"));
        fs::create_dir_all(&pos_dir)?;
        write_time_map(&pos_dir, &selection.time_indices)?;

        for (t_new, &t_orig) in selection.time_indices.iter().enumerate() {
            for &c_orig in &selection.channel_indices {
                for z in 0..selection.info.n_z {
                    let frame = nd2.read_frame_2d(p_idx, t_orig, c_orig, z)?;
                    let filename = format!(
                        "img_channel{c_orig:03}_position{p_idx:03}_time{t_new:09}_z{z:03}.tif"
                    );
                    write_tiff(
                        &pos_dir.join(filename),
                        selection.info.width,
                        selection.info.height,
                        &frame,
                    )?;
                    done += 1;
                    emit_progress(
                        on_progress.as_deref_mut(),
                        ProgressPhase::Advance,
                        done,
                        total,
                        "Writing TIFFs".to_owned(),
                    );
                }
            }
        }
    }

    emit_progress(
        on_progress.as_deref_mut(),
        ProgressPhase::Finish,
        done,
        total,
        format!("Wrote {}", options.output.display()),
    );

    Ok(())
}

fn emit_progress(
    progress: Option<&mut impl FnMut(ProgressEvent)>,
    phase: ProgressPhase,
    done: usize,
    total: usize,
    message: String,
) {
    if let Some(callback) = progress {
        callback(ProgressEvent {
            phase,
            done,
            total,
            message,
        });
    }
}

fn write_time_map(pos_dir: &Path, time_indices: &[usize]) -> Result<(), ConvertError> {
    let mut csv = BufWriter::new(File::create(pos_dir.join("time_map.csv"))?);
    writeln!(csv, "t,t_real")?;
    for (t_new, &t_orig) in time_indices.iter().enumerate() {
        writeln!(csv, "{t_new},{t_orig}")?;
    }
    csv.flush()?;
    Ok(())
}

fn write_tiff(
    path: &Path,
    width: usize,
    height: usize,
    pixels: &[u16],
) -> Result<(), ConvertError> {
    if path.exists() {
        fs::remove_file(path)?;
    }
    let file = File::create(path)?;
    let mut writer = BufWriter::new(file);
    let mut encoder = TiffEncoder::new(&mut writer)?;
    encoder.write_image::<Gray16>(width as u32, height as u32, pixels)?;
    writer.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{write_tiff, write_time_map};

    #[test]
    fn writes_time_map() {
        let dir = tempfile::tempdir().unwrap();
        write_time_map(dir.path(), &[3, 5, 8]).unwrap();
        let csv = std::fs::read_to_string(dir.path().join("time_map.csv")).unwrap();
        assert_eq!(csv, "t,t_real\n0,3\n1,5\n2,8\n");
    }

    #[test]
    fn overwrites_existing_tiff() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("frame.tif");
        std::fs::write(&path, b"stale").unwrap();

        write_tiff(&path, 2, 2, &[1, 2, 3, 4]).unwrap();

        assert!(path.exists());
        assert!(std::fs::metadata(&path).unwrap().len() > 5);
    }
}
