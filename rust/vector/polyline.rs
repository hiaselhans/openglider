use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};
use std::fmt;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use super::signature::*;
use super::vector::*;

#[derive(Debug, Clone)]
pub struct SimpleError(pub String);

impl SimpleError {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for SimpleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for SimpleError {}

impl From<SimpleError> for PyErr {
    fn from(error: SimpleError) -> Self {
        PyRuntimeError::new_err(error.to_string())
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct PolyLine2D {
    #[pyo3(get)]
    pub nodes: Vec<Vector2D>,
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct PolyLine3D {
    #[pyo3(get)]
    pub nodes: Vec<Vector3D>,
}


#[pyclass(from_py_object)]
#[derive(Clone, Copy, Debug)]
pub struct CutResult {
    #[pyo3(get)]
    pub success: bool,
    #[pyo3(get)]
    pub ik_1: f64,
    #[pyo3(get)]
    pub ik_2: f64,
    #[pyo3(get)]
    pub point: Vector2D,
}

fn line_intersection_2d(a1: Vector2D, a2: Vector2D, b1: Vector2D, b2: Vector2D) -> Option<(f64, f64, Vector2D)> {
    let da = a2.sub(a1);
    let db = b2.sub(b1);

    let min_segment_length = 1e-8;
    let da_len_sq = da.dot(da);
    let db_len_sq = db.dot(db);
    if da_len_sq < min_segment_length * min_segment_length || db_len_sq < min_segment_length * min_segment_length {
        return None;
    }

    let det = da.x * db.y - da.y * db.x;
    let parallel_threshold = 1e-10;
    let da_len = da_len_sq.sqrt();
    let db_len = db_len_sq.sqrt();
    if da_len == 0.0 || db_len == 0.0 {
        return None;
    }
    let cross_normalized = det / (da_len * db_len);
    if cross_normalized.abs() < parallel_threshold {
        return None;
    }

    let diff = b1.sub(a1);
    let t = (diff.x * db.y - diff.y * db.x) / det;
    let u = (diff.x * da.y - diff.y * da.x) / det;
    Some((t, u, a1.add(da.scale(t))))
}

#[pyfunction]
pub fn cut_2d(
    l1_p1: Vector2DInput,
    l1_p2: Vector2DInput,
    l2_p1: Vector2DInput,
    l2_p2: Vector2DInput,
) -> PyResult<CutResult> {
    let l1_p1 = l1_p1.into_vector()?;
    let l1_p2 = l1_p2.into_vector()?;
    let l2_p1 = l2_p1.into_vector()?;
    let l2_p2 = l2_p2.into_vector()?;

    Ok(if let Some((ik_1, ik_2, point)) = line_intersection_2d(l1_p1, l1_p2, l2_p1, l2_p2) {
        CutResult { success: true, ik_1, ik_2, point }
    } else {
        CutResult { success: false, ik_1: 0.0, ik_2: 0.0, point: Vector2D::zero() }
    })
}

#[pyfunction(name = "cut")]
pub fn cut(
    l1_p1: Vector2DInput,
    l1_p2: Vector2DInput,
    l2_p1: Vector2DInput,
    l2_p2: Vector2DInput,
) -> PyResult<CutResult> {
    cut_2d(l1_p1, l1_p2, l2_p1, l2_p2)
}

pub(crate) fn polyline_resample<V: VectorOps>(nodes: &[V], num_points: usize) -> Vec<V> {
    if nodes.is_empty() || num_points == 0 {
        return Vec::new();
    }
    if nodes.len() == 1 || num_points == 1 {
        return vec![nodes[0]];
    }

    let lengths: Vec<f64> = nodes.windows(2).map(|pair| pair[0].distance(pair[1])).collect();
    let total: f64 = lengths.iter().sum();
    if total == 0.0 {
        return vec![nodes[0]; num_points];
    }

    let step = total / (num_points - 1) as f64;
    let mut result = Vec::with_capacity(num_points);
    result.push(nodes[0]);

    let mut target_distance = step;
    let mut segment_index = 0usize;
    let mut accumulated = 0.0;
    while result.len() + 1 < num_points {
        while segment_index < lengths.len() && accumulated + lengths[segment_index] < target_distance {
            accumulated += lengths[segment_index];
            segment_index += 1;
        }
        if segment_index >= lengths.len() {
            break;
        }
        let segment_length = lengths[segment_index];
        let fraction = if segment_length == 0.0 { 0.0 } else { (target_distance - accumulated) / segment_length };
        let p1 = nodes[segment_index];
        let p2 = nodes[segment_index + 1];
        result.push(p1.scale(1.0 - fraction).add(p2.scale(fraction)));
        target_distance += step;
    }

    while result.len() + 1 < num_points {
        result.push(*nodes.last().unwrap());
    }
    result.push(*nodes.last().unwrap());
    result
}

pub(crate) fn polyline_get<V: VectorOps>(nodes: &[V], ik: f64) -> V {
    if nodes.is_empty() {
        return V::zero();
    }
    if nodes.len() == 1 {
        return nodes[0];
    }

    let mut i = (ik as isize).max(0) as usize;
    if (ik - i as f64).abs() < 1e-10 && ik >= 0.0 && (i as f64) < nodes.len() as f64 {
        return nodes[i];
    }

    let diff = if i >= nodes.len() - 1 {
        i = nodes.len() - 1;
        nodes[i].sub(nodes[i - 1])
    } else {
        nodes[i + 1].sub(nodes[i])
    };

    let k = ik - i as f64;
    nodes[i].add(diff.scale(k))
}

pub(crate) fn polyline_length<V: VectorOps>(nodes: &[V]) -> f64 {
    nodes.windows(2).map(|pair| pair[0].distance(pair[1])).sum()
}

fn polyline_segments<V: VectorOps>(nodes: &[V]) -> Vec<V> {
    nodes.windows(2).map(|pair| pair[1].sub(pair[0])).collect()
}

fn polyline_tangents<V: VectorOps>(nodes: &[V]) -> Vec<V> {
    let segments: Vec<V> = polyline_segments(nodes)
        .into_iter()
        .map(VectorOps::normalized)
        .collect();
    if segments.is_empty() {
        return Vec::new();
    }

    let mut tangents = Vec::with_capacity(nodes.len());
    tangents.push(segments[0]);

    for index in 0..segments.len().saturating_sub(1) {
        tangents.push(segments[index].add(segments[index + 1]));
    }

    tangents.push(*segments.last().unwrap());
    tangents
}

fn polyline_hash<V: VectorOps>(nodes: &[V]) -> u64 {
    let mut hasher = DefaultHasher::new();
    nodes.len().hash(&mut hasher);
    for node in nodes {
        node.hash_value().hash(&mut hasher);
    }
    hasher.finish()
}

fn polyline_scale_nodes<V: VectorOps>(nodes: &[V], factors: &[f64]) -> Result<Vec<V>, SimpleError> {
    if nodes.len() != factors.len() {
        return Err(SimpleError::new(format!(
            "PolyLine sizes don't match! ({}/{})",
            nodes.len(),
            factors.len()
        )));
    }
    Ok(nodes.iter().zip(factors.iter().copied()).map(|(node, factor)| node.scale(factor)).collect())
}

fn polyline2d_fix_errors(nodes: &[Vector2D]) -> Vec<Vector2D> {
    const TOLERANCE: f64 = 1e-5;
    const SMALL_D: f64 = 1e-10;

    if nodes.len() <= 4 {
        return nodes.to_vec();
    }

    for index in 0..nodes.len().saturating_sub(3) {
        let new_list_start = index + 2;
        let line2_nodes = &nodes[new_list_start..];

        let cuts = polyline2d_cut_line(line2_nodes, nodes[index], nodes[index + 1]);
        for (ik_1, ik_2) in cuts.into_iter().rev() {
            let line2_max = line2_nodes.len() as f64 - 1.0 - SMALL_D;
            if (0.0..line2_max).contains(&ik_1) && (0.0..1.0).contains(&ik_2) {
                let mut new_nodes = Vec::with_capacity(nodes.len());
                new_nodes.extend_from_slice(&nodes[..=index]);
                new_nodes.push(polyline_get(line2_nodes, ik_1));

                let mut start_2 = ik_1 as usize + 1;
                if (ik_1 - start_2 as f64).abs() < TOLERANCE {
                    start_2 += 1;
                }

                if start_2 < line2_nodes.len() {
                    new_nodes.extend_from_slice(&line2_nodes[start_2..]);
                }

                return polyline2d_fix_errors(&new_nodes);
            }
        }
    }

    let mut cleaned = Vec::with_capacity(nodes.len());
    cleaned.push(nodes[0]);

    for pair in nodes.windows(2) {
        if pair[0].distance(pair[1]) > TOLERANCE {
            cleaned.push(pair[1]);
        }
    }

    simplify_short_zigzags_auto(&cleaned, TOLERANCE * 10.0)
}

fn turn_angle_deg(a: Vector2D, b: Vector2D, c: Vector2D) -> f64 {
    let ab = b.sub(a);
    let bc = c.sub(b);
    let ab_len = ab.length();
    let bc_len = bc.length();
    if ab_len < 1e-12 || bc_len < 1e-12 {
        return 0.0;
    }

    let cosang = (ab.dot(bc) / (ab_len * bc_len)).clamp(-1.0, 1.0);
    cosang.acos().to_degrees()
}

fn simplify_short_zigzags_auto(nodes: &[Vector2D], absolute_tolerance: f64) -> Vec<Vector2D> {
    if nodes.len() < 4 {
        return nodes.to_vec();
    }

    let mut simplified = nodes.to_vec();
    let ratio_threshold = 0.25;
    let angle_threshold_deg = 45.0;
    let mut changed = true;

    while changed && simplified.len() >= 4 {
        changed = false;
        let mut index = 1usize;

        while index + 2 < simplified.len() {
            let left_len = simplified[index - 1].distance(simplified[index]);
            let seg_len = simplified[index].distance(simplified[index + 1]);
            let right_len = simplified[index + 1].distance(simplified[index + 2]);

            let local_threshold = absolute_tolerance.max(left_len.min(right_len) * ratio_threshold);
            if seg_len >= local_threshold {
                index += 1;
                continue;
            }

            let a = simplified[index - 1];
            let b = simplified[index];
            let c = simplified[index + 1];
            let d = simplified[index + 2];

            let angle_b = turn_angle_deg(a, b, c);
            let angle_c = turn_angle_deg(b, c, d);
            if angle_b.max(angle_c) < angle_threshold_deg {
                index += 1;
                continue;
            }

            let score_remove_b = turn_angle_deg(a, c, d);
            let score_remove_c = turn_angle_deg(a, b, d);

            if score_remove_b <= score_remove_c {
                simplified.remove(index);
            } else {
                simplified.remove(index + 1);
            }

            changed = true;
            if index > 1 {
                index -= 1;
            }
        }
    }

    simplified
}

pub(crate) fn polyline2d_cut_line(nodes: &[Vector2D], p1: Vector2D, p2: Vector2D) -> Vec<(f64, f64)> {
    let mut intersections = Vec::new();
    let tolerance = 1e-5;
    if nodes.len() < 2 {
        return intersections;
    }

    let mut last_ik_1 = 0.0;
    let mut last_ik_2 = 0.0;
    let mut last_success = false;
    let mut last_cut = line_intersection_2d(nodes[0], nodes[1], p1, p2);

    if let Some((ik_1, ik_2, _)) = last_cut {
        last_success = true;
        last_ik_1 = ik_1;
        last_ik_2 = ik_2;
        if ik_1 <= tolerance {
            intersections.push((ik_1, ik_2));
        }
    }

    for index in 0..nodes.len().saturating_sub(1) {
        let cut = line_intersection_2d(nodes[index], nodes[index + 1], p1, p2);
        if let Some((ik_1, ik_2, _)) = cut {
            if tolerance < ik_1 && ik_1 <= 1.0 - tolerance {
                intersections.push((index as f64 + ik_1, ik_2));
            } else if -tolerance < ik_1 && ik_1 <= tolerance && last_success && 1.0 - tolerance < last_ik_1 && last_ik_1 <= 1.0 + tolerance {
                intersections.push((index as f64, last_ik_2));
            }
            last_success = true;
            last_ik_1 = ik_1;
            last_ik_2 = ik_2;
            last_cut = Some((ik_1, ik_2, Vector2D::zero()));
        } else {
            last_success = false;
            last_cut = None;
        }
    }

    if let Some((ik_1, ik_2, _)) = last_cut {
        if ik_1 > 1.0 - tolerance {
            intersections.push((ik_1 + nodes.len() as f64 - 2.0, ik_2));
        }
    }

    intersections
}

fn polyline2d_cut_polyline(line1_nodes: &[Vector2D], line2_nodes: &[Vector2D]) -> Vec<(f64, f64)> {
    let tolerance = 1e-5;
    let mut intersections = Vec::new();

    if line2_nodes.len() < 2 {
        return intersections;
    }

    for index in 0..line2_nodes.len().saturating_sub(1) {
        let cuts = polyline2d_cut_line(line1_nodes, line2_nodes[index], line2_nodes[index + 1]);
        for cut in cuts {
            if -tolerance < cut.1
                && cut.1 < 1.0 + tolerance
                && -tolerance < cut.0
                && cut.0 < line1_nodes.len() as f64 - 1.0 + tolerance
            {
                intersections.push((cut.0, index as f64 + cut.1));
            }
        }
    }

    intersections
}

fn polyline2d_contains(nodes: &[Vector2D], point: Vector2D) -> bool {
    if nodes.len() < 3 {
        return false;
    }

    let mut inside = false;
    let mut previous = *nodes.last().unwrap();
    for current in nodes {
        let intersects = ((current.y > point.y) != (previous.y > point.y))
            && (point.x
                < (previous.x - current.x) * (point.y - current.y)
                    / (previous.y - current.y + 1e-18)
                    + current.x);
        if intersects {
            inside = !inside;
        }
        previous = *current;
    }

    inside
}

fn polyline2d_subcurve(nodes: &[Vector2D], start: f64, end: f64) -> Vec<Vector2D> {
    polyline_get_positions(nodes.len(), start, end)
        .into_iter()
        .map(|position| polyline_get(nodes, position))
        .collect()
}

fn polyline_get_positions(node_count: usize, ik_start: f64, ik_end: f64) -> Vec<f64> {
    if node_count < 2 {
        return vec![ik_start, ik_end];
    }

    let mut result = Vec::new();
    let mut direction = 1_i32;
    let mut forward = true;
    if ik_end < ik_start {
        direction = -1;
        forward = false;
    }

    result.push(ik_start);

    let mut ik = ik_start as i32;
    ik = ik.clamp(0, (node_count as i32) - 2);

    if forward {
        ik += 1;
    }

    if (ik_start - ik as f64).abs() < 1e-8 {
        ik += direction;
    }

    while (direction as f64) * (ik_end - ik as f64) > 1e-8 && 0 < ik && ik < (node_count as i32) - 1 {
        result.push(ik as f64);
        ik += direction;
    }

    result.push(ik_end);
    result
}

fn polyline_walk<V: VectorOps>(nodes: &[V], start: f64, amount: f64) -> f64 {
    if nodes.len() < 2 {
        return start;
    }

    if amount.abs() < 1e-5 {
        return start;
    }

    let direction: i32 = if amount < 0.0 { -1 } else { 1 };
    let mut next_value = start as i32;
    if direction > 0 {
        next_value += 1;
    }
    if start < 0.0 {
        next_value -= 1;
    }

    if (start - next_value as f64).abs() < 1e-5 {
        next_value += direction;
    }

    let mut remaining = amount.abs();
    let mut start_cursor = start;

    let mut current_segment_length = polyline_get(nodes, next_value as f64).distance(polyline_get(nodes, start_cursor));
    remaining -= current_segment_length;

    while remaining > 0.0 {
        if next_value > nodes.len() as i32 && direction > 0 {
            break;
        }
        if next_value < 0 && direction < 0 {
            break;
        }

        start_cursor = next_value as f64;
        next_value += direction;
        current_segment_length = polyline_get(nodes, next_value as f64).distance(polyline_get(nodes, start_cursor));
        remaining -= current_segment_length;
    }

    if current_segment_length <= 1e-15 {
        return next_value as f64;
    }

    next_value as f64 + (direction as f64) * remaining * ((next_value as f64 - start_cursor).abs()) / current_segment_length
}


#[pymethods]
impl PolyLine2D {
    #[new]
    #[pyo3(signature = (nodes = None))]
    fn new(nodes: Option<Vec<Vector2DInput>>) -> PyResult<Self> {
        let mut parsed = Vec::new();
        if let Some(nodes) = nodes {
            for node in nodes {
                parsed.push(node.into_vector()?);
            }
        }
        Ok(Self { nodes: parsed })
    }

    fn __len__(&self) -> usize { self.nodes.len() }
    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let list = PyList::new(py, self.nodes.clone())?;
        Ok(list.into_any().call_method0("__iter__")?.unbind())
    }
    fn __copy__(&self) -> Self { self.clone() }
    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> Self { self.clone() }
    fn copy(&self) -> Self { self.clone() }

    fn __repr__(&self) -> String {
        let mut result = String::from("PolyLine2D[\n");
        for node in &self.nodes {
            result.push_str("  ");
            result.push_str(&node.repr());
            result.push_str(",\n");
        }
        if !self.nodes.is_empty() {
            result.truncate(result.len().saturating_sub(2));
            result.push('\n');
        }
        result.push(']');
        result
    }

    fn __json__(&self) -> Vec<Vec<f64>> { self.nodes.iter().map(VectorOps::components).collect() }
    fn tolist(&self) -> Vec<Vec<f64>> { self.nodes.iter().map(VectorOps::components).collect() }

    fn __hash__(&self) -> u64 { polyline_hash(&self.nodes) }

    #[pyo3(signature = (value, end = None))]
    pub fn get(&self, value: f64, end: Option<f64>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(end) = end {
            let mut nodes = Vec::new();
            for position in polyline_get_positions(self.nodes.len(), value, end) {
                nodes.push(polyline_get(&self.nodes, position));
            }
            return Py::new(py, Self { nodes }).map(|value| value.into_bound(py).into_any().unbind());
        }
        Py::new(py, polyline_get(&self.nodes, value)).map(|value| value.into_bound(py).into_any().unbind())
    }

    pub fn get_positions(&self, start: f64, end: f64) -> Vec<f64> {
        polyline_get_positions(self.nodes.len(), start, end)
    }

    pub fn get_segments(&self) -> Vec<Vector2D> { polyline_segments(&self.nodes) }
    pub fn get_segment_lengthes(&self) -> Vec<f64> { self.nodes.windows(2).map(|pair| pair[0].distance(pair[1])).collect() }
    pub fn get_tangents(&self) -> Vec<Vector2D> { polyline_tangents(&self.nodes) }
    pub fn get_length(&self) -> f64 { polyline_length(&self.nodes) }

    pub fn walk(&self, start: f64, amount: f64) -> f64 {
        polyline_walk(&self.nodes, start, amount)
    }

    pub fn resample(&self, num_points: usize) -> Self { Self { nodes: polyline_resample(&self.nodes, num_points) } }

    pub fn scale(&self, factor: Vector2DScaleInput) -> PyResult<Self> {
        Ok(match factor.into_scale()? {
            Vector2DScale::Scalar(scalar) => Self {
                nodes: self.nodes.iter().map(|node| node.scale(scalar)).collect(),
            },
            Vector2DScale::Vector(vector) => Self {
                nodes: self.nodes.iter().map(|node| node.mul(vector)).collect(),
            },
        })
    }

    #[pyo3(name = "move")]
    pub fn r#move(&self, offset: Vector2DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .map(|node| node.add(offset))
                .collect(),
        })
    }

    pub fn add(&self, other: &PolyLine2D) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }

        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.add(right))
                .collect(),
        })
    }

    pub fn sub(&self, other: &PolyLine2D) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }

        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.sub(right))
                .collect(),
        })
    }

    pub fn scale_nodes(&self, factors: Vec<f64>) -> Result<Self, SimpleError> {
        Ok(Self {
            nodes: polyline_scale_nodes(&self.nodes, &factors)?,
        })
    }
    pub fn reverse(&self) -> Self { let mut nodes = self.nodes.clone(); nodes.reverse(); Self { nodes } }
    pub fn mix(&self, other: &PolyLine2D, factor: f64) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }

        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.scale(1.0 - factor).add(right.scale(factor)))
                .collect(),
        })
    }
    fn __add__(&self, other: &PolyLine2D) -> Self {
        let mut nodes = Vec::with_capacity(self.nodes.len() + other.nodes.len());
        nodes.extend_from_slice(&self.nodes);
        nodes.extend_from_slice(&other.nodes);
        Self { nodes }
    }
    fn __sub__(&self, other: &PolyLine2D) -> Result<Self, SimpleError> { self.sub(other) }
    fn __mul__(&self, factor: Vector2DScaleInput) -> PyResult<Self> { self.scale(factor) }

    pub fn segment_normals(&self) -> Self {
        let nodes = self.nodes.windows(2).map(|pair| {
            let segment = pair[1].sub(pair[0]).normalized();
            Vector2D { x: segment.y, y: -segment.x }
        }).collect();
        Self { nodes }
    }

    pub fn normvectors(&self) -> Self {
        let segments = self.get_segments();
        if segments.is_empty() {
            return Self { nodes: Vec::new() };
        }

        let segment_normals = self.segment_normals().nodes;
        let mut norms = Vec::with_capacity(self.nodes.len());
        norms.push(segment_normals[0]);

        for index in 0..segment_normals.len().saturating_sub(1) {
            let normal = segment_normals[index].add(segment_normals[index + 1]);
            if normal.length() > 1e-12 {
                norms.push(normal.normalized());
            } else {
                let segment_index = index.saturating_sub(1);
                norms.push(segments[segment_index].normalized());
            }
        }

        norms.push(*segment_normals.last().unwrap());
        Self { nodes: norms }
    }

    #[pyo3(signature = (amount, simple = false))]
    fn offset(&self, amount: f64, simple: bool) -> Self {
        const EPSILON: f64 = 1e-10;
        const MITER_LIMIT: f64 = 10.0;

        let nodes = polyline2d_fix_errors(&self.nodes);

        if nodes.len() < 2 {
            return self.clone();
        }

        let clean_line = Self { nodes };

        if simple {
            let normals = clean_line.normvectors().nodes;
            let nodes = clean_line
                .nodes
                .iter()
                .copied()
                .zip(normals)
                .map(|(point, normal)| point.add(normal.scale(amount)))
                .collect();
            return Self { nodes };
        }

        let segments = clean_line.get_segments();
        let segments_normalized: Vec<Vector2D> = segments.iter().copied().map(|segment| segment.normalized()).collect();
        let segment_normals = clean_line.segment_normals().nodes;

        let mut offset_segments: Vec<(Vector2D, Vector2D)> = Vec::with_capacity(clean_line.nodes.len().saturating_sub(1));
        for index in 0..clean_line.nodes.len() - 1 {
            let normal = segment_normals[index];
            offset_segments.push((
                clean_line.nodes[index].add(normal.scale(amount)),
                clean_line.nodes[index + 1].add(normal.scale(amount)),
            ));
        }

        let mut result = Vec::with_capacity(clean_line.nodes.len() + clean_line.nodes.len().saturating_sub(2));
        result.push(clean_line.nodes[0].add(segment_normals[0].scale(amount)));

        for index in 0..clean_line.nodes.len() - 2 {
            let segment_1 = segments_normalized[index];
            let segment_2 = segments_normalized[index + 1];
            let cos_angle = segment_1.dot(segment_2);
            let segment_1_len = segments[index].length();
            let segment_2_len = segments[index + 1].length();
            let tiny_segment_threshold = amount.abs().max(1e-6) * 0.25;

            let fallback_join = || {
                let merged_normal = segment_normals[index].add(segment_normals[index + 1]);
                if merged_normal.length() > EPSILON {
                    clean_line.nodes[index + 1].add(merged_normal.normalized().scale(amount))
                } else {
                    offset_segments[index].1.add(offset_segments[index + 1].0).scale(0.5)
                }
            };

            if segment_1_len < tiny_segment_threshold || segment_2_len < tiny_segment_threshold {
                result.push(fallback_join());
                continue;
            }

            if cos_angle > 0.999 || segment_1.length() < EPSILON || segment_2.length() < EPSILON {
                let average = offset_segments[index].1.add(offset_segments[index + 1].0).scale(0.5);
                result.push(average);
                continue;
            }

            let intersection = line_intersection_2d(
                offset_segments[index].0,
                offset_segments[index].1,
                offset_segments[index + 1].0,
                offset_segments[index + 1].1,
            );

            if let Some((ik_1, ik_2, point)) = intersection {
                let reasonable_intersection = (ik_1 > 0.5 && ik_1 < 1.5) && (ik_2 > -0.5 && ik_2 < 0.5);

                if reasonable_intersection {
                    let original_vertex = clean_line.nodes[index + 1];
                    let miter_distance = point.sub(original_vertex).length();
                    let max_miter_distance = amount.abs() * MITER_LIMIT;

                    if miter_distance <= max_miter_distance {
                        result.push(point);
                    } else {
                        result.push(fallback_join());
                    }
                } else {
                    result.push(fallback_join());
                }
            } else {
                result.push(fallback_join());
            }
        }

        result.push(clean_line.nodes[clean_line.nodes.len() - 1].add(segment_normals[segment_normals.len() - 1].scale(amount)));
        Self { nodes: result }
    }

    #[pyo3(signature = (other, second_point = None, nearest_ik = None))]
    pub fn cut(&self, other: PolyLine2DCutInput, second_point: Option<Vector2DInput>, nearest_ik: Option<f64>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let finalize_result = |mut intersections: Vec<(f64, f64)>| -> PyResult<Py<PyAny>> {
            if let Some(nearest_ik) = nearest_ik {
                intersections.sort_by(|left, right| (left.0 - nearest_ik).abs().partial_cmp(&(right.0 - nearest_ik).abs()).unwrap_or(std::cmp::Ordering::Equal));
                if let Some(cut) = intersections.first() {
                    return Ok((cut.0, cut.1).into_pyobject(py)?.into_any().unbind());
                }
                return Err(PyRuntimeError::new_err("No cut found!"));
            }

            Ok(intersections.into_pyobject(py)?.into_any().unbind())
        };

        match other {
            PolyLine2DCutInput::Vector(vector) => {
                let p1 = vector.into_vector()?;
                let p2 = match second_point {
                    Some(point) => point.into_vector()?,
                    None => p1.add(Vector2D { x: 1.0, y: 0.0 }),
                };
                finalize_result(polyline2d_cut_line(&self.nodes, p1, p2))
            }
            PolyLine2DCutInput::PolyLine(other) => {
                if second_point.is_some() {
                    return Err(PyTypeError::new_err("second_point is only valid when 'other' is a Vector2D"));
                }

                let tolerance = 1e-5;
                let mut intersections = Vec::new();
                let other = other.bind(py).borrow();
                for index_b in 0..other.nodes.len().saturating_sub(1) {
                    let cuts = polyline2d_cut_line(&self.nodes, other.nodes[index_b], other.nodes[index_b + 1]);
                    for cut in cuts {
                        if -tolerance < cut.1 && cut.1 < 1.0 + tolerance && -tolerance < cut.0 && cut.0 < self.nodes.len() as f64 - 1.0 + tolerance {
                            intersections.push((cut.0, index_b as f64 + cut.1));
                        }
                    }
                }
                finalize_result(intersections)
            }
        }
    }

    fn bool_intersection(&self, other: &PolyLine2D) -> Vec<PolyLine2D> {
        type Cut = (f64, f64);

        let mut result: Vec<PolyLine2D> = Vec::new();

        let first = self.close();
        let second = other.close();

        let mut cuts = polyline2d_cut_polyline(&first.nodes, &second.nodes);

        if cuts.is_empty() {
            if !second.nodes.is_empty() && polyline2d_contains(&first.nodes, second.nodes[0]) {
                result.push(second);
            } else if !first.nodes.is_empty() && polyline2d_contains(&second.nodes, first.nodes[0]) {
                result.push(first);
            }

            return result;
        }

        cuts.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut start: Cut = (0.0, 0.0);
        let mut end: Cut = (
            first.nodes.len().saturating_sub(1) as f64,
            second.nodes.len().saturating_sub(1) as f64,
        );

        if cuts.len() > 1 {
            if cuts[0].1 > cuts[1].1 {
                start.1 = second.nodes.len().saturating_sub(1) as f64;
            }

            let n = cuts.len();
            if cuts[n - 1].1 < cuts[n - 2].1 {
                end.1 = 0.0;
            }
        }

        cuts.insert(0, start);
        cuts.push(end);

        let mut new_nodes: Vec<Vector2D> = Vec::new();

        for index in 0..cuts.len().saturating_sub(1) {
            let start_positions = cuts[index];
            let end_positions = cuts[index + 1];

            let mut ik_middle = (start_positions.0 + end_positions.0) / 2.0;
            let first_inside_second =
                polyline2d_contains(&second.nodes, polyline_get(&first.nodes, ik_middle));

            ik_middle = (start_positions.1 + end_positions.1) / 2.0;
            let second_inside_first =
                polyline2d_contains(&first.nodes, polyline_get(&second.nodes, ik_middle));

            let node_offset = if new_nodes.is_empty() { 0 } else { 1 };

            if index > 0 && first_inside_second && second_inside_first {
                let to_insert = polyline2d_subcurve(&first.nodes, start_positions.0, end_positions.0);
                new_nodes.extend(to_insert);

                let to_insert = polyline2d_subcurve(&second.nodes, end_positions.1, start_positions.1);
                if to_insert.len() > 1 {
                    new_nodes.extend_from_slice(&to_insert[1..]);
                }

                result.push(PolyLine2D { nodes: new_nodes }.close());
                new_nodes = Vec::new();
            } else if first_inside_second {
                let to_insert = polyline2d_subcurve(&first.nodes, start_positions.0, end_positions.0);
                if to_insert.len() > node_offset {
                    new_nodes.extend_from_slice(&to_insert[node_offset..]);
                }
            } else if second_inside_first {
                let to_insert = polyline2d_subcurve(&second.nodes, start_positions.1, end_positions.1);
                if to_insert.len() > node_offset {
                    new_nodes.extend_from_slice(&to_insert[node_offset..]);
                }
            }
        }

        if !new_nodes.is_empty() {
            result.push(PolyLine2D { nodes: new_nodes });
        }

        result
    }

    fn bool_union(&self, other: &PolyLine2D) -> Vec<PolyLine2D> {
        // TODO: apply real name
        self.bool_intersection(other)
    }
    fn fix_errors(&self) -> Self {
        Self {
            nodes: polyline2d_fix_errors(&self.nodes),
        }
    }
    fn close(&self) -> Self {
        let mut nodes = self.nodes.clone();
        if !nodes.is_empty() && nodes.first() != nodes.last() {
            nodes.push(*nodes.first().unwrap());
        }
        Self { nodes }
    }

    fn get_area(&self) -> f64 {
        if self.nodes.len() < 3 {
            return 0.0;
        }
        let mut area = 0.0;
        for index in 0..self.nodes.len() {
            let next = (index + 1) % self.nodes.len();
            area += self.nodes[index].x * self.nodes[next].y - self.nodes[next].x * self.nodes[index].y;
        }
        0.5 * area.abs()
    }

    fn boundary(&self) -> Vec<Vector2D> { self.nodes.clone() }

    fn contains(&self, point: Vector2DInput) -> PyResult<bool> {
        let point = point.into_vector()?;
        if self.nodes.len() < 3 {
            return Ok(false);
        }
        let mut inside = false;
        let mut previous = self.nodes.last().copied().unwrap();
        for current in &self.nodes {
            let intersects = ((current.y > point.y) != (previous.y > point.y))
                && (point.x < (previous.x - current.x) * (point.y - current.y) / (previous.y - current.y + 1e-18) + current.x);
            if intersects {
                inside = !inside;
            }
            previous = *current;
        }
        Ok(inside)
    }

    #[pyo3(signature = (p1 = None, p2 = None))]
    fn mirror(&self, p1: Option<Vector2DInput>, p2: Option<Vector2DInput>) -> PyResult<Self> {
        let (a, b) = match (p1, p2) {
            (Some(a), Some(b)) => (a.into_vector()?, b.into_vector()?),
            _ => (Vector2D { x: 0.0, y: 0.0 }, Vector2D { x: 0.0, y: 1.0 }),
        };
        let direction = b.sub(a).normalized();
        let nodes = self.nodes.iter().copied().map(|point| {
            let ap = point.sub(a);
            let projection = direction.scale(ap.dot(direction));
            let perpendicular = ap.sub(projection);
            a.add(projection).sub(perpendicular)
        }).collect();
        Ok(Self { nodes })
    }

    #[pyo3(signature = (angle, p1 = None))]
    fn rotate(&self, angle: f64, p1: Option<Vector2DInput>) -> PyResult<Self> {
        let center = match p1 {
            Some(point) => point.into_vector()?,
            None => Vector2D::zero(),
        };
        let (sin_angle, cos_angle) = angle.sin_cos();
        let nodes = self.nodes.iter().copied().map(|point| {
            let point = point.sub(center);
            Vector2D {
                x: point.x * cos_angle - point.y * sin_angle + center.x,
                y: point.x * sin_angle + point.y * cos_angle + center.y,
            }
        }).collect();
        Ok(Self { nodes })
    }

    fn to_3d(&self) -> PolyLine3D {
        PolyLine3D { nodes: self.nodes.iter().copied().map(Vector2D::to_3d).collect() }
    }

    fn __getitem__(&self, index: usize) -> PyResult<Vector2D> {
        self.nodes.get(index).copied().ok_or_else(|| PyValueError::new_err("index out of range"))
    }
}

#[pymethods]
impl PolyLine3D {
    #[new]
    #[pyo3(signature = (nodes = None))]
    fn new(nodes: Option<Vec<Vector3DInput>>) -> PyResult<Self> {
        let mut parsed = Vec::new();
        if let Some(nodes) = nodes {
            for node in nodes {
                parsed.push(node.into_vector()?);
            }
        }
        Ok(Self { nodes: parsed })
    }

    fn __len__(&self) -> usize { self.nodes.len() }
    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let list = PyList::new(py, self.nodes.clone())?;
        Ok(list.into_any().call_method0("__iter__")?.unbind())
    }
    fn __copy__(&self) -> Self { self.clone() }
    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> Self { self.clone() }
    fn copy(&self) -> Self { self.clone() }

    fn __repr__(&self) -> String {
        let mut result = String::from("PolyLine3D[\n");
        for node in &self.nodes {
            result.push_str("  ");
            result.push_str(&node.repr());
            result.push_str(",\n");
        }
        if !self.nodes.is_empty() {
            result.truncate(result.len().saturating_sub(2));
            result.push('\n');
        }
        result.push(']');
        result
    }

    fn __json__(&self) -> Vec<Vec<f64>> { self.nodes.iter().map(VectorOps::components).collect() }
    fn tolist(&self) -> Vec<Vec<f64>> { self.nodes.iter().map(VectorOps::components).collect() }

    fn __hash__(&self) -> u64 { polyline_hash(&self.nodes) }

    #[pyo3(signature = (value, end = None))]
    fn get(&self, value: f64, end: Option<f64>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(end) = end {
            let mut nodes = Vec::new();
            for position in polyline_get_positions(self.nodes.len(), value, end) {
                nodes.push(polyline_get(&self.nodes, position));
            }
            return Py::new(py, Self { nodes }).map(|value| value.into_bound(py).into_any().unbind());
        }
        Py::new(py, polyline_get(&self.nodes, value)).map(|value| value.into_bound(py).into_any().unbind())
    }

    fn get_length(&self) -> f64 { polyline_length(&self.nodes) }
    fn get_positions(&self, start: f64, end: f64) -> Vec<f64> {
        polyline_get_positions(self.nodes.len(), start, end)
    }
    fn get_segments(&self) -> Vec<Vector3D> { polyline_segments(&self.nodes) }
    fn get_segment_lengthes(&self) -> Vec<f64> { self.nodes.windows(2).map(|pair| pair[0].distance(pair[1])).collect() }
    fn get_tangents(&self) -> Vec<Vector3D> { polyline_tangents(&self.nodes) }
    fn walk(&self, start: f64, amount: f64) -> f64 {
        polyline_walk(&self.nodes, start, amount)
    }
    fn resample(&self, num_points: usize) -> Self { Self { nodes: polyline_resample(&self.nodes, num_points) } }
    fn reverse(&self) -> Self { let mut nodes = self.nodes.clone(); nodes.reverse(); Self { nodes } }
    fn scale(&self, factor: Vector3DScaleInput) -> PyResult<Self> {
        Ok(match factor.into_scale()? {
            Vector3DScale::Scalar(scalar) => Self {
                nodes: self.nodes.iter().map(|node| node.scale(scalar)).collect(),
            },
            Vector3DScale::Vector(vector) => Self {
                nodes: self.nodes.iter().map(|node| node.mul(vector)).collect(),
            },
        })
    }
    #[pyo3(name = "move")]
    fn r#move(&self, offset: Vector3DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .map(|node| node.add(offset))
                .collect(),
        })
    }
    fn add(&self, other: &Self) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }
        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.add(right))
                .collect(),
        })
    }
    fn sub(&self, other: &Self) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }
        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.sub(right))
                .collect(),
        })
    }
    fn mix(&self, other: &PolyLine3D, factor: f64) -> Result<Self, SimpleError> {
        if self.nodes.len() != other.nodes.len() {
            return Err(SimpleError::new(format!(
                "PolyLine sizes don't match! ({}/{})",
                self.nodes.len(),
                other.nodes.len()
            )));
        }
        Ok(Self {
            nodes: self
                .nodes
                .iter()
                .copied()
                .zip(other.nodes.iter().copied())
                .map(|(left, right)| left.scale(1.0 - factor).add(right.scale(factor)))
                .collect(),
        })
    }
    fn scale_nodes(&self, factors: Vec<f64>) -> Result<Self, SimpleError> {
        Ok(Self {
            nodes: polyline_scale_nodes(&self.nodes, &factors)?,
        })
    }
    fn __add__(&self, other: &Self) -> Self {
        let mut nodes = Vec::with_capacity(self.nodes.len() + other.nodes.len());
        nodes.extend_from_slice(&self.nodes);
        nodes.extend_from_slice(&other.nodes);
        Self { nodes }
    }
    fn __sub__(&self, other: &Self) -> Result<Self, SimpleError> { self.sub(other) }
    fn __mul__(&self, factor: Vector3DScaleInput) -> PyResult<Self> { self.scale(factor) }
    fn __getitem__(&self, index: usize) -> PyResult<Vector3D> { self.nodes.get(index).copied().ok_or_else(|| PyValueError::new_err("index out of range")) }
}