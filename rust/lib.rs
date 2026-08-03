use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

mod mesh;
mod plane;
mod spline;
mod svg;
mod voronoi;
mod vector;
mod cell;
mod wgpu_renderer;

#[pyfunction]
#[pyo3(signature = (a, b, c))]
fn triangle_area(a: f64, b: f64, c: f64) -> PyResult<f64> {
    let semi_perimeter = (a + b + c) / 2.0;
    let area_squared = semi_perimeter
        * (semi_perimeter - a)
        * (semi_perimeter - b)
        * (semi_perimeter - c);

    if area_squared.is_sign_negative() {
        return Err(PyValueError::new_err("invalid triangle side lengths"));
    }

    Ok(area_squared.sqrt())
}

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule(name = "rs")]
mod rs {
    #[pymodule_export]
    use super::triangle_area;
    #[pymodule_export]
    use super::version;
    #[pymodule_export]
    use crate::cell::basic_cell_midrib;
    #[pymodule_export]
    use crate::cell::flatten_midribs;
    #[pymodule_export]
    use crate::mesh::find_duplicates;
    #[pymodule_export]
    use crate::mesh::mesh_mod as mesh;
    #[pymodule_export]
    use crate::plane::plane_mod as plane;
    #[pymodule_export]
    use crate::spline::spline_mod as spline;
    #[pymodule_export]
    use crate::svg::svg_mod as svg;
    #[pymodule_export]
    use crate::voronoi::voronoi_mod as voronoi;
    #[pymodule_export]
    use crate::vector::vector_mod as vector;
    #[pymodule_export]
    use crate::wgpu_renderer::wgpu_mod as wgpu;
}