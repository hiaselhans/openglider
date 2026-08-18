use nalgebra::Matrix4;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub(crate) type MvpUniform = [[f32; 4]; 4];
pub(crate) const PERSPECTIVE_FOV_Y: f32 = 45.0_f32.to_radians();

#[derive(Clone, Copy)]
pub(crate) enum ProjectionMode {
    Orthographic,
    Perspective,
}

impl ProjectionMode {
    pub(crate) fn from_str(value: &str) -> PyResult<Self> {
        match value {
            "orthographic" | "ortho" => Ok(Self::Orthographic),
            "perspective" | "persp" => Ok(Self::Perspective),
            other => Err(PyValueError::new_err(format!(
                "unsupported projection mode '{other}', expected one of: orthographic, perspective"
            ))),
        }
    }
}

pub(crate) fn matrix_to_uniform(matrix: Matrix4<f32>) -> MvpUniform {
    // WGSL matrices are interpreted as column vectors in memory.
    // nalgebra stores Matrix4 as column-major contiguous data as well, so we
    // upload 4 vec4 columns directly to avoid implicit transposition issues.
    let m = matrix.as_slice();
    [
        [m[0], m[1], m[2], m[3]],
        [m[4], m[5], m[6], m[7]],
        [m[8], m[9], m[10], m[11]],
        [m[12], m[13], m[14], m[15]],
    ]
}
