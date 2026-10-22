//! DXF export based on `cadkit-dxf`.
//!
//! By default every plot part becomes a block that is inserted once at the origin of model space
//! (coordinates stay in layout space, so the drawing looks identical). Without blocks all entities are
//! written directly into model space. `cadkit-dxf` writes the complete file structure AutoCAD requires
//! (handles, tables, `*Model_Space`/`*Paper_Space`, layouts, objects).

use std::collections::{BTreeMap, BTreeSet};

use cadkit_core::{
    Block, Color, Document, Entity, EntityKind, HAlign, Layer, Lineweight, Model, ModelKind, Point3, Units, VAlign,
    Vec3, Vertex,
};
use cadkit_dxf::DxfVersion;

use super::{dxf_text_anchor, normalize_text_align, stroke_to_aci, stroke_to_rgb, LayerStyle, Part, Text};
use crate::vector::PolyLine2D;

/// Version of the written file (R2013 = AC1027).
const DXF_VERSION: DxfVersion = DxfVersion::R2013;

fn clean_name(raw: &str, fallback: &str) -> String {
    let cleaned: String = raw
        .chars()
        .map(|ch| if ch.is_control() || "<>/\\\":;?*|,=`".contains(ch) { '_' } else { ch })
        .collect();
    let cleaned = cleaned.trim();

    if cleaned.is_empty() {
        fallback.to_string()
    } else {
        cleaned.chars().take(200).collect()
    }
}

fn unique_block_name(raw: Option<&str>, used: &mut BTreeSet<String>) -> String {
    let base = clean_name(raw.unwrap_or(""), "part");
    let mut name = base.clone();
    let mut counter = 1;
    while !used.insert(name.to_lowercase()) {
        name = format!("{}_{}", base, counter);
        counter += 1;
    }
    name
}

fn point(x: f64, y: f64) -> Point3 {
    Point3::new(x, y, 0.0)
}

fn z_axis() -> Vec3 {
    Vec3::new(0.0, 0.0, 1.0)
}

fn entity(kind: EntityKind, layer: &str, style: &LayerStyle) -> Entity {
    let mut entity = Entity::new(kind);
    entity.layer = Some(layer.to_string());
    entity.color = match stroke_to_rgb(&style.stroke) {
        Some((r, g, b)) => Color::Rgb { r, g, b },
        None => Color::Aci { index: stroke_to_aci(&style.stroke) },
    };
    entity.lineweight = Lineweight::Millimeters(if style.stroke_width.is_finite() { style.stroke_width } else { 0.25 });
    entity
}

fn line_entity(line: &PolyLine2D, layer: &str, style: &LayerStyle) -> Option<Entity> {
    match line.nodes.len() {
        0 => None,
        1 => Some(entity(
            EntityKind::Point { position: point(line.nodes[0].x, line.nodes[0].y) },
            layer,
            style,
        )),
        count => {
            let first = line.nodes[0];
            let last = line.nodes[count - 1];
            // closed polylines must not repeat the start vertex
            let closed = count > 2 && first.x == last.x && first.y == last.y;
            let end = if closed { count - 1 } else { count };

            let vertices = line.nodes[..end]
                .iter()
                .map(|node| Vertex { position: point(node.x, node.y), bulge: 0.0, start_width: 0.0, end_width: 0.0 })
                .collect();

            Some(entity(EntityKind::Polyline { vertices, closed, normal: z_axis() }, layer, style))
        }
    }
}

fn text_entity(text: &Text, layer: &str, style: &LayerStyle) -> Entity {
    let anchor = dxf_text_anchor(text);
    let height = style.font_size.unwrap_or_else(|| text.letter_height());
    let height = if height.is_finite() && height > 0.0 { height } else { 1.0 };

    let align = normalize_text_align(text.align);
    let halign = if align >= 0.33 {
        HAlign::Right
    } else if align <= -0.33 {
        HAlign::Left
    } else {
        HAlign::Center
    };
    let valign = if text.valign >= 0.75 {
        VAlign::Top
    } else if text.valign <= 0.25 {
        VAlign::Bottom
    } else {
        VAlign::Middle
    };

    let rotation = (text.p2.y - text.p1.y).atan2(text.p2.x - text.p1.x);
    let value: String = text.text.chars().map(|ch| if ch.is_control() { ' ' } else { ch }).collect();

    entity(
        EntityKind::Text {
            position: point(anchor.x, anchor.y),
            end_point: None,
            height,
            rotation: if rotation.is_finite() { rotation } else { 0.0 },
            width_factor: 1.0,
            oblique: 0.0,
            value,
            style: None,
            halign,
            valign,
            normal: z_axis(),
        },
        layer,
        style,
    )
}

fn layer_definition(name: &str, style: &LayerStyle) -> Layer {
    Layer {
        name: name.to_string(),
        color: Color::Aci { index: stroke_to_aci(&style.stroke) },
        visible: true,
        plottable: true,
        ..Layer::default()
    }
}

pub(super) fn parts_to_dxf(parts: &[Part], write_blocks: bool) -> Result<String, String> {
    let mut layers: BTreeMap<String, Layer> = BTreeMap::new();
    layers.insert(
        "0".to_string(),
        Layer {
            name: "0".to_string(),
            color: Color::Aci { index: 7 },
            visible: true,
            plottable: true,
            ..Layer::default()
        },
    );

    let mut used_block_names = BTreeSet::new();
    let mut blocks = Vec::new();
    let mut model_entities = Vec::new();

    for part in parts {
        let mut entities = Vec::new();

        for (layer_name, layer) in &part.layers {
            if !layer.style.visible {
                continue;
            }

            let name = clean_name(layer_name, "0");
            layers.entry(name.clone()).or_insert_with(|| layer_definition(&name, &layer.style));

            entities.extend(layer.lines.iter().filter_map(|line| line_entity(line, &name, &layer.style)));
            entities.extend(layer.texts.iter().map(|text| text_entity(text, &name, &layer.style)));
        }

        if entities.is_empty() {
            continue;
        }

        if !write_blocks {
            model_entities.extend(entities);
            continue;
        }

        let name = unique_block_name(part.name.as_deref(), &mut used_block_names);
        let mut insert = Entity::new(EntityKind::Insert {
            block: name.clone(),
            position: point(0.0, 0.0),
            scale: Vec3::new(1.0, 1.0, 1.0),
            rotation: 0.0,
            normal: z_axis(),
            columns: 1,
            rows: 1,
            column_spacing: 0.0,
            row_spacing: 0.0,
        });
        insert.layer = Some("0".to_string());
        model_entities.push(insert);

        blocks.push(Block { name, entities, ..Block::default() });
    }

    let document = Document {
        units: Units::default(),
        layers: layers.into_values().collect(),
        blocks,
        models: vec![Model { name: "Model".to_string(), kind: ModelKind::Model, entities: model_entities, ..Model::default() }],
        ..Document::default()
    };

    cadkit_dxf::write(&document, DXF_VERSION).map_err(|error| format!("failed to build dxf: {}", error))
}
