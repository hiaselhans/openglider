use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::fs;

type SourceBbox = (f32, f32, f32, f32);
type RasterRequest = (u32, u32, Option<SourceBbox>);
type UvBbox = (f32, f32, f32, f32);

fn load_svg_tree(file_path: &str) -> PyResult<usvg::Tree> {
    let svg_data = fs::read(file_path)
        .map_err(|err| PyValueError::new_err(format!("failed to read svg file '{}': {}", file_path, err)))?;

    let mut options = usvg::Options::default();
    options.fontdb_mut().load_system_fonts();

    usvg::Tree::from_data(&svg_data, &options)
        .map_err(|err| PyValueError::new_err(format!("failed to parse svg file '{}': {}", file_path, err)))
}

#[pyfunction]
#[pyo3(signature = (file_path, width, height, precision = 1.0, source_bbox = None))]
pub fn render_svg_rgba(
    file_path: String,
    width: u32,
    height: u32,
    precision: f32,
    source_bbox: Option<(f32, f32, f32, f32)>,
) -> PyResult<(u32, u32, Vec<u8>)> {
    let tree = load_svg_tree(&file_path)?;

    let precision = precision.max(0.1);
    let width = ((width as f32) * precision).round().max(1.0) as u32;
    let height = ((height as f32) * precision).round().max(1.0) as u32;
    let mut pixmap = tiny_skia::Pixmap::new(width, height)
        .ok_or_else(|| PyValueError::new_err("failed to allocate svg raster pixmap"))?;

    let source_size = tree.size();
    let (source_x, source_y, source_w, source_h) = source_bbox.unwrap_or((0.0, 0.0, source_size.width(), source_size.height()));
    let source_w = source_w.max(1e-6);
    let source_h = source_h.max(1e-6);
    let scale_x = width as f32 / source_w;
    let scale_y = height as f32 / source_h;
    let transform = usvg::Transform::from_translate(-source_x, -source_y).pre_scale(scale_x, scale_y);
    resvg::render(&tree, transform, &mut pixmap.as_mut());

    Ok((width, height, pixmap.take()))
}

#[pyfunction]
#[pyo3(signature = (file_path, width, height, bboxes, precision = 1.0))]
pub fn render_svg_rgba_bboxes(
    file_path: String,
    width: u32,
    height: u32,
    bboxes: Vec<Option<SourceBbox>>,
    precision: f32,
) -> PyResult<Vec<Option<Vec<u8>>>> {
    let requests: Vec<RasterRequest> = bboxes.into_iter().map(|bbox| (width, height, bbox)).collect();
    render_svg_rgba_batch_requests(file_path, requests, precision)
}

#[pyfunction]
#[pyo3(signature = (file_path, requests, precision = 1.0))]
pub fn render_svg_rgba_batch(
    file_path: String,
    requests: Vec<RasterRequest>,
    precision: f32,
) -> PyResult<Vec<Option<Vec<u8>>>> {
    render_svg_rgba_batch_requests(file_path, requests, precision)
}

#[pyfunction]
#[pyo3(signature = (file_path, width, height, bboxes, precision = 1.0))]
pub fn render_svg_rgba_crop_batch(
    file_path: String,
    width: u32,
    height: u32,
    bboxes: Vec<UvBbox>,
    precision: f32,
) -> PyResult<Vec<Option<(u32, u32, Vec<u8>)>>> {
    let tree = load_svg_tree(&file_path)?;

    let precision = precision.max(0.1);
    let render_width = ((width as f32) * precision).round().max(1.0) as u32;
    let render_height = ((height as f32) * precision).round().max(1.0) as u32;

    let mut pixmap = tiny_skia::Pixmap::new(render_width, render_height)
        .ok_or_else(|| PyValueError::new_err("failed to allocate svg raster pixmap"))?;

    let source_size = tree.size();
    let scale_x = render_width as f32 / source_size.width().max(1e-6);
    let scale_y = render_height as f32 / source_size.height().max(1e-6);
    let transform = usvg::Transform::from_scale(scale_x, scale_y);
    resvg::render(&tree, transform, &mut pixmap.as_mut());

    let source = pixmap.data();
    let row_stride = render_width as usize * 4;

    let mut results: Vec<Option<(u32, u32, Vec<u8>)>> = Vec::with_capacity(bboxes.len());
    for (min_x_in, max_x_in, min_y_in, max_y_in) in bboxes {
        let min_x = min_x_in.clamp(0.0, 1.0);
        let max_x = max_x_in.clamp(0.0, 1.0);
        let min_y = min_y_in.clamp(0.0, 1.0);
        let max_y = max_y_in.clamp(0.0, 1.0);

        if max_x <= min_x || max_y <= min_y {
            results.push(None);
            continue;
        }

        let left = ((min_x * render_width as f32).floor() as u32).min(render_width);
        let right = ((max_x * render_width as f32).ceil() as u32).min(render_width).max(left + 1);
        let top = (((1.0 - max_y) * render_height as f32).floor() as u32).min(render_height);
        let bottom = (((1.0 - min_y) * render_height as f32).ceil() as u32).min(render_height).max(top + 1);

        if right <= left || bottom <= top {
            results.push(None);
            continue;
        }

        let crop_w = right - left;
        let crop_h = bottom - top;
        let mut out = vec![0u8; crop_w as usize * crop_h as usize * 4];

        for row in 0..(crop_h as usize) {
            let src_start = (top as usize + row) * row_stride + left as usize * 4;
            let src_end = src_start + crop_w as usize * 4;
            let dst_start = row * crop_w as usize * 4;
            out[dst_start..(dst_start + crop_w as usize * 4)]
                .copy_from_slice(&source[src_start..src_end]);
        }

        if !out.chunks_exact(4).any(|px| px[3] != 0) {
            results.push(None);
            continue;
        }

        results.push(Some((crop_w, crop_h, out)));
    }

    Ok(results)
}

fn render_svg_rgba_batch_requests(
    file_path: String,
    requests: Vec<RasterRequest>,
    precision: f32,
) -> PyResult<Vec<Option<Vec<u8>>>> {
    let tree = load_svg_tree(&file_path)?;

    let source_size = tree.size();
    let default_bbox = (0.0, 0.0, source_size.width(), source_size.height());
    let precision = precision.max(0.1);

    let mut results: Vec<Option<Vec<u8>>> = Vec::with_capacity(requests.len());

    for (width, height, source_bbox) in requests {
        let width = ((width as f32) * precision).round().max(1.0) as u32;
        let height = ((height as f32) * precision).round().max(1.0) as u32;
        let (source_x, source_y, source_w, source_h) = source_bbox.unwrap_or(default_bbox);

        if source_w <= 0.0 || source_h <= 0.0 {
            results.push(None);
            continue;
        }

        let mut pixmap = match tiny_skia::Pixmap::new(width, height) {
            Some(value) => value,
            None => {
                results.push(None);
                continue;
            }
        };

        let scale_x = width as f32 / source_w;
        let scale_y = height as f32 / source_h;
        let transform = usvg::Transform::from_translate(-source_x, -source_y).pre_scale(scale_x, scale_y);
        resvg::render(&tree, transform, &mut pixmap.as_mut());
        results.push(Some(pixmap.take()));
    }

    Ok(results)
}

#[pymodule]
pub fn svg_mod(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(render_svg_rgba, m)?)?;
    m.add_function(wrap_pyfunction!(render_svg_rgba_bboxes, m)?)?;
    m.add_function(wrap_pyfunction!(render_svg_rgba_batch, m)?)?;
    m.add_function(wrap_pyfunction!(render_svg_rgba_crop_batch, m)?)?;
    Ok(())
}
