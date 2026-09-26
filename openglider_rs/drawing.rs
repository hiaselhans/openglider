use dxf::entities::{Entity, EntityType, LwPolyline as DxfLwPolylineEntity, ModelPoint as DxfPointEntity, Text as DxfTextEntity};
use dxf::enums::{AcadVersion, HorizontalTextJustification, VerticalTextJustification};
use dxf::tables::Layer as DxfLayer;
use dxf::Color;
use dxf::{Drawing as DxfDrawing, LwPolylineVertex, Point, Vector};
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use svg::node::element::{Circle, Group, Polyline, Text as SvgText};
use svg::Document;

use crate::vector::signature::*;
use crate::vector::{PolyLine2D, Vector2D};

fn normalize_class_name(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' { ch } else { '_' })
        .collect()
}

fn svg_point(point: Vector2D) -> Vector2D {
    Vector2D { x: point.x, y: -point.y }
}

fn translate_point(point: Vector2D, offset: Vector2D) -> Vector2D {
    Vector2D { x: point.x + offset.x, y: point.y + offset.y }
}

fn scale_point(point: Vector2D, factor: f64) -> Vector2D {
    Vector2D { x: point.x * factor, y: point.y * factor }
}

fn rotate_point(point: Vector2D, angle: f64, center: Vector2D) -> Vector2D {
    let (sin_angle, cos_angle) = angle.sin_cos();
    let dx = point.x - center.x;
    let dy = point.y - center.y;
    Vector2D {
        x: center.x + dx * cos_angle - dy * sin_angle,
        y: center.y + dx * sin_angle + dy * cos_angle,
    }
}

fn polyline_bbox(polyline: &PolyLine2D) -> Option<(f64, f64, f64, f64)> {
    let mut min_x = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_y = f64::NEG_INFINITY;

    for node in &polyline.nodes {
        min_x = min_x.min(node.x);
        max_x = max_x.max(node.x);
        min_y = min_y.min(node.y);
        max_y = max_y.max(node.y);
    }

    if min_x.is_finite() && min_y.is_finite() && max_x.is_finite() && max_y.is_finite() {
        Some((min_x, max_x, min_y, max_y))
    } else {
        None
    }
}

fn merge_bbox(current: &mut Option<(f64, f64, f64, f64)>, other: Option<(f64, f64, f64, f64)>) {
    let Some((other_min_x, other_max_x, other_min_y, other_max_y)) = other else {
        return;
    };

    match current {
        Some((min_x, max_x, min_y, max_y)) => {
            *min_x = min_x.min(other_min_x);
            *max_x = max_x.max(other_max_x);
            *min_y = min_y.min(other_min_y);
            *max_y = max_y.max(other_max_y);
        }
        None => *current = Some((other_min_x, other_max_x, other_min_y, other_max_y)),
    }
}

fn vector2d_to_point(point: Vector2D) -> Point {
    Point::new(point.x, point.y, 0.0)
}

fn svg_points(points: &[Vector2D]) -> String {
    points
        .iter()
        .map(|point| format!("{},{}", point.x, -point.y))
        .collect::<Vec<_>>()
        .join(" ")
}

fn normalize_text_align(align: f64) -> f64 {
    if align.is_finite() {
        align.clamp(-1.0, 1.0)
    } else {
        -1.0
    }
}

fn svg_text_anchor(align: f64) -> &'static str {
    let align = normalize_text_align(align);
    if align >= 0.33 {
        "end"
    } else if align <= -0.33 {
        "start"
    } else {
        "middle"
    }
}

fn dxf_horizontal_justification(align: f64) -> HorizontalTextJustification {
    let align = normalize_text_align(align);
    if align >= 0.33 {
        HorizontalTextJustification::Right
    } else if align <= -0.33 {
        HorizontalTextJustification::Left
    } else {
        HorizontalTextJustification::Center
    }
}

fn text_anchor_name(align: f64, valign: f64) -> String {
    let horizontal = if align >= 0.33 {
        "right"
    } else if align <= -0.33 {
        "left"
    } else {
        "center"
    };

    if valign >= 0.75 {
        return format!("top-{}", horizontal);
    }
    if valign <= 0.25 {
        return format!("bottom-{}", horizontal);
    }

    horizontal.to_string()
}

fn dxf_vertical_justification(valign: f64) -> VerticalTextJustification {
    if valign >= 0.75 {
        VerticalTextJustification::Top
    } else if valign <= 0.25 {
        VerticalTextJustification::Bottom
    } else {
        VerticalTextJustification::Middle
    }
}

fn dxf_text_anchor(text: &Text) -> Point {
    let direction = text.direction();
    let normal = text.normal();
    let text_width = text.font_size() * text.text.chars().count() as f64;
    let align = normalize_text_align(text.align);
    let base_factor = (align + 1.0) * 0.5;
    let base = translate_point(
        text.p1,
        scale_point(Vector2D { x: text.p2.x - text.p1.x, y: text.p2.y - text.p1.y }, base_factor),
    );

    let horizontal_offset = -base_factor * text_width;
    let vertical_offset = text.letter_height() * (text.valign - 0.5);
    let anchor = translate_point(
        translate_point(base, scale_point(direction, horizontal_offset)),
        scale_point(normal, vertical_offset),
    );
    vector2d_to_point(anchor)
}

fn parse_hex_rgb(value: &str) -> Option<(u8, u8, u8)> {
    let text = value.trim();
    let hex = text.strip_prefix('#')?;
    if hex.len() != 6 {
        return None;
    }

    let r = u8::from_str_radix(&hex[0..2], 16).ok()?;
    let g = u8::from_str_radix(&hex[2..4], 16).ok()?;
    let b = u8::from_str_radix(&hex[4..6], 16).ok()?;
    Some((r, g, b))
}

fn aci_from_rgb(r: u8, g: u8, b: u8) -> u8 {
    // Approximate CSS RGB to a reasonable AutoCAD Color Index.
    if r < 32 && g < 32 && b < 32 {
        return 7;
    }
    if r > 223 && g > 223 && b > 223 {
        return 7;
    }

    let max_channel = r.max(g).max(b);
    let min_channel = r.min(g).min(b);
    let chroma = max_channel - min_channel;

    if chroma < 24 {
        return 8;
    }

    if r >= g && r >= b {
        if g > 160 && b < 96 {
            30
        } else if b > 160 && g < 96 {
            210
        } else {
            1
        }
    } else if g >= r && g >= b {
        if r > 160 && b < 96 {
            50
        } else if b > 160 && r < 96 {
            130
        } else {
            3
        }
    } else if r > 160 && g > 160 {
        170
    } else {
        5
    }
}

fn stroke_to_rgb(stroke: &Option<String>) -> Option<(u8, u8, u8)> {
    let stroke = stroke.as_ref()?;
    let value = stroke.trim().to_ascii_lowercase();
    match value.as_str() {
        "black" => Some((0, 0, 0)),
        "white" => Some((255, 255, 255)),
        "gray" | "grey" => Some((128, 128, 128)),
        "red" => Some((255, 0, 0)),
        "yellow" => Some((255, 255, 0)),
        "green" => Some((0, 255, 0)),
        "cyan" => Some((0, 255, 255)),
        "blue" => Some((0, 0, 255)),
        "magenta" => Some((255, 0, 255)),
        _ => parse_hex_rgb(&value),
    }
}

fn stroke_to_aci(stroke: &Option<String>) -> u8 {
    stroke_to_rgb(stroke)
        .map(|(r, g, b)| aci_from_rgb(r, g, b))
        .unwrap_or(7)
}

fn stroke_width_to_lineweight(stroke_width: f64) -> i16 {
    // DXF stores lineweight in 1/100 mm and expects values in the 0..211 range.
    let width = if stroke_width.is_finite() { stroke_width } else { 0.25 };
    let raw = (width * 100.0).round() as i16;
    raw.clamp(0, 211)
}

fn dxf_truecolor(stroke: &Option<String>) -> i32 {
    if let Some((r, g, b)) = stroke_to_rgb(stroke) {
        ((r as i32) << 16) | ((g as i32) << 8) | (b as i32)
    } else {
        0
    }
}

fn polyline_to_lwpolyline(line: &PolyLine2D) -> Option<DxfLwPolylineEntity> {
    if line.nodes.len() < 2 {
        return None;
    }

    let mut polyline = DxfLwPolylineEntity::default();
    let mut end = line.nodes.len();
    let is_closed = line.nodes.len() > 2
        && line.nodes.first().map(|point| point.x) == line.nodes.last().map(|point| point.x)
        && line.nodes.first().map(|point| point.y) == line.nodes.last().map(|point| point.y);

    // Closed polylines should not duplicate start/end vertices; closure is encoded via flags.
    if is_closed {
        end -= 1;
        polyline.set_is_closed(true);
    }

    polyline.vertices = line.nodes[..end]
        .iter()
        .map(|point| LwPolylineVertex {
            x: point.x,
            y: point.y,
            id: 0,
            starting_width: 0.0,
            ending_width: 0.0,
            bulge: 0.0,
        })
        .collect();

    Some(polyline)
}

fn dxf_line_entities(line: &PolyLine2D, layer_name: &str, layer_style: &LayerStyle) -> Vec<Entity> {
    if line.nodes.is_empty() {
        return Vec::new();
    }

    let aci = stroke_to_aci(&layer_style.stroke);
    let lineweight = stroke_width_to_lineweight(layer_style.stroke_width);
    let truecolor = dxf_truecolor(&layer_style.stroke);

    if line.nodes.len() == 1 {
        let mut entity = Entity::new(EntityType::ModelPoint(DxfPointEntity {
            location: vector2d_to_point(line.nodes[0]),
            ..DxfPointEntity::default()
        }));
        entity.common.layer = layer_name.to_string();
        entity.common.color = Color::from_index(aci);
        entity.common.lineweight_enum_value = lineweight;
        entity.common.color_24_bit = truecolor;
        return vec![entity];
    }

    let polyline = match polyline_to_lwpolyline(line) {
        Some(polyline) => polyline,
        None => return Vec::new(),
    };

    let mut entity = Entity::new(EntityType::LwPolyline(polyline));
    entity.common.layer = layer_name.to_string();
    entity.common.color = Color::from_index(aci);
    entity.common.lineweight_enum_value = lineweight;
    entity.common.color_24_bit = truecolor;
    return vec![entity];
}

fn dxf_text_entity(text: &Text, layer_name: &str, layer_style: &LayerStyle) -> Entity {
    let anchor = dxf_text_anchor(text);
    let aci = stroke_to_aci(&layer_style.stroke);
    let lineweight = stroke_width_to_lineweight(layer_style.stroke_width);
    let truecolor = dxf_truecolor(&layer_style.stroke);
    let mut entity = Entity::new(EntityType::Text(DxfTextEntity {
        value: text.text.clone(),
        location: anchor.clone(),
        text_height: layer_style.font_size.unwrap_or_else(|| text.letter_height()),
        rotation: (text.p2.y - text.p1.y).atan2(text.p2.x - text.p1.x).to_degrees(),
        relative_x_scale_factor: 1.0,
        oblique_angle: 0.0,
        text_style_name: layer_style.font_family.clone().unwrap_or_else(|| "STANDARD".to_string()),
        text_generation_flags: 0,
        horizontal_text_justification: dxf_horizontal_justification(text.align),
        second_alignment_point: anchor,
        normal: Vector::z_axis(),
        vertical_text_justification: dxf_vertical_justification(text.valign),
        thickness: 0.0,
        ..DxfTextEntity::default()
    }));
    entity.common.layer = layer_name.to_string();
    entity.common.color = Color::from_index(aci);
    entity.common.lineweight_enum_value = lineweight;
    entity.common.color_24_bit = truecolor;
    entity
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct LayerStyle {
    #[pyo3(get, set)]
    pub stroke: Option<String>,
    #[pyo3(get, set)]
    pub stroke_width: f64,
    #[pyo3(get, set)]
    pub fill: Option<String>,
    #[pyo3(get, set)]
    pub font_size: Option<f64>,
    #[pyo3(get, set)]
    pub font_family: Option<String>,
    #[pyo3(get, set)]
    pub visible: bool,
}

impl Default for LayerStyle {
    fn default() -> Self {
        Self {
            stroke: Some("black".to_string()),
            stroke_width: 0.25,
            fill: None,
            font_size: None,
            font_family: None,
            visible: true,
        }
    }
}

#[pymethods]
impl LayerStyle {
    fn scaled(&self, factor: f64) -> Self {
        Self {
            stroke: self.stroke.clone(),
            stroke_width: self.stroke_width,
            fill: self.fill.clone(),
            font_size: self.font_size.map(|font_size| if factor.abs() > 0.0 { font_size / factor } else { font_size }),
            font_family: self.font_family.clone(),
            visible: self.visible,
        }
    }

    #[new]
    #[pyo3(signature = (stroke = None, stroke_width = 0.25, fill = None, font_size = None, font_family = None, visible = true))]
    fn new(
        stroke: Option<String>,
        stroke_width: f64,
        fill: Option<String>,
        font_size: Option<f64>,
        font_family: Option<String>,
        visible: bool,
    ) -> Self {
        Self { stroke, stroke_width, fill, font_size, font_family, visible }
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
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Text {
    #[pyo3(get, set)]
    pub text: String,
    #[pyo3(get, set)]
    pub p1: Vector2D,
    #[pyo3(get, set)]
    pub p2: Vector2D,
    #[pyo3(get, set)]
    pub size: Option<f64>,
    #[pyo3(get, set)]
    pub height: f64,
    #[pyo3(get, set)]
    pub space: f64,
    #[pyo3(get, set)]
    pub align: f64,
    #[pyo3(get, set)]
    pub valign: f64,
}

impl Text {
    fn letter_width(&self) -> f64 {
        if let Some(size) = self.size {
            return size;
        }

        let char_count = self.text.chars().count().max(1) as f64;
        let diff = Vector2D {
            x: self.p2.x - self.p1.x,
            y: self.p2.y - self.p1.y,
        };
        let length = (diff.x * diff.x + diff.y * diff.y).sqrt();
        if length > 0.0 {
            length / char_count
        } else {
            1.0
        }
    }

    fn font_size(&self) -> f64 {
        self.letter_width()
    }

    fn letter_height(&self) -> f64 {
        self.height * self.letter_width()
    }

    fn direction(&self) -> Vector2D {
        let diff = Vector2D {
            x: self.p2.x - self.p1.x,
            y: self.p2.y - self.p1.y,
        };
        let length = (diff.x * diff.x + diff.y * diff.y).sqrt();
        if length > 0.0 {
            Vector2D { x: diff.x / length, y: diff.y / length }
        } else {
            Vector2D { x: 1.0, y: 0.0 }
        }
    }

    fn normal(&self) -> Vector2D {
        let direction = self.direction();
        Vector2D { x: -direction.y, y: direction.x }
    }

    fn anchor_point(&self) -> Vector2D {
        let direction = self.direction();
        let normal = self.normal();
        let text_width = self.font_size() * self.text.chars().count() as f64;
        let align = normalize_text_align(self.align);
        let base_factor = (align + 1.0) * 0.5;
        let base = translate_point(
            self.p1,
            scale_point(Vector2D { x: self.p2.x - self.p1.x, y: self.p2.y - self.p1.y }, base_factor),
        );

        let horizontal_offset = -base_factor * text_width;

        let vertical_offset = self.letter_height() * (self.valign - 0.5);
        translate_point(
            translate_point(base, scale_point(direction, horizontal_offset)),
            scale_point(normal, vertical_offset),
        )
    }

    fn bbox_impl(&self) -> Option<(f64, f64, f64, f64)> {
        if self.text.is_empty() {
            return Some((self.p1.x, self.p1.x, self.p1.y, self.p1.y));
        }

        let direction = self.direction();
        let normal = self.normal();
        let text_width = self.font_size() * self.text.chars().count() as f64;
        let letter_height = self.letter_height();
        let anchor = self.anchor_point();

        // Keep bbox semantics aligned with anchor + valign behavior used by SVG/DXF output.
        let (normal_min, normal_max) = if self.valign >= 0.75 {
            (-letter_height, 0.0)
        } else if self.valign <= 0.25 {
            (0.0, letter_height)
        } else {
            (-0.5 * letter_height, 0.5 * letter_height)
        };

        let lower = translate_point(anchor, scale_point(normal, normal_min));
        let upper = translate_point(anchor, scale_point(normal, normal_max));
        let lower_end = translate_point(lower, scale_point(direction, text_width));
        let upper_end = translate_point(upper, scale_point(direction, text_width));

        Some((
            lower.x.min(upper.x).min(lower_end.x).min(upper_end.x),
            lower.x.max(upper.x).max(lower_end.x).max(upper_end.x),
            lower.y.min(upper.y).min(lower_end.y).min(upper_end.y),
            lower.y.max(upper.y).max(lower_end.y).max(upper_end.y),
        ))
    }

    fn svg_element(&self, layer_style: &LayerStyle, layer_name: &str, material_code: &str) -> SvgText {
        let svg_anchor = svg_point(self.anchor_point());
        let angle = (self.p2.y - self.p1.y).atan2(self.p2.x - self.p1.x).to_degrees();
        let font_size = layer_style.font_size.unwrap_or_else(|| self.font_size());
        let mut element = SvgText::new(self.text.clone())
            .set("x", svg_anchor.x)
            .set("y", svg_anchor.y)
            .set("font-size", font_size)
            .set("text-anchor", svg_text_anchor(self.align))
            .set(
                "dominant-baseline",
                match self.valign {
                    v if v >= 0.75 => "text-before-edge",
                    v if v <= 0.25 => "text-after-edge",
                    _ => "middle",
                },
            )
            .set(
                "transform",
                format!("rotate({} {} {})", angle, svg_anchor.x, svg_anchor.y),
            )
            .set("class", layer_classes(layer_name, material_code));

        if let Some(font_family) = &layer_style.font_family {
            element = element.set("font-family", font_family.as_str());
        }

        let fill = layer_style
            .fill
            .as_deref()
            .or(layer_style.stroke.as_deref())
            .unwrap_or("black");
        element.set("fill", fill)
    }

    fn dxf_entity(&self, layer_name: &str, layer_style: &LayerStyle) -> Entity {
        dxf_text_entity(self, layer_name, layer_style)
    }

    fn transformed(&self, transform: impl Fn(Vector2D) -> Vector2D) -> Self {
        Self {
            text: self.text.clone(),
            p1: transform(self.p1),
            p2: transform(self.p2),
            size: self.size,
            height: self.height,
            space: self.space,
            align: self.align,
            valign: self.valign,
        }
    }

    fn scaled(&self, factor: f64) -> Self {
        Self {
            text: self.text.clone(),
            p1: scale_point(self.p1, factor),
            p2: scale_point(self.p2, factor),
            size: self.size.map(|size| size * factor),
            height: self.height,
            space: self.space,
            align: self.align,
            valign: self.valign,
        }
    }
}

#[pymethods]
impl Text {
    #[new]
    #[pyo3(signature = (text, p1, p2, size = None, height = 0.8, space = 0.2, align = -1.0, valign = 0.5))]
    fn new(
        text: String,
        p1: Vector2DInput,
        p2: Vector2DInput,
        size: Option<f64>,
        height: f64,
        space: f64,
        align: f64,
        valign: f64,
    ) -> PyResult<Self> {
        Ok(Self {
            text,
            p1: p1.into_vector()?,
            p2: p2.into_vector()?,
            size,
            height,
            space,
            align: normalize_text_align(align),
            valign: if valign.is_finite() { valign } else { 0.5 },
        })
    }

    #[pyo3(signature = (align, valign = None))]
    fn set_alignment(&mut self, align: f64, valign: Option<f64>) {
        self.align = normalize_text_align(align);
        if let Some(valign) = valign {
            self.valign = if valign.is_finite() { valign } else { self.valign };
        }
    }

    fn get_anchor(&self) -> String {
        text_anchor_name(self.align, self.valign)
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

    fn bbox(&self) -> Option<(f64, f64, f64, f64)> {
        self.bbox_impl()
    }

    #[pyo3(name = "move")]
    fn r#move(&self, offset: Vector2DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(self.transformed(|point| translate_point(point, offset)))
    }

    fn rotate(&self, angle: f64, radians: bool, center: Option<Vector2DInput>) -> PyResult<Self> {
        let angle = if radians { angle } else { angle.to_radians() };
        let center = match center {
            Some(center) => center.into_vector()?,
            None => Vector2D { x: 0.0, y: 0.0 },
        };
        Ok(self.transformed(|point| rotate_point(point, angle, center)))
    }

    fn scale(&self, factor: f64) -> Self {
        self.scaled(factor)
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Layer {
    #[pyo3(get, set)]
    pub lines: Vec<PolyLine2D>,
    #[pyo3(get, set)]
    pub texts: Vec<Text>,
    #[pyo3(get, set)]
    pub style: LayerStyle,
}

impl Default for Layer {
    fn default() -> Self {
        Self {
            lines: Vec::new(),
            texts: Vec::new(),
            style: LayerStyle::default(),
        }
    }
}

impl Layer {
    fn bbox_impl(&self) -> Option<(f64, f64, f64, f64)> {
        let mut bbox = None;
        for line in &self.lines {
            merge_bbox(&mut bbox, polyline_bbox(line));
        }
        for text in &self.texts {
            merge_bbox(&mut bbox, text.bbox_impl());
        }
        bbox
    }

    fn transformed(&self, transform: impl Fn(Vector2D) -> Vector2D + Copy) -> Self {
        Self {
            lines: self
                .lines
                .iter()
                .map(|line| PolyLine2D { nodes: line.nodes.iter().copied().map(transform).collect() })
                .collect(),
            texts: self.texts.iter().map(|text| text.transformed(transform)).collect(),
            style: self.style.clone(),
        }
    }

    fn scaled(&self, factor: f64) -> Self {
        Self {
            lines: self
                .lines
                .iter()
                .map(|line| PolyLine2D { nodes: line.nodes.iter().map(|point| scale_point(*point, factor)).collect() })
                .collect(),
            texts: self.texts.iter().map(|text| text.scaled(factor)).collect(),
            style: self.style.scaled(factor),
        }
    }

    fn to_svg_group(&self, layer_name: &str, material_code: &str) -> Option<Group> {
        if !self.style.visible {
            return None;
        }

        let mut group = Group::new().set("class", layer_classes(layer_name, material_code));

        for line in &self.lines {
            let stroke = self.style.stroke.as_deref().unwrap_or("black");
            let fill = self.style.fill.as_deref().unwrap_or("none");
            if line.nodes.len() == 1 {
                let radius = (self.style.stroke_width * 0.5).max(0.25);
                let point = Circle::new()
                    .set("cx", line.nodes[0].x)
                    .set("cy", -line.nodes[0].y)
                    .set("r", radius)
                    .set("stroke", stroke)
                    .set("stroke-width", self.style.stroke_width)
                    .set("fill", stroke)
                    .set("class", layer_classes(layer_name, material_code));
                group = group.add(point);
            } else {
                let polyline = Polyline::new()
                    .set("points", svg_points(&line.nodes))
                    .set("stroke", stroke)
                    .set("stroke-width", self.style.stroke_width)
                    .set("fill", fill)
                    .set("vector-effect", "non-scaling-stroke")
                    .set("class", layer_classes(layer_name, material_code));
                group = group.add(polyline);
            }
        }

        for text in &self.texts {
            group = group.add(text.svg_element(&self.style, layer_name, material_code));
        }

        Some(group)
    }

    fn to_preview_layout(&self) -> Layout {
        let mut layers = BTreeMap::new();
        layers.insert("layer".to_string(), self.clone());
        Layout {
            parts: vec![Part {
                layers,
                name: Some("layer".to_string()),
                material_code: String::new(),
            }],
        }
    }
}

#[pymethods]
impl Layer {
    #[new]
    #[pyo3(signature = (lines = None, texts = None, style = None))]
    fn new(lines: Option<Vec<PolyLine2D>>, texts: Option<Vec<Text>>, style: Option<LayerStyle>) -> Self {
        Self {
            lines: lines.unwrap_or_default(),
            texts: texts.unwrap_or_default(),
            style: style.unwrap_or_default(),
        }
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

    fn add_line(&mut self, line: PolyLine2D) {
        self.lines.push(line);
    }

    fn add_text(&mut self, text: Text) {
        self.texts.push(text);
    }

    fn add_entity(&mut self, entity: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Ok(line) = entity.extract::<PolyLine2D>() {
            self.lines.push(line);
            return Ok(());
        }
        if let Ok(text) = entity.extract::<Text>() {
            self.texts.push(text);
            return Ok(());
        }

        Err(PyValueError::new_err(
            "unsupported entity type; expected PolyLine2D or Text",
        ))
    }

    fn bbox(&self) -> Option<(f64, f64, f64, f64)> {
        self.bbox_impl()
    }

    #[pyo3(name = "move")]
    fn r#move(&self, offset: Vector2DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(self.transformed(|point| translate_point(point, offset)))
    }

    fn rotate(&self, angle: f64, radians: bool, center: Option<Vector2DInput>) -> PyResult<Self> {
        let angle = if radians { angle } else { angle.to_radians() };
        let center = match center {
            Some(center) => center.into_vector()?,
            None => Vector2D { x: 0.0, y: 0.0 },
        };
        Ok(self.transformed(|point| rotate_point(point, angle, center)))
    }

    fn scale(&self, factor: f64) -> Self {
        self.scaled(factor)
    }

    fn __repr_svg_(&self) -> String {
        self.to_preview_layout().to_svg_document_with_size(800, 0.0).to_string()
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Part {
    #[pyo3(get, set)]
    pub layers: BTreeMap<String, Layer>,
    #[pyo3(get, set)]
    pub name: Option<String>,
    #[pyo3(get, set)]
    pub material_code: String,
}

impl Default for Part {
    fn default() -> Self {
        Self {
            layers: BTreeMap::new(),
            name: None,
            material_code: String::new(),
        }
    }
}

impl Part {
    fn layer_mut_or_insert(&mut self, layer_name: &str) -> &mut Layer {
        let layer = self.layers.entry(layer_name.to_string()).or_default();
        if layer.style.stroke.is_none() {
            layer.style.stroke = Some("black".to_string());
        }
        layer
    }

    fn bbox_impl(&self) -> Option<(f64, f64, f64, f64)> {
        let mut bbox = None;
        for layer in self.layers.values() {
            merge_bbox(&mut bbox, layer.bbox());
        }
        bbox
    }

    fn transformed(&self, transform: impl Fn(Vector2D) -> Vector2D + Copy) -> Self {
        let layers = self
            .layers
            .iter()
            .map(|(name, layer)| (name.clone(), layer.transformed(transform)))
            .collect();

        Self { layers, name: self.name.clone(), material_code: self.material_code.clone() }
    }

    fn scaled(&self, factor: f64) -> Self {
        let layers = self
            .layers
            .iter()
            .map(|(name, layer)| (name.clone(), layer.scaled(factor)))
            .collect();

        Self { layers, name: self.name.clone(), material_code: self.material_code.clone() }
    }

    fn to_svg_group(&self) -> Group {
        let part_class = self.name.as_deref().unwrap_or("part");
        let mut group = Group::new().set("class", layer_classes(part_class, &self.material_code));
        if let Some(name) = &self.name {
            group = group.set("id", name.as_str());
        }
        for (layer_name, layer) in &self.layers {
            if let Some(child_group) = layer.to_svg_group(layer_name, &self.material_code) {
                group = group.add(child_group);
            }
        }
        group
    }

    fn to_preview_layout(&self) -> Layout {
        Layout { parts: vec![self.clone()] }
    }
}

#[pymethods]
impl Part {
    #[new]
    #[pyo3(signature = (layers = None, name = None, material_code = "".to_string()))]
    fn new(
        layers: Option<BTreeMap<String, Layer>>,
        name: Option<String>,
        material_code: String,
    ) -> Self {
        Self {
            layers: layers.unwrap_or_default(),
            name,
            material_code,
        }
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

    #[pyo3(signature = (layer_name, style = None))]
    fn layer(
        slf: Py<Self>,
        py: Python<'_>,
        layer_name: String,
        style: Option<LayerStyle>,
    ) -> LayerEditor {
        {
            let mut part = slf.borrow_mut(py);
            let layer = part.layer_mut_or_insert(&layer_name);
            if let Some(style) = style {
                layer.style = style;
            }
        }

        LayerEditor { part: slf, layer_name }
    }

    fn add_entity(&mut self, layer_name: String, entity: &Bound<'_, PyAny>) -> PyResult<()> {
        self.layer_mut_or_insert(&layer_name).add_entity(entity)
    }

    fn add_line(&mut self, layer_name: String, line: PolyLine2D) {
        self.layer_mut_or_insert(&layer_name).lines.push(line);
    }

    fn add_text(&mut self, layer_name: String, text: Text) {
        self.layer_mut_or_insert(&layer_name).texts.push(text);
    }

    fn bbox(&self) -> Option<(f64, f64, f64, f64)> {
        self.bbox_impl()
    }

    #[pyo3(name = "move")]
    fn r#move(&self, offset: Vector2DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(self.transformed(|point| translate_point(point, offset)))
    }

    fn rotate(&self, angle: f64, radians: bool, center: Option<Vector2DInput>) -> PyResult<Self> {
        let angle = if radians { angle } else { angle.to_radians() };
        let center = match center {
            Some(center) => center.into_vector()?,
            None => Vector2D { x: 0.0, y: 0.0 },
        };
        Ok(self.transformed(|point| rotate_point(point, angle, center)))
    }

    fn scale(&self, factor: f64) -> Self {
        self.scaled(factor)
    }

    fn __repr_svg_(&self) -> String {
        self.to_preview_layout().to_svg_document_with_size(800, 0.0).to_string()
    }
}

#[pyclass]
pub struct LayerEditor {
    part: Py<Part>,
    layer_name: String,
}

#[pyclass]
pub struct LayerStyleEditor {
    part: Py<Part>,
    layer_name: String,
}

impl LayerStyleEditor {
    fn get_style_value<R>(&self, py: Python<'_>, f: impl FnOnce(&LayerStyle) -> R) -> R {
        let part = self.part.borrow(py);
        let style = part
            .layers
            .get(&self.layer_name)
            .map(|layer| layer.style.clone())
            .unwrap_or_default();
        f(&style)
    }

    fn set_style_value(&self, py: Python<'_>, mutator: impl FnOnce(&mut LayerStyle)) {
        let mut part = self.part.borrow_mut(py);
        let layer = part.layer_mut_or_insert(&self.layer_name);
        mutator(&mut layer.style);
    }
}

#[pymethods]
impl LayerStyleEditor {
    #[getter]
    fn stroke(&self, py: Python<'_>) -> Option<String> {
        self.get_style_value(py, |style| style.stroke.clone())
    }

    #[setter]
    fn set_stroke(&self, py: Python<'_>, stroke: Option<String>) {
        self.set_style_value(py, |style| style.stroke = stroke);
    }

    #[getter]
    fn stroke_width(&self, py: Python<'_>) -> f64 {
        self.get_style_value(py, |style| style.stroke_width)
    }

    #[setter]
    fn set_stroke_width(&self, py: Python<'_>, stroke_width: f64) {
        self.set_style_value(py, |style| style.stroke_width = stroke_width);
    }

    #[getter]
    fn fill(&self, py: Python<'_>) -> Option<String> {
        self.get_style_value(py, |style| style.fill.clone())
    }

    #[setter]
    fn set_fill(&self, py: Python<'_>, fill: Option<String>) {
        self.set_style_value(py, |style| style.fill = fill);
    }

    #[getter]
    fn font_size(&self, py: Python<'_>) -> Option<f64> {
        self.get_style_value(py, |style| style.font_size)
    }

    #[setter]
    fn set_font_size(&self, py: Python<'_>, font_size: Option<f64>) {
        self.set_style_value(py, |style| style.font_size = font_size);
    }

    #[getter]
    fn font_family(&self, py: Python<'_>) -> Option<String> {
        self.get_style_value(py, |style| style.font_family.clone())
    }

    #[setter]
    fn set_font_family(&self, py: Python<'_>, font_family: Option<String>) {
        self.set_style_value(py, |style| style.font_family = font_family);
    }

    #[getter]
    fn visible(&self, py: Python<'_>) -> bool {
        self.get_style_value(py, |style| style.visible)
    }

    #[setter]
    fn set_visible(&self, py: Python<'_>, visible: bool) {
        self.set_style_value(py, |style| style.visible = visible);
    }
}

#[pymethods]
impl LayerEditor {
    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<'_, PyAny>>,
        _exc: Option<&Bound<'_, PyAny>>,
        _tb: Option<&Bound<'_, PyAny>>,
    ) -> bool {
        false
    }

    fn add_line(&self, py: Python<'_>, line: PolyLine2D) {
        let mut part = self.part.borrow_mut(py);
        part.layer_mut_or_insert(&self.layer_name).lines.push(line);
    }

    fn add_text(&self, py: Python<'_>, text: Text) {
        let mut part = self.part.borrow_mut(py);
        part.layer_mut_or_insert(&self.layer_name).texts.push(text);
    }

    fn add(&self, py: Python<'_>, entity: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut part = self.part.borrow_mut(py);
        part.layer_mut_or_insert(&self.layer_name).add_entity(entity)
    }

    #[getter]
    fn style(&self, py: Python<'_>) -> LayerStyleEditor {
        LayerStyleEditor {
            part: self.part.clone_ref(py),
            layer_name: self.layer_name.clone(),
        }
    }

    #[setter(style)]
    fn set_style_property(&self, py: Python<'_>, style: LayerStyle) {
        let mut part = self.part.borrow_mut(py);
        part.layer_mut_or_insert(&self.layer_name).style = style;
    }
}

#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct Layout {
    #[pyo3(get, set)]
    pub parts: Vec<Part>,
}

impl Default for Layout {
    fn default() -> Self {
        Self { parts: Vec::new() }
    }
}

impl Layout {
    fn bbox_impl(&self) -> Option<(f64, f64, f64, f64)> {
        let mut bbox = None;
        for part in &self.parts {
            merge_bbox(&mut bbox, part.bbox());
        }
        bbox
    }

    fn transformed(&self, transform: impl Fn(Vector2D) -> Vector2D + Copy) -> Self {
        Self {
            parts: self.parts.iter().map(|part| part.transformed(transform)).collect(),
        }
    }

    fn scaled(&self, factor: f64) -> Self {
        Self {
            parts: self.parts.iter().map(|part| part.scaled(factor)).collect(),
        }
    }

    fn svg_viewbox(&self, border: f64) -> (f64, f64, f64, f64) {
        let (min_x, max_x, min_y, max_y) = self.bbox_impl().unwrap_or((0.0, 1.0, 0.0, 1.0));
        let width = (max_x - min_x).max(1e-6);
        let height = (max_y - min_y).max(1e-6);
        (min_x - border, -(max_y + border), width + border * 2.0, height + border * 2.0)
    }

    fn to_svg_document(&self, border: f64) -> Document {
        let (view_x, view_y, view_w, view_h) = self.svg_viewbox(border);
        let mut document = Document::new()
            .set("xmlns", "http://www.w3.org/2000/svg")
            .set("version", "1.1")
            .set("viewBox", (view_x, view_y, view_w, view_h));
        for part in &self.parts {
            document = document.add(part.to_svg_group());
        }
        document
    }

    fn to_svg_document_with_size(&self, width_px: u32, border: f64) -> Document {
        let (min_x, max_x, min_y, max_y) = self.bbox_impl().unwrap_or((0.0, 1.0, 0.0, 1.0));
        let width = (max_x - min_x).max(1e-6) + border * 2.0;
        let height = (max_y - min_y).max(1e-6) + border * 2.0;
        let height_px = ((width_px as f64) * height / width).round().max(1.0) as u32;

        self.to_svg_document(border)
            .set("width", format!("{}px", width_px))
            .set("height", format!("{}px", height_px))
    }

    fn dxf_drawing(&self) -> DxfDrawing {
        let mut drawing = DxfDrawing::new();
        // LWPOLYLINE requires R14+; keep parity with legacy exporter (AC1015/R2000).
        drawing.header.version = AcadVersion::R2000;
        let mut added_layers = BTreeSet::new();

        for part in &self.parts {
            for (layer_name, layer) in &part.layers {
                if !layer.style.visible {
                    continue;
                }

                if added_layers.insert(layer_name.clone()) {
                    let mut dxf_layer = DxfLayer::default();
                    dxf_layer.name = layer_name.clone();
                    dxf_layer.color = Color::from_index(stroke_to_aci(&layer.style.stroke));
                    dxf_layer.normalize();
                    drawing.add_layer(dxf_layer);
                }

                for line in &layer.lines {
                    for entity in dxf_line_entities(line, layer_name, &layer.style) {
                        drawing.add_entity(entity);
                    }
                }

                for text in &layer.texts {
                    drawing.add_entity(text.dxf_entity(layer_name, &layer.style));
                }
            }
        }

        drawing
    }

    fn to_dxf_string(&self) -> PyResult<String> {
        let drawing = self.dxf_drawing();
        let mut buffer = Vec::new();
        drawing.save(&mut buffer).map_err(|error| PyIOError::new_err(format!("failed to build dxf: {}", error)))?;
        String::from_utf8(buffer).map_err(|error| PyIOError::new_err(format!("failed to encode dxf text: {}", error)))
    }

    fn stack_input_to_layouts(py: Python<'_>, parts: Vec<Py<PyAny>>) -> PyResult<Vec<Layout>> {
        let mut layouts = Vec::with_capacity(parts.len());

        for item in parts {
            let any = item.bind(py);

            if let Ok(layout) = any.extract::<Layout>() {
                layouts.push(layout);
                continue;
            }

            if let Ok(part) = any.extract::<Part>() {
                layouts.push(Layout { parts: vec![part] });
                continue;
            }

            return Err(PyValueError::new_err(
                "parts must contain Layout or Part instances",
            ));
        }

        Ok(layouts)
    }

    fn size_from_bbox(layout: &Layout) -> (f64, f64) {
        if let Some((min_x, max_x, min_y, max_y)) = layout.bbox_impl() {
            (max_x - min_x, max_y - min_y)
        } else {
            (0.0, 0.0)
        }
    }

    fn moved_to(layout: &Layout, x: f64, y: f64) -> Layout {
        if let Some((min_x, _, min_y, _)) = layout.bbox_impl() {
            let dx = x - min_x;
            let dy = y - min_y;
            layout.transformed(|point| Vector2D {
                x: point.x + dx,
                y: point.y + dy,
            })
        } else {
            layout.clone()
        }
    }

    fn move_to_xy(&mut self, x: f64, y: f64) {
        let moved = Layout::moved_to(self, x, y);
        self.parts = moved.parts;
    }
}

#[pymethods]
impl Layout {
    #[new]
    #[pyo3(signature = (parts = None))]
    fn new(parts: Option<Vec<Part>>) -> Self {
        Self { parts: parts.unwrap_or_default() }
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

    #[staticmethod]
    #[pyo3(signature = (parts, distance, center_x = true))]
    fn stack_column(py: Python<'_>, parts: Vec<Py<PyAny>>, distance: f64, center_x: bool) -> PyResult<Self> {
        let parts = Layout::stack_input_to_layouts(py, parts)?;
        let widths: Vec<f64> = parts.iter().map(|layout| Layout::size_from_bbox(layout).0).collect();
        let max_width = widths.iter().copied().fold(0.0, f64::max);
        let direction = if distance < 0.0 { -1.0 } else { 1.0 };

        let mut y = 0.0;
        let mut column = Layout::default();

        for (layout, width) in parts.iter().zip(widths.iter()) {
            let (_, height) = Layout::size_from_bbox(layout);
            let x = if center_x { (max_width - *width) / 2.0 } else { 0.0 };
            let moved = Layout::moved_to(layout, x, y);
            column.parts.extend(moved.parts);

            y += direction * height;
            y += distance;
        }

        Ok(column)
    }

    #[staticmethod]
    #[pyo3(signature = (parts, distance, center_y = true))]
    fn stack_row(py: Python<'_>, parts: Vec<Py<PyAny>>, distance: f64, center_y: bool) -> PyResult<Self> {
        let parts = Layout::stack_input_to_layouts(py, parts)?;
        let heights: Vec<f64> = parts.iter().map(|layout| Layout::size_from_bbox(layout).1).collect();
        let max_height = heights.iter().copied().fold(0.0, f64::max);
        let direction = if distance < 0.0 { -1.0 } else { 1.0 };

        let mut x = 0.0;
        let mut row = Layout::default();

        for (layout, height) in parts.iter().zip(heights.iter()) {
            let (width, _) = Layout::size_from_bbox(layout);
            let y = if center_y { (max_height - *height) / 2.0 } else { 0.0 };
            let moved = Layout::moved_to(layout, x, y);
            row.parts.extend(moved.parts);

            x += direction * width;
            x += distance;
        }

        Ok(row)
    }

    fn add_part(&mut self, part: Part) {
        self.parts.push(part);
    }

    fn bbox(&self) -> Option<(f64, f64, f64, f64)> {
        self.bbox_impl()
    }

    #[getter]
    fn min_x(&self) -> f64 {
        self.bbox_impl().map(|(min_x, _, _, _)| min_x).unwrap_or(0.0)
    }

    #[getter]
    fn max_x(&self) -> f64 {
        self.bbox_impl().map(|(_, max_x, _, _)| max_x).unwrap_or(0.0)
    }

    #[getter]
    fn min_y(&self) -> f64 {
        self.bbox_impl().map(|(_, _, min_y, _)| min_y).unwrap_or(0.0)
    }

    #[getter]
    fn max_y(&self) -> f64 {
        self.bbox_impl().map(|(_, _, _, max_y)| max_y).unwrap_or(0.0)
    }

    #[getter]
    fn width(&self) -> f64 {
        Layout::size_from_bbox(self).0.abs()
    }

    #[getter]
    fn height(&self) -> f64 {
        Layout::size_from_bbox(self).1.abs()
    }

    fn move_to(&mut self, target: Vector2DInput) -> PyResult<()> {
        let target = target.into_vector()?;
        self.move_to_xy(target.x, target.y);
        Ok(())
    }

    #[pyo3(signature = (other, distance = 0.0))]
    fn append_top(&mut self, other: &Layout, distance: f64) -> Self {
        let mut moved = other.clone();
        let y0 = if self.parts.is_empty() { 0.0 } else { self.max_y() + distance };
        moved.move_to_xy(0.0, y0);
        self.parts.extend(moved.parts);
        self.clone()
    }

    #[pyo3(signature = (other, distance = 0.0))]
    fn append_left(&mut self, other: &Layout, distance: f64) -> Self {
        let mut moved = other.clone();
        if !moved.parts.is_empty() {
            let x0 = moved.width() + distance;
            moved.move_to_xy(-x0, 0.0);
        }
        self.parts.extend(moved.parts);
        self.clone()
    }

    fn join(&mut self, other: &Layout) -> Self {
        self.parts.extend(other.parts.iter().cloned());
        self.clone()
    }

    #[pyo3(name = "move")]
    fn r#move(&self, offset: Vector2DInput) -> PyResult<Self> {
        let offset = offset.into_vector()?;
        Ok(self.transformed(|point| translate_point(point, offset)))
    }

    fn rotate(&self, angle: f64, radians: bool, center: Option<Vector2DInput>) -> PyResult<Self> {
        let angle = if radians { angle } else { angle.to_radians() };
        let center = match center {
            Some(center) => center.into_vector()?,
            None => Vector2D { x: 0.0, y: 0.0 },
        };
        Ok(self.transformed(|point| rotate_point(point, angle, center)))
    }

    fn scale(&self, factor: f64) -> Self {
        self.scaled(factor)
    }

    #[pyo3(signature = (border = 0.0))]
    fn to_svg_string(&self, border: f64) -> String {
        self.to_svg_document(border).to_string()
    }

    #[pyo3(signature = (path, border = 0.0))]
    fn export_svg(&self, path: String, border: f64) -> PyResult<()> {
        fs::write(&path, self.to_svg_document(border).to_string())
            .map_err(|error| PyIOError::new_err(format!("failed to write svg file '{}': {}", path, error)))
    }

    #[pyo3(signature = (path))]
    fn export_dxf(&self, path: String) -> PyResult<()> {
        fs::write(&path, self.to_dxf_string()?)
            .map_err(|error| PyIOError::new_err(format!("failed to write dxf file '{}': {}", path, error)))
    }

    fn __repr_svg_(&self) -> String {
        self.to_svg_document_with_size(800, 0.0).to_string()
    }
}

fn layer_classes(layer_name: &str, material_code: &str) -> String {
    let mut classes = vec![normalize_class_name(layer_name)];
    if !material_code.is_empty() {
        classes.push(normalize_class_name(material_code));
        classes.push(material_code.to_string());
    }
    classes.join(" ")
}

#[pymodule(submodule, name = "drawing")]
pub(crate) mod drawing_mod {
    #[pymodule_export]
    use super::Layer;
    #[pymodule_export]
    use super::LayerEditor;
    #[pymodule_export]
    use super::LayerStyleEditor;
    #[pymodule_export]
    use super::LayerStyle;
    #[pymodule_export]
    use super::Layout;
    #[pymodule_export]
    use super::Part;
    #[pymodule_export]
    use super::Text;
}