mod vector;
mod polyline;
pub(crate) mod signature;
mod transformation;
mod interpolation;

pub use vector::*;
pub use polyline::*;
pub use transformation::*;
pub use interpolation::*;

use pyo3::prelude::*;

#[pymodule(submodule, name = "vector")]
pub(crate) mod vector_mod {
    #[pymodule_export]
    use super::CutResult;
    #[pymodule_export]
    use super::Interpolation;
    #[pymodule_export]
    use super::PolyLine2D;
    #[pymodule_export]
    use super::PolyLine3D;
    #[pymodule_export]
    use super::Rotation2D;
    #[pymodule_export]
    use super::Transformation;
    #[pymodule_export]
    use super::Vector2D;
    #[pymodule_export]
    use super::Vector3D;
    #[pymodule_export]
    use super::cut;
    #[pymodule_export]
    use super::cut_2d;
}
