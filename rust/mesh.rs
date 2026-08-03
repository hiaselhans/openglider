use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use spade::{ConstrainedDelaunayTriangulation, Point2, RefinementParameters, Triangulation};
use std::collections::HashMap;
use std::fs;

use crate::vector::{PolyLine2D, Vector2D, Vector3D};

#[derive(Clone, Debug)]
pub struct MeshTexture {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
}

#[derive(Debug, Clone)]
struct UnionFind {
    parent: Vec<usize>,
    rank: Vec<u8>,
}

impl UnionFind {
    fn new(size: usize) -> Self {
        Self {
            parent: (0..size).collect(),
            rank: vec![0; size],
        }
    }

    fn find(&mut self, node: usize) -> usize {
        if self.parent[node] != node {
            let root = self.find(self.parent[node]);
            self.parent[node] = root;
        }
        self.parent[node]
    }

    fn union(&mut self, a: usize, b: usize) {
        let mut root_a = self.find(a);
        let mut root_b = self.find(b);

        if root_a == root_b {
            return;
        }

        if self.rank[root_a] < self.rank[root_b] {
            std::mem::swap(&mut root_a, &mut root_b);
        }

        self.parent[root_b] = root_a;
        if self.rank[root_a] == self.rank[root_b] {
            self.rank[root_a] += 1;
        }
    }
}

fn cell_coords(point: &Vector3D, cell_size: f64) -> (i64, i64, i64) {
    (
        (point.x / cell_size).floor() as i64,
        (point.y / cell_size).floor() as i64,
        (point.z / cell_size).floor() as i64,
    )
}

fn duplicate_representatives_impl(points: &[Vector3D], max_distance: f64) -> Vec<usize> {
    if points.is_empty() {
        return Vec::new();
    }

    if max_distance <= 0.0 {
        return (0..points.len()).collect();
    }

    let mut union_find = UnionFind::new(points.len());
    let mut buckets: HashMap<(i64, i64, i64), Vec<usize>> = HashMap::new();

    for (index, point) in points.iter().enumerate() {
        let (cx, cy, cz) = cell_coords(point, max_distance);

        for dx in -1..=1 {
            for dy in -1..=1 {
                for dz in -1..=1 {
                    if let Some(candidates) = buckets.get(&(cx + dx, cy + dy, cz + dz)) {
                        for candidate_index in candidates {
                            if points[index].distance(&points[*candidate_index]) < max_distance {
                                union_find.union(index, *candidate_index);
                            }
                        }
                    }
                }
            }
        }

        buckets.entry((cx, cy, cz)).or_default().push(index);
    }

    let mut root_to_representative: HashMap<usize, usize> = HashMap::new();
    let mut representatives = vec![0usize; points.len()];

    for index in 0..points.len() {
        let root = union_find.find(index);
        root_to_representative
            .entry(root)
            .and_modify(|existing| {
                if index < *existing {
                    *existing = index;
                }
            })
            .or_insert(index);
    }

    for (index, representative_slot) in representatives.iter_mut().enumerate() {
        let root = union_find.find(index);
        *representative_slot = *root_to_representative.get(&root).unwrap();
    }

    representatives
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Line {
    #[pyo3(get, set)]
    pub a: usize,
    #[pyo3(get, set)]
    pub b: usize,
}

#[pymethods]
impl Line {
    #[new]
    fn new(a: usize, b: usize) -> Self {
        Self { a, b }
    }

    fn as_tuple(&self) -> (usize, usize) {
        (self.a, self.b)
    }

}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Triangle {
    #[pyo3(get, set)]
    pub a: usize,
    #[pyo3(get, set)]
    pub b: usize,
    #[pyo3(get, set)]
    pub c: usize,
}

#[pymethods]
impl Triangle {
    #[new]
    fn new(a: usize, b: usize, c: usize) -> Self {
        Self { a, b, c }
    }

    fn as_tuple(&self) -> (usize, usize, usize) {
        (self.a, self.b, self.c)
    }

}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Quad {
    #[pyo3(get, set)]
    pub a: usize,
    #[pyo3(get, set)]
    pub b: usize,
    #[pyo3(get, set)]
    pub c: usize,
    #[pyo3(get, set)]
    pub d: usize,
}

#[pymethods]
impl Quad {
    #[new]
    fn new(a: usize, b: usize, c: usize, d: usize) -> Self {
        Self { a, b, c, d }
    }

    fn as_tuple(&self) -> (usize, usize, usize, usize) {
        (self.a, self.b, self.c, self.d)
    }

}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct MeshObject {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub color: (u8, u8, u8),
    #[pyo3(get)]
    pub lines: Vec<Line>,
    #[pyo3(get)]
    pub triangles: Vec<Triangle>,
    #[pyo3(get)]
    pub quads: Vec<Quad>,
}

#[pymethods]
impl MeshObject {
    #[new]
    #[pyo3(signature = (name, color = (255, 255, 255), lines = None, triangles = None, quads = None))]
    fn new(
        name: String,
        color: (u8, u8, u8),
        lines: Option<Vec<Line>>,
        triangles: Option<Vec<Triangle>>,
        quads: Option<Vec<Quad>>,
    ) -> Self {
        Self {
            name,
            color,
            lines: lines.unwrap_or_default(),
            triangles: triangles.unwrap_or_default(),
            quads: quads.unwrap_or_default(),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Mesh {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get)]
    pub points: Vec<Vector3D>,
    #[pyo3(get)]
    pub objects: Vec<MeshObject>,
    pub uv_coords: Option<Vec<[f32; 2]>>,
    pub texture: Option<MeshTexture>,
}

#[pymethods]
impl Mesh {
    #[new]
    #[pyo3(signature = (name = "unnamed".to_string()))]
    fn new(name: String) -> Self {
        Self {
            name,
            points: Vec::new(),
            objects: Vec::new(),
            uv_coords: None,
            texture: None,
        }
    }

    #[staticmethod]
    #[pyo3(signature = (vertices, polygons, boundaries = None, name = "unnamed".to_string(), node_attributes = None))]
    fn from_indexed(
        py: Python<'_>,
        vertices: Vec<Vector3D>,
        polygons: HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>>,
        boundaries: Option<Py<PyAny>>,
        name: String,
        node_attributes: Option<Vec<Py<PyAny>>>,
    ) -> PyResult<Self> {
        let _ = boundaries;
        let mut mesh = Self::new(name);
        mesh.points = vertices;

        if let Some(attrs) = node_attributes {
            mesh.uv_coords = parse_uv_node_attributes(py, &attrs)?;
        }

        for (object_name, object_polygons) in polygons {
            let color = parse_color_code(&object_name);
            let mut object = MeshObject {
                name: object_name,
                color,
                lines: Vec::new(),
                triangles: Vec::new(),
                quads: Vec::new(),
            };

            for (indices_raw, attributes) in object_polygons {
                let _ = attributes;
                let indices = extract_indices(py, &indices_raw)?;
                match indices.len() {
                    2 => object.lines.push(Line {
                        a: indices[0],
                        b: indices[1],
                    }),
                    3 => object.triangles.push(Triangle {
                        a: indices[0],
                        b: indices[1],
                        c: indices[2],
                    }),
                    4 => object.quads.push(Quad {
                        a: indices[0],
                        b: indices[1],
                        c: indices[2],
                        d: indices[3],
                    }),
                    _ if indices.len() > 4 => {
                        for i in 1..indices.len() - 1 {
                            object.triangles.push(Triangle {
                                a: indices[0],
                                b: indices[i],
                                c: indices[i + 1],
                            });
                        }
                    }
                    _ => {}
                }
            }

            mesh.objects.push(object);
        }

        Ok(mesh)
    }

    #[staticmethod]
    #[pyo3(signature = (path, name = None))]
    fn from_obj(_py: Python<'_>, path: &Bound<'_, PyAny>, name: Option<String>) -> PyResult<Self> {
        let path_string = stringify_path(path)?;
        let content = fs::read_to_string(&path_string).map_err(|error| {
            pyo3::exceptions::PyIOError::new_err(format!("failed to read {path_string}: {error}"))
        })?;

        let mut points: Vec<Vector3D> = Vec::new();
        let mut objects: HashMap<String, MeshObject> = HashMap::new();
        let mut current_group = name.clone().unwrap_or_else(|| {
            std::path::Path::new(&path_string)
                .file_stem()
                .and_then(|stem| stem.to_str())
                .unwrap_or("obj")
                .to_string()
        });

        for line in content.lines() {
            let stripped = line.trim();
            if stripped.is_empty() || stripped.starts_with('#') {
                continue;
            }

            let parts: Vec<&str> = stripped.split_whitespace().collect();
            if parts.is_empty() {
                continue;
            }

            match parts[0] {
                "v" if parts.len() >= 4 => {
                    let x = parts[1].parse::<f64>().unwrap_or(0.0);
                    let y = parts[2].parse::<f64>().unwrap_or(0.0);
                    let z = parts[3].parse::<f64>().unwrap_or(0.0);
                    points.push(Vector3D { x, y, z });
                }
                "o" | "g" if parts.len() >= 2 => {
                    current_group = parts[1..].join(" ");
                }
                "f" | "l" if parts.len() >= 3 => {
                    let mut indices: Vec<usize> = Vec::new();
                    for token in &parts[1..] {
                        let vertex_token = token.split('/').next().unwrap_or("");
                        if vertex_token.is_empty() {
                            continue;
                        }
                        let raw = vertex_token.parse::<isize>().unwrap_or(0);
                        let resolved = if raw > 0 {
                            (raw - 1) as usize
                        } else if raw < 0 {
                            (points.len() as isize + raw) as usize
                        } else {
                            continue;
                        };
                        indices.push(resolved);
                    }

                    if indices.is_empty() {
                        continue;
                    }

                    let object = objects.entry(current_group.clone()).or_insert_with(|| {
                        MeshObject {
                            name: current_group.clone(),
                            color: parse_color_code(&current_group),
                            lines: Vec::new(),
                            triangles: Vec::new(),
                            quads: Vec::new(),
                        }
                    });

                    match indices.len() {
                        2 => object.lines.push(Line {
                            a: indices[0],
                            b: indices[1],
                        }),
                        3 => object.triangles.push(Triangle {
                            a: indices[0],
                            b: indices[1],
                            c: indices[2],
                        }),
                        4 => object.quads.push(Quad {
                            a: indices[0],
                            b: indices[1],
                            c: indices[2],
                            d: indices[3],
                        }),
                        _ => {
                            for i in 1..indices.len() - 1 {
                                object.triangles.push(Triangle {
                                    a: indices[0],
                                    b: indices[i],
                                    c: indices[i + 1],
                                });
                            }
                        }
                    }
                }
                _ => {}
            }
        }

        let mesh_name = name.unwrap_or_else(|| {
            std::path::Path::new(&path_string)
                .file_stem()
                .and_then(|stem| stem.to_str())
                .unwrap_or("obj")
                .to_string()
        });

        Ok(Self {
            name: mesh_name,
            points,
            objects: objects.into_values().collect(),
            uv_coords: None,
            texture: None,
        })
    }

    fn set_uv_coords(&mut self, uv_coords: Vec<(f32, f32)>) -> PyResult<()> {
        if uv_coords.len() != self.points.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "uv_coords length ({}) must match vertex count ({})",
                uv_coords.len(),
                self.points.len(),
            )));
        }

        self.uv_coords = Some(uv_coords.into_iter().map(|(u, v)| [u, v]).collect());
        Ok(())
    }

    #[pyo3(signature = (projection = "xy".to_string()))]
    fn generate_uvs(&mut self, projection: String) -> PyResult<()> {
        if self.points.is_empty() {
            self.uv_coords = Some(Vec::new());
            return Ok(());
        }

        let (axis_u, axis_v) = match projection.as_str() {
            "xy" => (0usize, 1usize),
            "xz" => (0usize, 2usize),
            "yz" => (1usize, 2usize),
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "projection must be one of: xy, xz, yz",
                ));
            }
        };

        let mut min_vals = [f64::INFINITY; 3];
        let mut max_vals = [f64::NEG_INFINITY; 3];
        for p in &self.points {
            let values = [p.x, p.y, p.z];
            for i in 0..3 {
                min_vals[i] = min_vals[i].min(values[i]);
                max_vals[i] = max_vals[i].max(values[i]);
            }
        }

        let du = (max_vals[axis_u] - min_vals[axis_u]).max(1e-9);
        let dv = (max_vals[axis_v] - min_vals[axis_v]).max(1e-9);

        self.uv_coords = Some(
            self.points
                .iter()
                .map(|p| {
                    let values = [p.x, p.y, p.z];
                    let u = ((values[axis_u] - min_vals[axis_u]) / du) as f32;
                    let v = ((values[axis_v] - min_vals[axis_v]) / dv) as f32;
                    [u, v]
                })
                .collect(),
        );

        Ok(())
    }

    fn clear_uvs(&mut self) {
        self.uv_coords = None;
    }

    fn get_uv_coords(&self) -> Option<Vec<(f32, f32)>> {
        self.uv_coords.as_ref().map(|uvs| {
            uvs.iter().map(|uv| (uv[0], uv[1])).collect()
        })
    }

    fn remap_uvs_bilinear(
        &mut self,
        back_left: (f64, f64),
        back_right: (f64, f64),
        front_right: (f64, f64),
        front_left: (f64, f64),
        bbox: (f64, f64, f64, f64),
    ) {
        let local_uvs = match self.uv_coords.take() {
            Some(uvs) => uvs,
            None => return,
        };

        let (min_x, max_x, min_y, max_y) = bbox;
        let dx = (max_x - min_x).max(1e-9);
        let dy = (max_y - min_y).max(1e-9);
        let (bl_x, bl_y) = back_left;
        let (br_x, br_y) = back_right;
        let (fr_x, fr_y) = front_right;
        let (fl_x, fl_y) = front_left;

        self.uv_coords = Some(
            local_uvs
                .iter()
                .map(|uv| {
                    let lu = uv[0] as f64;
                    let lv = uv[1] as f64;
                    let gx = fl_x * (1.0 - lu) * (1.0 - lv)
                        + bl_x * lu * (1.0 - lv)
                        + fr_x * (1.0 - lu) * lv
                        + br_x * lu * lv;
                    let gy = fl_y * (1.0 - lu) * (1.0 - lv)
                        + bl_y * lu * (1.0 - lv)
                        + fr_y * (1.0 - lu) * lv
                        + br_y * lu * lv;
                    let norm_u = ((gx - min_x) / dx) as f32;
                    let norm_v = (1.0 - (gy - min_y) / dy) as f32;
                    [norm_u.clamp(0.0, 1.0), norm_v.clamp(0.0, 1.0)]
                })
                .collect(),
        );
    }

    /// Map per-vertex (span_normalized, chord_p) UV coords (stored by Panel::get_mesh
    /// when called with x_span_left/right) to final texture UV.
    ///
    /// span_normalized: rib x-value divided by max span, in [0,1] for the right half-wing.
    /// chord_p:         signed profile x-value (0 = LE, +ve = upper surface, -ve = lower).
    ///
    /// Stacking: upper panels (chord_p >= 0) sit above the LE line;
    ///           lower panels (chord_p < 0) are shifted by lower_offset so they form a
    ///           separate "lower sail" shape below.
    ///
    /// tex_u: derived from span (negate_span = true for the mirrored left half-wing).
    /// tex_v: 1 − normalised layout_y  (v-flip so WGPU v=0 is the top of the image).
    fn remap_uvs_stacked(
        &mut self,
        span_min: f64,
        span_max: f64,
        y_min: f64,
        y_max: f64,
        lower_offset: f64,
        negate_span: bool,
    ) {
        let local_uvs = match self.uv_coords.take() {
            Some(uvs) => uvs,
            None => return,
        };

        let d_span = (span_max - span_min).max(1e-9);
        let d_y = (y_max - y_min).max(1e-9);

        self.uv_coords = Some(
            local_uvs
                .iter()
                .map(|uv| {
                    let span_norm = uv[0] as f64;
                    let chord_p = uv[1] as f64;
                    let span_eff = if negate_span { -span_norm } else { span_norm };
                    let layout_y = if chord_p < 0.0 { chord_p + lower_offset } else { chord_p };
                    let tex_u = ((span_eff - span_min) / d_span) as f32;
                    let tex_v = (1.0 - (layout_y - y_min) / d_y) as f32;
                    [tex_u.clamp(0.0, 1.0), tex_v.clamp(0.0, 1.0)]
                })
                .collect(),
        );
    }

    /// Mirror the mesh geometry (and fix winding order) without touching UV coordinates.
    /// Unlike mirror(), this leaves uv_coords untouched so that remap_uvs_stacked can
    /// use the original stored (span_norm, chord_p) values even after geometry mirroring.
    #[pyo3(signature = (axis = "x"))]
    fn mirror_geometry_only(&mut self, axis: &str) -> Self {
        let factors: (f64, f64, f64) = match axis {
            "y" => (1.0, -1.0, 1.0),
            "z" => (1.0, 1.0, -1.0),
            _ => (-1.0, 1.0, 1.0),
        };
        for point in &mut self.points {
            point.x *= factors.0;
            point.y *= factors.1;
            point.z *= factors.2;
        }
        for object in &mut self.objects {
            for triangle in &mut object.triangles {
                std::mem::swap(&mut triangle.b, &mut triangle.c);
            }
            for quad in &mut object.quads {
                let a = quad.a; let b = quad.b; let c = quad.c; let d = quad.d;
                quad.a = d; quad.b = c; quad.c = b; quad.d = a;
            }
        }
        self.clone()
    }

    fn set_texture_rgba(&mut self, width: u32, height: u32, rgba: Vec<u8>) -> PyResult<()> {
        let expected = width as usize * height as usize * 4usize;
        if rgba.len() != expected {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "rgba length ({}) does not match width*height*4 ({})",
                rgba.len(),
                expected,
            )));
        }

        self.texture = Some(MeshTexture { width, height, rgba });
        Ok(())
    }

    fn clear_texture(&mut self) {
        self.texture = None;
    }

    fn has_texture(&self) -> bool {
        self.texture.is_some()
    }

    fn add_point(&mut self, point: PyRef<'_, Vector3D>) -> usize {
        let index = self.points.len();
        self.points.push(*point);
        index
    }

    #[pyo3(signature = (name, color = (255, 255, 255)))]
    fn add_object(&mut self, name: String, color: (u8, u8, u8)) -> usize {
        self.objects.push(MeshObject {
            name,
            color,
            lines: Vec::new(),
            triangles: Vec::new(),
            quads: Vec::new(),
        });
        self.objects.len() - 1
    }

    fn add_line(&mut self, object_index: usize, line: PyRef<'_, Line>) {
        if let Some(object) = self.objects.get_mut(object_index) {
            object.lines.push(line.clone());
        }
    }

    fn add_triangle(&mut self, object_index: usize, triangle: PyRef<'_, Triangle>) {
        if let Some(object) = self.objects.get_mut(object_index) {
            object.triangles.push(triangle.clone());
        }
    }

    fn add_quad(&mut self, object_index: usize, quad: PyRef<'_, Quad>) {
        if let Some(object) = self.objects.get_mut(object_index) {
            object.quads.push(quad.clone());
        }
    }

    #[getter]
    fn vertices(&self) -> Vec<Vector3D> {
        self.points.clone()
    }

    #[getter]
    fn polygons(
        &self,
        py: Python<'_>,
    ) -> PyResult<HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>>> {
        Ok(self.polygons_dict(py))
    }

    fn get_indexed(
        &self,
        py: Python<'_>,
    ) -> PyResult<(
        Vec<Vector3D>,
        HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>>,
        HashMap<String, Vec<usize>>,
    )> {
        Ok((
            self.points.clone(),
            self.polygons_dict(py),
            HashMap::new(),
        ))
    }

    fn point_vectors(&self) -> Vec<Vector3D> {
        self.points.clone()
    }

    fn copy(&self) -> Self {
        self.clone()
    }

    fn __copy__(&self) -> Self {
        self.clone()
    }

    fn __deepcopy__(&self, _memo: &Bound<'_, PyAny>) -> Self {
        self.clone()
    }

    fn __repr__(&self) -> String {
        let face_count: usize = self
            .objects
            .iter()
            .map(|object| object.lines.len() + object.triangles.len() + object.quads.len())
            .sum();
        format!(
            "Mesh {} ({} faces, {} vertices)",
            self.name,
            face_count,
            self.points.len()
        )
    }

    #[pyo3(signature = (axis = "x"))]
    fn mirror(&mut self, axis: &str) -> Self {
        let factors = match axis {
            "y" => (1.0, -1.0, 1.0),
            "z" => (1.0, 1.0, -1.0),
            _ => (-1.0, 1.0, 1.0),
        };

        for point in &mut self.points {
            point.x *= factors.0;
            point.y *= factors.1;
            point.z *= factors.2;
        }

        if let Some(uvs) = self.uv_coords.as_mut() {
            if axis == "x" {
                for uv in uvs {
                    uv[0] = 1.0 - uv[0];
                }
            } else if axis == "y" {
                for uv in uvs {
                    uv[1] = 1.0 - uv[1];
                }
            }
        }

        for object in &mut self.objects {
            for triangle in &mut object.triangles {
                std::mem::swap(&mut triangle.b, &mut triangle.c);
            }
            for quad in &mut object.quads {
                let a = quad.a;
                let b = quad.b;
                let c = quad.c;
                let d = quad.d;
                quad.a = d;
                quad.b = c;
                quad.c = b;
                quad.d = a;
            }
        }

        self.clone()
    }

    fn triangularize(&self) -> Self {
        let mut result = self.clone();
        for object in &mut result.objects {
            let mut quads_as_triangles = Vec::new();
            for quad in &object.quads {
                quads_as_triangles.push(Triangle {
                    a: quad.a,
                    b: quad.b,
                    c: quad.c,
                });
                quads_as_triangles.push(Triangle {
                    a: quad.a,
                    b: quad.c,
                    c: quad.d,
                });
            }
            object.triangles.extend(quads_as_triangles);
            object.quads.clear();
        }
        result
    }

    fn __add__(&self, other: &Mesh) -> Self {
        let mut result = self.clone();
        result.merge_from(other);
        result
    }

    fn __getitem__(&self, item: String) -> PyResult<Self> {
        let selected: Vec<MeshObject> = self
            .objects
            .iter()
            .filter(|object| object.name == item)
            .cloned()
            .collect();
        if selected.is_empty() {
            return Err(pyo3::exceptions::PyKeyError::new_err(item));
        }
        Ok(Self {
            name: self.name.clone(),
            points: self.points.clone(),
            objects: selected,
            uv_coords: self.uv_coords.clone(),
            texture: self.texture.clone(),
        })
    }

    #[pyo3(signature = (boundaries = None))]
    fn delete_duplicates(&mut self, boundaries: Option<Py<PyAny>>) {
        let _ = boundaries;
        self.merge_duplicate_points(1e-10);
    }

    fn polygon_size(&self) -> (f64, f64, f64) {
        let mut areas = Vec::new();
        for object in &self.objects {
            for triangle in &object.triangles {
                let area = triangle_area(
                    &self.points[triangle.a],
                    &self.points[triangle.b],
                    &self.points[triangle.c],
                );
                areas.push(area);
            }
            for quad in &object.quads {
                let a1 = triangle_area(
                    &self.points[quad.a],
                    &self.points[quad.b],
                    &self.points[quad.c],
                );
                let a2 = triangle_area(
                    &self.points[quad.a],
                    &self.points[quad.c],
                    &self.points[quad.d],
                );
                areas.push(a1 + a2);
            }
        }

        if areas.is_empty() {
            return (0.0, 0.0, 0.0);
        }

        let min = areas.iter().copied().fold(f64::INFINITY, f64::min);
        let max = areas.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let avg = areas.iter().sum::<f64>() / areas.len() as f64;
        (min, max, avg)
    }

    #[getter]
    fn bounding_box(&self) -> (Vector3D, Vector3D) {
        if self.points.is_empty() {
            return (
                Vector3D { x: 0.0, y: 0.0, z: 0.0 },
                Vector3D { x: 0.0, y: 0.0, z: 0.0 },
            );
        }

        let mut min_x = self.points[0].x;
        let mut min_y = self.points[0].y;
        let mut min_z = self.points[0].z;
        let mut max_x = self.points[0].x;
        let mut max_y = self.points[0].y;
        let mut max_z = self.points[0].z;

        for point in &self.points {
            min_x = min_x.min(point.x);
            min_y = min_y.min(point.y);
            min_z = min_z.min(point.z);
            max_x = max_x.max(point.x);
            max_y = max_y.max(point.y);
            max_z = max_z.max(point.z);
        }

        (
            Vector3D {
                x: min_x,
                y: min_y,
                z: min_z,
            },
            Vector3D {
                x: max_x,
                y: max_y,
                z: max_z,
            },
        )
    }

    #[pyo3(signature = (path = None, offset = 0.0))]
    fn export_obj(&self, py: Python<'_>, path: Option<&Bound<'_, PyAny>>, offset: f64) -> PyResult<String> {
        let mut output = String::new();

        for point in &self.points {
            output.push_str(&format!("v {:.6} {:.6} {:.6}\n", point.x, point.y, point.z));
        }

        for object in &self.objects {
            output.push_str(&format!("o {}\n", object.name));
            for line in &object.lines {
                output.push_str(&format!(
                    "l {} {}\n",
                    line.a as f64 + offset + 1.0,
                    line.b as f64 + offset + 1.0
                ));
            }
            for triangle in &object.triangles {
                output.push_str(&format!(
                    "f {} {} {}\n",
                    triangle.a as f64 + offset + 1.0,
                    triangle.b as f64 + offset + 1.0,
                    triangle.c as f64 + offset + 1.0
                ));
            }
            for quad in &object.quads {
                output.push_str(&format!(
                    "f {} {} {} {}\n",
                    quad.a as f64 + offset + 1.0,
                    quad.b as f64 + offset + 1.0,
                    quad.c as f64 + offset + 1.0,
                    quad.d as f64 + offset + 1.0
                ));
            }
        }

        if let Some(path_value) = path {
            let path_string = stringify_path(path_value)?;
            fs::write(&path_string, &output).map_err(|error| {
                pyo3::exceptions::PyIOError::new_err(format!("failed to write {path_string}: {error}"))
            })?;
        }

        let _ = py;
        Ok(output)
    }

    #[pyo3(signature = (path = None, version = "AC1021".to_string()))]
    fn export_dxf(&self, path: Option<&Bound<'_, PyAny>>, version: String) -> PyResult<String> {
        let mut output = String::new();
        output.push_str("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\n");
        output.push_str(&version);
        output.push_str("\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n");

        for object in &self.objects {
            let layer_name = object.name.replace('#', "_");

            for line in &object.lines {
                let p1 = self.points[line.a];
                let p2 = self.points[line.b];
                output.push_str("0\nLINE\n8\n");
                output.push_str(&layer_name);
                output.push_str("\n10\n");
                output.push_str(&format!("{}\n20\n{}\n30\n{}\n", p1.x, p1.y, p1.z));
                output.push_str("11\n");
                output.push_str(&format!("{}\n21\n{}\n31\n{}\n", p2.x, p2.y, p2.z));
            }

            for triangle in &object.triangles {
                let p1 = self.points[triangle.a];
                let p2 = self.points[triangle.b];
                let p3 = self.points[triangle.c];
                output.push_str("0\n3DFACE\n8\n");
                output.push_str(&layer_name);
                output.push_str("\n10\n");
                output.push_str(&format!("{}\n20\n{}\n30\n{}\n", p1.x, p1.y, p1.z));
                output.push_str("11\n");
                output.push_str(&format!("{}\n21\n{}\n31\n{}\n", p2.x, p2.y, p2.z));
                output.push_str("12\n");
                output.push_str(&format!("{}\n22\n{}\n32\n{}\n", p3.x, p3.y, p3.z));
                output.push_str("13\n");
                output.push_str(&format!("{}\n23\n{}\n33\n{}\n", p3.x, p3.y, p3.z));
            }

            for quad in &object.quads {
                let p1 = self.points[quad.a];
                let p2 = self.points[quad.b];
                let p3 = self.points[quad.c];
                let p4 = self.points[quad.d];
                output.push_str("0\n3DFACE\n8\n");
                output.push_str(&layer_name);
                output.push_str("\n10\n");
                output.push_str(&format!("{}\n20\n{}\n30\n{}\n", p1.x, p1.y, p1.z));
                output.push_str("11\n");
                output.push_str(&format!("{}\n21\n{}\n31\n{}\n", p2.x, p2.y, p2.z));
                output.push_str("12\n");
                output.push_str(&format!("{}\n22\n{}\n32\n{}\n", p3.x, p3.y, p3.z));
                output.push_str("13\n");
                output.push_str(&format!("{}\n23\n{}\n33\n{}\n", p4.x, p4.y, p4.z));
            }
        }

        output.push_str("0\nENDSEC\n0\nEOF\n");

        if let Some(path_value) = path {
            let path_string = stringify_path(path_value)?;
            fs::write(&path_string, &output).map_err(|error| {
                pyo3::exceptions::PyIOError::new_err(format!("failed to write {path_string}: {error}"))
            })?;
        }

        Ok(output)
    }

    fn merge_duplicate_points(&mut self, max_distance: f64) -> Vec<usize> {
        let vectors = self.point_vectors();
        let representatives = duplicate_representatives_impl(&vectors, max_distance);

        let mut representative_to_new_index: HashMap<usize, usize> = HashMap::new();
        let mut merged_points = Vec::new();
        let mut old_to_new = vec![0usize; self.points.len()];

        for (old_index, representative) in representatives.iter().enumerate() {
            let new_index = if let Some(existing) = representative_to_new_index.get(representative) {
                *existing
            } else {
                let created_index = merged_points.len();
                representative_to_new_index.insert(*representative, created_index);
                merged_points.push(self.points[*representative]);
                created_index
            };
            old_to_new[old_index] = new_index;
        }

        self.points = merged_points;

        if let Some(old_uvs) = &self.uv_coords {
            let mut new_uvs = vec![[0.0_f32, 0.0_f32]; self.points.len()];
            let mut seen = vec![false; self.points.len()];
            for (old_index, new_index) in old_to_new.iter().enumerate() {
                if !seen[*new_index] {
                    new_uvs[*new_index] = old_uvs[old_index];
                    seen[*new_index] = true;
                }
            }
            self.uv_coords = Some(new_uvs);
        }

        for object in &mut self.objects {
            object.lines = object
                .lines
                .iter()
                .filter_map(|line| {
                    let mapped = Line {
                        a: old_to_new[line.a],
                        b: old_to_new[line.b],
                    };
                    if mapped.a == mapped.b {
                        None
                    } else {
                        Some(mapped)
                    }
                })
                .collect();

            object.triangles = object
                .triangles
                .iter()
                .filter_map(|triangle| {
                    let mapped = Triangle {
                        a: old_to_new[triangle.a],
                        b: old_to_new[triangle.b],
                        c: old_to_new[triangle.c],
                    };
                    if mapped.a == mapped.b || mapped.b == mapped.c || mapped.a == mapped.c {
                        None
                    } else {
                        Some(mapped)
                    }
                })
                .collect();

            object.quads = object
                .quads
                .iter()
                .filter_map(|quad| {
                    let mapped = Quad {
                        a: old_to_new[quad.a],
                        b: old_to_new[quad.b],
                        c: old_to_new[quad.c],
                        d: old_to_new[quad.d],
                    };
                    let mut unique = std::collections::HashSet::new();
                    unique.insert(mapped.a);
                    unique.insert(mapped.b);
                    unique.insert(mapped.c);
                    unique.insert(mapped.d);
                    if unique.len() < 4 {
                        None
                    } else {
                        Some(mapped)
                    }
                })
                .collect();
        }

        old_to_new
    }

    fn __json__(
        &self,
        py: Python<'_>,
    ) -> PyResult<(Vec<Vector3D>, HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>>, HashMap<String, Vec<usize>>)> {
        self.get_indexed(py)
    }
}

impl Mesh {
    fn merge_from(&mut self, other: &Mesh) {
        let offset = self.points.len();

        if self.uv_coords.is_some() || other.uv_coords.is_some() {
            let mut merged_uvs = self
                .uv_coords
                .clone()
                .unwrap_or_else(|| vec![[0.0, 0.0]; self.points.len()]);

            if let Some(other_uvs) = &other.uv_coords {
                merged_uvs.extend(other_uvs.iter().copied());
            } else {
                merged_uvs.extend(vec![[0.0, 0.0]; other.points.len()]);
            }

            self.uv_coords = Some(merged_uvs);
        }

        self.points.extend(other.points.iter().copied());

        for other_object in &other.objects {
            if let Some(target) = self.objects.iter_mut().find(|obj| obj.name == other_object.name) {
                target.lines.extend(other_object.lines.iter().map(|line| Line {
                    a: line.a + offset,
                    b: line.b + offset,
                }));
                target.triangles.extend(other_object.triangles.iter().map(|triangle| Triangle {
                    a: triangle.a + offset,
                    b: triangle.b + offset,
                    c: triangle.c + offset,
                }));
                target.quads.extend(other_object.quads.iter().map(|quad| Quad {
                    a: quad.a + offset,
                    b: quad.b + offset,
                    c: quad.c + offset,
                    d: quad.d + offset,
                }));
            } else {
                self.objects.push(MeshObject {
                    name: other_object.name.clone(),
                    color: other_object.color,
                    lines: other_object.lines.iter().map(|line| Line {
                        a: line.a + offset,
                        b: line.b + offset,
                    }).collect(),
                    triangles: other_object.triangles.iter().map(|triangle| Triangle {
                        a: triangle.a + offset,
                        b: triangle.b + offset,
                        c: triangle.c + offset,
                    }).collect(),
                    quads: other_object.quads.iter().map(|quad| Quad {
                        a: quad.a + offset,
                        b: quad.b + offset,
                        c: quad.c + offset,
                        d: quad.d + offset,
                    }).collect(),
                });
            }
        }
    }

    fn polygons_dict(&self, py: Python<'_>) -> HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>> {
        let mut polygons: HashMap<String, Vec<(Py<PyAny>, Py<PyAny>)>> = HashMap::new();

        for object in &self.objects {
            let mut group: Vec<(Py<PyAny>, Py<PyAny>)> = Vec::new();

            for line in &object.lines {
                let indices = PyTuple::new(py, [line.a, line.b]).unwrap().into_any().unbind();
                let attributes = PyDict::new(py).into_any().unbind();
                group.push((indices, attributes));
            }

            for triangle in &object.triangles {
                let indices = PyTuple::new(py, [triangle.a, triangle.b, triangle.c])
                    .unwrap()
                    .into_any()
                    .unbind();
                let attributes = PyDict::new(py).into_any().unbind();
                group.push((indices, attributes));
            }

            for quad in &object.quads {
                let indices = PyTuple::new(py, [quad.a, quad.b, quad.c, quad.d])
                    .unwrap()
                    .into_any()
                    .unbind();
                let attributes = PyDict::new(py).into_any().unbind();
                group.push((indices, attributes));
            }

            polygons.insert(object.name.clone(), group);
        }

        polygons
    }
}

fn stringify_path(path: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(path_string) = path.extract::<String>() {
        return Ok(path_string);
    }
    let text = path.str()?.to_str()?.to_string();
    Ok(text)
}

fn extract_indices(py: Python<'_>, value: &Py<PyAny>) -> PyResult<Vec<usize>> {
    let bound = value.bind(py);
    if let Ok(indices) = bound.extract::<Vec<usize>>() {
        return Ok(indices);
    }

    if let Ok(nodes) = bound.getattr("nodes") {
        if let Ok(indices) = nodes.extract::<Vec<usize>>() {
            return Ok(indices);
        }
    }

    Err(pyo3::exceptions::PyTypeError::new_err(
        "polygon index data must be a sequence of integers",
    ))
}

fn parse_uv_node_attributes(py: Python<'_>, node_attributes: &[Py<PyAny>]) -> PyResult<Option<Vec<[f32; 2]>>> {
    let mut uv_coords: Vec<[f32; 2]> = Vec::with_capacity(node_attributes.len());
    let mut has_any = false;

    for attr in node_attributes {
        let bound = attr.bind(py);
        if let Ok(dict) = bound.cast::<PyDict>() {
            let uv_value = dict.get_item("uv")?;
            if let Some(value) = uv_value {
                if let Ok((u, v)) = value.extract::<(f32, f32)>() {
                    uv_coords.push([u, v]);
                    has_any = true;
                    continue;
                }
                if let Ok(values) = value.extract::<Vec<f32>>() {
                    if values.len() == 2 {
                        uv_coords.push([values[0], values[1]]);
                        has_any = true;
                        continue;
                    }
                }
            }
        }

        uv_coords.push([0.0, 0.0]);
    }

    if !has_any {
        return Ok(None);
    }

    Ok(Some(uv_coords))
}

fn parse_color_code(name: &str) -> (u8, u8, u8) {
    if let Some((_, hex)) = name.rsplit_once('#') {
        if hex.len() == 6 {
            let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(255);
            let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(255);
            let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(255);
            return (r, g, b);
        }
    }
    (255, 255, 255)
}

fn triangle_area(a: &Vector3D, b: &Vector3D, c: &Vector3D) -> f64 {
    let abx = b.x - a.x;
    let aby = b.y - a.y;
    let abz = b.z - a.z;
    let acx = c.x - a.x;
    let acy = c.y - a.y;
    let acz = c.z - a.z;

    let cx = aby * acz - abz * acy;
    let cy = abz * acx - abx * acz;
    let cz = abx * acy - aby * acx;

    (cx * cx + cy * cy + cz * cz).sqrt() * 0.5
}

#[pyclass(skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct Triangulation2D {
    #[pyo3(get)]
    pub nodes: Vec<Vector2D>,
    #[pyo3(get)]
    pub triangles: Vec<(usize, usize, usize)>,
}

fn close_ring(nodes: &[Vector2D]) -> Vec<Vector2D> {
    if nodes.is_empty() {
        return Vec::new();
    }

    let mut ring = nodes.to_vec();
    if let (Some(first), Some(last)) = (ring.first().copied(), ring.last().copied()) {
        if first != last {
            ring.push(first);
        }
    }
    ring
}

fn ring_area(ring: &[Vector2D]) -> f64 {
    if ring.len() < 3 {
        return 0.0;
    }

    let mut area = 0.0;
    for pair in ring.windows(2) {
        area += pair[0].x * pair[1].y - pair[1].x * pair[0].y;
    }
    0.5 * area
}

fn point_in_ring(point: Vector2D, ring: &[Vector2D]) -> bool {
    if ring.len() < 4 {
        return false;
    }

    let mut inside = false;
    for pair in ring.windows(2) {
        let a = pair[0];
        let b = pair[1];
        let intersects = (a.y > point.y) != (b.y > point.y)
            && point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x;
        if intersects {
            inside = !inside;
        }
    }
    inside
}

fn classify_triangle(center: Vector2D, outline: &[Vector2D], holes: &[Vec<Vector2D>]) -> bool {
    if !point_in_ring(center, outline) {
        return false;
    }
    for hole in holes {
        if point_in_ring(center, hole) {
            return false;
        }
    }
    true
}

fn triangle_area_2d(a: Point2<f64>, b: Point2<f64>, c: Point2<f64>) -> f64 {
    ((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)).abs() * 0.5
}

fn add_ring_constraints(
    ring: &[Vector2D],
    cdt: &mut ConstrainedDelaunayTriangulation<Point2<f64>>,
    handles: &mut HashMap<(u64, u64), spade::handles::FixedVertexHandle>,
) -> PyResult<()> {
    if ring.len() < 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "each ring needs at least 3 distinct points",
        ));
    }

    let mut ring_handles = Vec::with_capacity(ring.len() - 1);
    for point in &ring[..ring.len() - 1] {
        let key = (point.x.to_bits(), point.y.to_bits());
        let handle = if let Some(existing) = handles.get(&key) {
            *existing
        } else {
            let inserted = cdt
                .insert(Point2::new(point.x, point.y))
                .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.to_string()))?;
            handles.insert(key, inserted);
            inserted
        };
        ring_handles.push(handle);
    }

    for edge in ring_handles.windows(2) {
        cdt.add_constraint(edge[0], edge[1]);
    }
    cdt.add_constraint(*ring_handles.last().unwrap(), ring_handles[0]);

    Ok(())
}

#[pyfunction(signature = (outline, holes, min_area = None, max_area = None))]
pub(crate) fn triangulate_with_holes(
    outline: PolyLine2D,
    holes: Vec<PolyLine2D>,
    min_area: Option<f64>,
    max_area: Option<f64>,
) -> PyResult<Triangulation2D> {
    let outline_ring = close_ring(&outline.nodes);
    if outline_ring.len() < 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "outline needs at least 3 distinct points",
        ));
    }

    let mut hole_rings = Vec::with_capacity(holes.len());
    for hole in holes {
        let ring = close_ring(&hole.nodes);
        if ring.len() < 4 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "each hole needs at least 3 distinct points",
            ));
        }
        hole_rings.push(ring);
    }

    let mut cdt: ConstrainedDelaunayTriangulation<Point2<f64>> = ConstrainedDelaunayTriangulation::new();
    let mut handle_by_point: HashMap<(u64, u64), spade::handles::FixedVertexHandle> = HashMap::new();

    add_ring_constraints(&outline_ring, &mut cdt, &mut handle_by_point)?;
    for hole in &hole_rings {
        add_ring_constraints(hole, &mut cdt, &mut handle_by_point)?;
    }

    if let Some(value) = min_area {
        if value <= 0.0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "min_area must be > 0",
            ));
        }
    }

    if let Some(value) = max_area {
        if value <= 0.0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "max_area must be > 0",
            ));
        }
    }

    if let (Some(min_area), Some(max_area)) = (min_area, max_area) {
        if min_area > max_area {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "min_area must be <= max_area",
            ));
        }
    }

    if max_area.is_some() {
        let mut refinement = RefinementParameters::<f64>::new()
            .exclude_outer_faces(true)
            .keep_constraint_edges();

        if let Some(min_area) = min_area {
            refinement = refinement.with_min_required_area(min_area);
        }
        if let Some(max_area) = max_area {
            refinement = refinement.with_max_allowed_area(max_area);
        }

        let result = cdt.refine(refinement);
        if !result.refinement_complete {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "spade refinement did not complete; consider relaxing area limits",
            ));
        }
    }

    let mut node_index_by_handle = HashMap::new();
    let mut nodes = Vec::with_capacity(cdt.num_vertices());
    for (index, vertex) in cdt.vertices().enumerate() {
        let handle = vertex.fix();
        let pos = vertex.position();
        node_index_by_handle.insert(handle, index);
        nodes.push(Vector2D { x: pos.x, y: pos.y });
    }

    let mut triangles = Vec::new();
    for face in cdt.inner_faces() {
        let verts = face.vertices();
        let p0 = verts[0].position();
        let p1 = verts[1].position();
        let p2 = verts[2].position();
        let center = Vector2D {
            x: (p0.x + p1.x + p2.x) / 3.0,
            y: (p0.y + p1.y + p2.y) / 3.0,
        };

        if let Some(min_area) = min_area {
            if triangle_area_2d(p0, p1, p2) < min_area {
                continue;
            }
        }

        if !classify_triangle(center, &outline_ring, &hole_rings) {
            continue;
        }

        let i0 = *node_index_by_handle.get(&verts[0].fix()).unwrap();
        let i1 = *node_index_by_handle.get(&verts[1].fix()).unwrap();
        let i2 = *node_index_by_handle.get(&verts[2].fix()).unwrap();
        triangles.push((i0, i1, i2));
    }

    if ring_area(&outline_ring) < 0.0 {
        triangles.iter_mut().for_each(|(a, b, _)| std::mem::swap(a, b));
    }

    Ok(Triangulation2D { nodes, triangles })
}

#[pyfunction]
pub(crate) fn duplicate_representatives(points: Vec<Vector3D>, max_distance: f64) -> Vec<usize> {
    duplicate_representatives_impl(&points, max_distance)
}

#[pyfunction]
pub(crate) fn find_duplicates(points: Vec<Vector3D>, max_distance: f64) -> Vec<(usize, usize)> {
    duplicate_representatives_impl(&points, max_distance)
        .iter()
        .enumerate()
        .filter_map(|(index, representative)| {
            if *representative == index {
                None
            } else {
                Some((*representative, index))
            }
        })
        .collect()
}

#[pymodule(submodule, name = "mesh")]
pub(crate) mod mesh_mod {
    #[pymodule_export]
    use super::duplicate_representatives;
    #[pymodule_export]
    use super::find_duplicates;
    #[pymodule_export]
    use super::Line;
    #[pymodule_export]
    use super::Mesh;
    #[pymodule_export]
    use super::MeshObject;
    #[pymodule_export]
    use super::Quad;
    #[pymodule_export]
    use super::Triangle;
    #[pymodule_export]
    use super::triangulate_with_holes;
    #[pymodule_export]
    use super::Triangulation2D;
}
