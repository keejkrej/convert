use std::collections::HashSet;

/// Parse slice expressions like "all", "1,3", "0:10:2".
/// Semantics mirror Python's slice.indices(length).
pub fn parse_slice_string(s: &str, length: usize) -> Result<Vec<usize>, String> {
    let s = s.trim();
    if s.eq_ignore_ascii_case("all") {
        return Ok((0..length).collect());
    }

    let len = length as isize;
    let mut indices = HashSet::new();

    for segment in s.split(',') {
        let segment = segment.trim();
        if segment.is_empty() {
            continue;
        }

        if segment.contains(':') {
            let parts: Vec<Option<isize>> = segment
                .split(':')
                .map(|part| {
                    let part = part.trim();
                    if part.is_empty() {
                        Ok(None)
                    } else {
                        part.parse::<isize>()
                            .map(Some)
                            .map_err(|_| format!("Invalid slice segment: {segment:?}"))
                    }
                })
                .collect::<Result<_, _>>()?;

            if parts.len() > 3 {
                return Err(format!("Invalid slice segment: {segment:?}"));
            }

            let step = parts.get(2).copied().flatten().unwrap_or(1);
            if step == 0 {
                return Err(format!("Slice step cannot be zero: {segment:?}"));
            }

            let default_start = if step < 0 { len - 1 } else { 0 };
            let default_stop = if step < 0 { -1 } else { len };
            let start = parts.get(0).copied().flatten().unwrap_or(default_start);
            let stop = parts.get(1).copied().flatten().unwrap_or(default_stop);
            let (start, stop, step) = slice_indices(start, stop, step, len);

            let mut idx = start;
            while (step > 0 && idx < stop) || (step < 0 && idx > stop) {
                indices.insert(idx as usize);
                idx += step;
            }
        } else {
            let idx: isize = segment
                .parse()
                .map_err(|_| format!("Invalid slice segment: {segment:?}"))?;
            if idx < -len || idx >= len {
                return Err(format!("Index {idx} out of range for length {length}"));
            }
            let normalized = if idx < 0 { idx + len } else { idx };
            indices.insert(normalized as usize);
        }
    }

    if indices.is_empty() {
        return Err(format!("Slice string {s:?} produced no indices"));
    }

    let mut out: Vec<_> = indices.into_iter().collect();
    out.sort_unstable();
    Ok(out)
}

fn slice_indices(start: isize, stop: isize, step: isize, length: isize) -> (isize, isize, isize) {
    debug_assert!(step != 0);

    if step > 0 {
        let mut start = normalize_bound(start, length);
        let mut stop = normalize_bound(stop, length);
        start = start.clamp(0, length);
        stop = stop.clamp(0, length);
        (start, stop, step)
    } else {
        let mut start = normalize_bound_negative(start, length);
        let mut stop = normalize_bound_negative(stop, length);
        start = start.clamp(-1, length - 1);
        stop = stop.clamp(-1, length - 1);
        (start, stop, step)
    }
}

fn normalize_bound(value: isize, length: isize) -> isize {
    if value < 0 {
        value + length
    } else {
        value
    }
}

fn normalize_bound_negative(value: isize, length: isize) -> isize {
    if value < 0 {
        value + length
    } else {
        value
    }
}

#[cfg(test)]
mod tests {
    use super::parse_slice_string;

    #[test]
    fn parses_all() {
        assert_eq!(parse_slice_string("all", 4).unwrap(), vec![0, 1, 2, 3]);
    }

    #[test]
    fn parses_indices_and_ranges() {
        assert_eq!(
            parse_slice_string("0:5, 7, 2", 10).unwrap(),
            vec![0, 1, 2, 3, 4, 7]
        );
    }

    #[test]
    fn parses_negative_indices() {
        assert_eq!(parse_slice_string("-1,-3", 5).unwrap(), vec![2, 4]);
    }

    #[test]
    fn rejects_empty_result() {
        assert!(parse_slice_string("10:10", 10).is_err());
    }

    #[test]
    fn rejects_zero_step() {
        assert!(parse_slice_string("0:10:0", 10).is_err());
    }
}
