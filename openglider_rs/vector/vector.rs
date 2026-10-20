use nalgebra::{Vector2, Vector3};
use pyo3::exceptions::{PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use super::signature::*;

pub trait VectorOps: Sized + Copy + Clone {
    const DIMENSION: usize;

    fn zero() -> Self;
    fn from_components(values: &[f64]) -> PyResult<Self>;
    fn components(&self) -> Vec<f64>;
    fn get_item(&self, index: usize) -> PyResult<f64>;
    fn set_item(&mut self, index: usize, value: f64) -> PyResult<()>;
    fn add(self, other: Self) -> Self;
    fn sub(self, other: Self) -> Self;
    fn mul(self, other: Self) -> Self;
    fn scale(self, factor: f64) -> Self;
    fn dot(self, other: Self) -> f64;
    fn repr(&self) -> String;

    fn length(self) -> f64 {
        self.dot(self).sqrt()
    }

    fn distance(self, other: Self) -> f64 {
        self.sub(other).length()
    }

    fn normalized(self) -> Self {
        let length = self.length();
        self.scale(1.0 / length)
    }

    fn hash_value(&self) -> u64 {
        let mut hasher = DefaultHasher::new();
        for value in self.components() {
            value.to_bits().hash(&mut hasher);
        }
        hasher.finish()
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Vector2D {
    #[pyo3(get, set)]
    pub x: f64,
    #[pyo3(get, set)]
    pub y: f64,
}

impl Vector2D {
    pub(crate) fn zero() -> Self {
        <Self as VectorOps>::zero()
    }

    pub(crate) fn from_components(values: &[f64]) -> PyResult<Self> {
        <Self as VectorOps>::from_components(values)
    }

    pub(crate) fn from_xy(x: f64, y: f64) -> Self {
        Self { x, y }
    }

    pub fn to_3d(self) -> Vector3D {
        Vector3D { x: self.x, y: self.y, z: 0.0 }
    }

    pub(crate) fn to_nalgebra(self) -> Vector2<f64> {
        Vector2::new(self.x, self.y)
    }

    pub(crate) fn from_nalgebra(v: Vector2<f64>) -> Self {
        Self { x: v.x, y: v.y }
    }
}

impl VectorOps for Vector2D {
    const DIMENSION: usize = 2;

    fn zero() -> Self {
        Self { x: 0.0, y: 0.0 }
    }

    fn from_components(values: &[f64]) -> PyResult<Self> {
        if values.len() != Self::DIMENSION {
            return Err(PyValueError::new_err("expected 2 values"));
        }
        Ok(Self::from_xy(values[0], values[1]))
    }

    fn components(&self) -> Vec<f64> {
        vec![self.x, self.y]
    }

    fn get_item(&self, index: usize) -> PyResult<f64> {
        match index {
            0 => Ok(self.x),
            1 => Ok(self.y),
            _ => Err(PyValueError::new_err("index out of range")),
        }
    }

    fn set_item(&mut self, index: usize, value: f64) -> PyResult<()> {
        match index {
            0 => self.x = value,
            1 => self.y = value,
            _ => return Err(PyValueError::new_err("index out of range")),
        }
        Ok(())
    }

    fn add(self, other: Self) -> Self {
        Self { x: self.x + other.x, y: self.y + other.y }
    }

    fn sub(self, other: Self) -> Self {
        Self { x: self.x - other.x, y: self.y - other.y }
    }

    fn mul(self, other: Self) -> Self {
        Self { x: self.x * other.x, y: self.y * other.y }
    }

    fn scale(self, factor: f64) -> Self {
        Self { x: self.x * factor, y: self.y * factor }
    }

    fn dot(self, other: Self) -> f64 {
        self.x * other.x + self.y * other.y
    }

    fn repr(&self) -> String {
        format!("Vector2D([{:.12}, {:.12}])", self.x, self.y)
    }
}

#[pymethods]
impl Vector2D {
    #[new]
    #[pyo3(signature = (values = None))]
    fn new(values: Option<Vec<f64>>) -> PyResult<Self> {
        match values {
            Some(values) => Self::from_components(&values),
            None => Ok(Self::zero()),
        }
    }

    fn __len__(&self) -> usize {
        Self::DIMENSION
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let list = PyList::new(py, self.components())?;
        Ok(list.into_any().call_method0("__iter__")?.unbind())
    }

    fn __getitem__(&self, index: isize) -> PyResult<f64> {
        if index < 0 || index as usize >= Self::DIMENSION {
            return Err(PyValueError::new_err("index out of range"));
        }
        self.get_item(index as usize)
    }

    fn __setitem__(&mut self, index: usize, value: f64) -> PyResult<()> {
        self.set_item(index, value)
    }

    fn __copy__(&self) -> Self {
        *self
    }

    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> Self {
        *self
    }

    fn __json__(&self) -> Vec<f64> {
        self.components()
    }

    fn __repr__(&self) -> String {
        self.repr()
    }

    fn __str__(&self) -> String {
        self.repr()
    }

    fn __hash__(&self) -> u64 {
        self.hash_value()
    }

    fn __eq__(&self, other: &Vector2D) -> bool {
        self == other
    }

    fn __lt__(&self, other: &Vector2D) -> bool {
        self.length() < other.length()
    }

    fn __le__(&self, other: &Vector2D) -> bool {
        self.length() <= other.length()
    }

    fn __gt__(&self, other: &Vector2D) -> bool {
        self.length() > other.length()
    }

    fn __ge__(&self, other: &Vector2D) -> bool {
        self.length() >= other.length()
    }

    fn __add__(&self, other: &Vector2D) -> Self {
        self.add(*other)
    }

    fn __sub__(&self, other: &Vector2D) -> Self {
        self.sub(*other)
    }

    fn __mul__(&self, other: Vector2DScaleInput) -> PyResult<Self> {
        Ok(match other.into_scale()? {
            Vector2DScale::Scalar(scalar) => self.scale(scalar),
            Vector2DScale::Vector(vector) => self.mul(vector),
        })
    }

    fn __truediv__(&self, factor: f64) -> Self {
        self.scale(1.0 / factor)
    }

    fn dot(&self, other: &Vector2D) -> f64 {
        VectorOps::dot(*self, *other)
    }

    fn length(&self) -> f64 {
        VectorOps::length(*self)
    }

    pub(crate) fn distance(&self, other: &Vector2D) -> f64 {
        VectorOps::distance(*self, *other)
    }

    pub(crate) fn normalized(&self) -> Self {
        VectorOps::normalized(*self)
    }

    fn copy(&self) -> Self {
        *self
    }

    fn cross(&self, other: &Vector2D) -> f64 {
        self.x * other.y - self.y * other.x
    }

    fn angle(&self) -> f64 {
        self.y.atan2(self.x)
    }

    pub fn rotate(&self, angle: f64) -> Self {

    let (sin, cos) = angle.sin_cos();
    Vector2D::from_xy(cos * self.x - sin * self.y, sin * self.x + cos * self.y)
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Vector3D {
    #[pyo3(get, set)]
    pub x: f64,
    #[pyo3(get, set)]
    pub y: f64,
    #[pyo3(get, set)]
    pub z: f64,
}

impl Vector3D {
    pub(crate) fn zero() -> Self {
        <Self as VectorOps>::zero()
    }

    pub(crate) fn from_components(values: &[f64]) -> PyResult<Self> {
        <Self as VectorOps>::from_components(values)
    }

    pub fn from_xyz(x: f64, y: f64, z: f64) -> Self {
        Self { x, y, z }
    }

    pub(crate) fn to_nalgebra(self) -> Vector3<f64> {
        Vector3::new(self.x, self.y, self.z)
    }

    pub(crate) fn from_nalgebra(v: Vector3<f64>) -> Self {
        Self { x: v.x, y: v.y, z: v.z }
    }
}

impl VectorOps for Vector3D {
    const DIMENSION: usize = 3;

    fn zero() -> Self {
        Self { x: 0.0, y: 0.0, z: 0.0 }
    }

    fn from_components(values: &[f64]) -> PyResult<Self> {
        if values.len() != Self::DIMENSION {
            return Err(PyValueError::new_err("expected 3 values"));
        }
        Ok(Self::from_xyz(values[0], values[1], values[2]))
    }

    fn components(&self) -> Vec<f64> {
        vec![self.x, self.y, self.z]
    }

    fn get_item(&self, index: usize) -> PyResult<f64> {
        match index {
            0 => Ok(self.x),
            1 => Ok(self.y),
            2 => Ok(self.z),
            _ => Err(PyValueError::new_err("index out of range")),
        }
    }

    fn set_item(&mut self, index: usize, value: f64) -> PyResult<()> {
        match index {
            0 => self.x = value,
            1 => self.y = value,
            2 => self.z = value,
            _ => return Err(PyValueError::new_err("index out of range")),
        }
        Ok(())
    }

    fn add(self, other: Self) -> Self {
        Self { x: self.x + other.x, y: self.y + other.y, z: self.z + other.z }
    }

    fn sub(self, other: Self) -> Self {
        Self { x: self.x - other.x, y: self.y - other.y, z: self.z - other.z }
    }

    fn mul(self, other: Self) -> Self {
        Self { x: self.x * other.x, y: self.y * other.y, z: self.z * other.z }
    }

    fn scale(self, factor: f64) -> Self {
        Self { x: self.x * factor, y: self.y * factor, z: self.z * factor }
    }

    fn dot(self, other: Self) -> f64 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    fn repr(&self) -> String {
        format!("Vector3D([{:.12}, {:.12}, {:.12}])", self.x, self.y, self.z)
    }
}

#[pymethods]
impl Vector3D {
    #[new]
    #[pyo3(signature = (values = None))]
    fn new(values: Option<Vec<f64>>) -> PyResult<Self> {
        match values {
            Some(values) => Self::from_components(&values),
            None => Ok(Self::zero()),
        }
    }

    fn __len__(&self) -> usize {
        Self::DIMENSION
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let list = PyList::new(py, self.components())?;
        Ok(list.into_any().call_method0("__iter__")?.unbind())
    }

    fn __getitem__(&self, index: isize) -> PyResult<f64> {
        if index < 0 || index as usize >= Self::DIMENSION {
            return Err(PyValueError::new_err("index out of range"));
        }
        self.get_item(index as usize)
    }

    fn __setitem__(&mut self, index: usize, value: f64) -> PyResult<()> {
        self.set_item(index, value)
    }

    fn __copy__(&self) -> Self {
        *self
    }

    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> Self {
        *self
    }

    fn __json__(&self) -> Vec<f64> {
        self.components()
    }

    fn __repr__(&self) -> String {
        self.repr()
    }

    fn __str__(&self) -> String {
        self.repr()
    }

    fn __hash__(&self) -> u64 {
        self.hash_value()
    }

    fn __eq__(&self, other: &Vector3D) -> bool {
        self == other
    }

    fn __lt__(&self, other: &Vector3D) -> bool {
        self.length() < other.length()
    }

    fn __le__(&self, other: &Vector3D) -> bool {
        self.length() <= other.length()
    }

    fn __gt__(&self, other: &Vector3D) -> bool {
        self.length() > other.length()
    }

    fn __ge__(&self, other: &Vector3D) -> bool {
        self.length() >= other.length()
    }

    fn __add__(&self, other: &Vector3D) -> Self {
        self.add(*other)
    }

    fn __sub__(&self, other: &Vector3D) -> Self {
        self.sub(*other)
    }

    fn __mul__(&self, other: Vector3DScaleInput) -> PyResult<Self> {
        Ok(match other.into_scale()? {
            Vector3DScale::Scalar(scalar) => self.scale(scalar),
            Vector3DScale::Vector(vector) => self.mul(vector),
        })
    }

    fn __truediv__(&self, factor: f64) -> Self {
        self.scale(1.0 / factor)
    }

    fn dot(&self, other: &Vector3D) -> f64 {
        VectorOps::dot(*self, *other)
    }

    fn length(&self) -> f64 {
        VectorOps::length(*self)
    }

    pub(crate) fn distance(&self, other: &Vector3D) -> f64 {
        VectorOps::distance(*self, *other)
    }

    pub(crate) fn normalized(&self) -> Self {
        VectorOps::normalized(*self)
    }

    fn copy(&self) -> Self {
        *self
    }

    pub(crate) fn cross(&self, other: &Vector3D) -> Self {
        Self {
            x: self.y * other.z - self.z * other.y,
            y: self.z * other.x - self.x * other.z,
            z: self.x * other.y - self.y * other.x,
        }
    }
}


