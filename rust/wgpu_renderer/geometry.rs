use crate::mesh::Mesh;
use std::collections::HashMap;

use super::Vertex;

fn triangle_normal(a: [f32; 3], b: [f32; 3], c: [f32; 3]) -> [f32; 3] {
    let ux = b[0] - a[0]; let uy = b[1] - a[1]; let uz = b[2] - a[2];
    let vx = c[0] - a[0]; let vy = c[1] - a[1]; let vz = c[2] - a[2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    let len = (nx * nx + ny * ny + nz * nz).sqrt().max(1e-6);
    [nx / len, ny / len, nz / len]
}

fn normalize_vector(v: [f32; 3]) -> [f32; 3] {
    let len = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt().max(1e-6);
    [v[0] / len, v[1] / len, v[2] / len]
}

fn compute_vertex_normals(mesh: &Mesh) -> Vec<[f32; 3]> {
    let mut accum = vec![[0.0_f32; 3]; mesh.points.len()];
    let mut counts = vec![0_u32; mesh.points.len()];

    for obj in &mesh.objects {
        for t in &obj.triangles {
            if let (Some(p0), Some(p1), Some(p2)) = (mesh.points.get(t.a), mesh.points.get(t.b), mesh.points.get(t.c)) {
                let a = [p0.x as f32, p0.y as f32, p0.z as f32];
                let b = [p1.x as f32, p1.y as f32, p1.z as f32];
                let c = [p2.x as f32, p2.y as f32, p2.z as f32];
                let n = triangle_normal(a, b, c);
                for idx in [t.a, t.b, t.c] {
                    if idx < accum.len() {
                        accum[idx][0] += n[0];
                        accum[idx][1] += n[1];
                        accum[idx][2] += n[2];
                        counts[idx] += 1;
                    }
                }
            }
        }

        for q in &obj.quads {
            for (ai, bi, ci) in [(q.a, q.b, q.c), (q.a, q.c, q.d)] {
                if let (Some(p0), Some(p1), Some(p2)) = (mesh.points.get(ai), mesh.points.get(bi), mesh.points.get(ci)) {
                    let a = [p0.x as f32, p0.y as f32, p0.z as f32];
                    let b = [p1.x as f32, p1.y as f32, p1.z as f32];
                    let c = [p2.x as f32, p2.y as f32, p2.z as f32];
                    let n = triangle_normal(a, b, c);
                    for idx in [ai, bi, ci] {
                        if idx < accum.len() {
                            accum[idx][0] += n[0];
                            accum[idx][1] += n[1];
                            accum[idx][2] += n[2];
                            counts[idx] += 1;
                        }
                    }
                }
            }
        }
    }

    let mut normals = vec![[0.0_f32; 3]; mesh.points.len()];
    for (idx, count) in counts.iter().enumerate() {
        if *count > 0 {
            normals[idx] = normalize_vector(accum[idx]);
        } else {
            normals[idx] = [0.0, 0.0, 1.0];
        }
    }

    normals
}

fn mesh_uv(mesh: &Mesh, index: usize) -> [f32; 2] {
    mesh
        .uv_coords
        .as_ref()
        .and_then(|uvs| uvs.get(index).copied())
        .unwrap_or([0.0, 0.0])
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct EdgeKey(u32, u32);
impl EdgeKey {
    fn new(a: u32, b: u32) -> Self { if a < b { EdgeKey(a, b) } else { EdgeKey(b, a) } }
}

/// Returns `(fill, mesh_lines, polygon_edges)`.
///
/// - `fill`:          fill vertices from triangles/quads
/// - `mesh_lines`:    vertices from MeshObject::lines (always emitted, depth-tested only)
/// - `polygon_edges`: outline vertices from polygon topology (stencil-tested at render time)
pub(crate) fn mesh_to_vertices(
    mesh: &Mesh,
    draw_polygon_edges: bool,
    boundary_only: bool,
) -> (Vec<Vertex>, Vec<Vertex>, Vec<Vertex>) {
    let mut fill: Vec<Vertex> = Vec::new();
    let mut mesh_lines: Vec<Vertex> = Vec::new();
    let mut poly_edges: Vec<Vertex> = Vec::new();
    let mut edge_count: HashMap<EdgeKey, u32> = HashMap::new();
    let vertex_normals = compute_vertex_normals(mesh);
    let use_texture = if mesh.texture.is_some() { 1.0 } else { 0.0 };

    if boundary_only && draw_polygon_edges {
        for obj in &mesh.objects {
            for t in &obj.triangles {
                for (a, b) in [(t.a, t.b), (t.b, t.c), (t.c, t.a)] {
                    edge_count.entry(EdgeKey::new(a as u32, b as u32)).and_modify(|e| *e += 1).or_insert(1);
                }
            }
            for q in &obj.quads {
                for (a, b) in [(q.a, q.b), (q.b, q.c), (q.c, q.d), (q.d, q.a)] {
                    edge_count.entry(EdgeKey::new(a as u32, b as u32)).and_modify(|e| *e += 1).or_insert(1);
                }
            }
        }
    }

    for obj in &mesh.objects {
        let color = [obj.color.0 as f32 / 255.0, obj.color.1 as f32 / 255.0, obj.color.2 as f32 / 255.0];
        let ec = [((color[0]*0.5+0.5).max(0.7)).min(1.0), ((color[1]*0.5+0.5).max(0.7)).min(1.0), ((color[2]*0.5+0.5).max(0.7)).min(1.0)];

        for line in &obj.lines {
            if let (Some(a), Some(b)) = (mesh.points.get(line.a), mesh.points.get(line.b)) {
                mesh_lines.push(Vertex {
                    position: [a.x as f32, a.y as f32, a.z as f32],
                    color,
                    normal: [0.0, 0.0, 1.0],
                    tex_coord: [0.0, 0.0],
                    use_texture: 0.0,
                });
                mesh_lines.push(Vertex {
                    position: [b.x as f32, b.y as f32, b.z as f32],
                    color,
                    normal: [0.0, 0.0, 1.0],
                    tex_coord: [0.0, 0.0],
                    use_texture: 0.0,
                });
            }
        }

        for t in &obj.triangles {
            if let (Some(p0), Some(p1), Some(p2)) = (mesh.points.get(t.a), mesh.points.get(t.b), mesh.points.get(t.c)) {
                let a = [p0.x as f32, p0.y as f32, p0.z as f32];
                let b = [p1.x as f32, p1.y as f32, p1.z as f32];
                let c = [p2.x as f32, p2.y as f32, p2.z as f32];
                let normals = [
                    vertex_normals.get(t.a).copied().unwrap_or([0.0, 0.0, 1.0]),
                    vertex_normals.get(t.b).copied().unwrap_or([0.0, 0.0, 1.0]),
                    vertex_normals.get(t.c).copied().unwrap_or([0.0, 0.0, 1.0]),
                ];
                let tex = [mesh_uv(mesh, t.a), mesh_uv(mesh, t.b), mesh_uv(mesh, t.c)];
                fill.push(Vertex { position: a, color, normal: normals[0], tex_coord: tex[0], use_texture });
                fill.push(Vertex { position: b, color, normal: normals[1], tex_coord: tex[1], use_texture });
                fill.push(Vertex { position: c, color, normal: normals[2], tex_coord: tex[2], use_texture });
                if draw_polygon_edges {
                    for (k, pa, pb) in [
                        (EdgeKey::new(t.a as u32, t.b as u32), a, b),
                        (EdgeKey::new(t.b as u32, t.c as u32), b, c),
                        (EdgeKey::new(t.c as u32, t.a as u32), c, a),
                    ] {
                        if !boundary_only || edge_count.get(&k).map_or(false, |&n| n == 1) {
                            poly_edges.push(Vertex { position: pa, color: ec, normal: [0.0,0.0,1.0], tex_coord: [0.0, 0.0], use_texture: 0.0 });
                            poly_edges.push(Vertex { position: pb, color: ec, normal: [0.0,0.0,1.0], tex_coord: [0.0, 0.0], use_texture: 0.0 });
                        }
                    }
                }
            }
        }

        for q in &obj.quads {
            for (ai, bi, ci) in [(q.a, q.b, q.c), (q.a, q.c, q.d)] {
                if let (Some(p0), Some(p1), Some(p2)) = (mesh.points.get(ai), mesh.points.get(bi), mesh.points.get(ci)) {
                    let a = [p0.x as f32, p0.y as f32, p0.z as f32];
                    let b = [p1.x as f32, p1.y as f32, p1.z as f32];
                    let c = [p2.x as f32, p2.y as f32, p2.z as f32];
                    let normals = [
                        vertex_normals.get(ai).copied().unwrap_or([0.0, 0.0, 1.0]),
                        vertex_normals.get(bi).copied().unwrap_or([0.0, 0.0, 1.0]),
                        vertex_normals.get(ci).copied().unwrap_or([0.0, 0.0, 1.0]),
                    ];
                    let tex = [mesh_uv(mesh, ai), mesh_uv(mesh, bi), mesh_uv(mesh, ci)];
                    fill.push(Vertex { position: a, color, normal: normals[0], tex_coord: tex[0], use_texture });
                    fill.push(Vertex { position: b, color, normal: normals[1], tex_coord: tex[1], use_texture });
                    fill.push(Vertex { position: c, color, normal: normals[2], tex_coord: tex[2], use_texture });
                }
            }
            if draw_polygon_edges {
                if let (Some(pa), Some(pb), Some(pc), Some(pd)) = (
                    mesh.points.get(q.a), mesh.points.get(q.b), mesh.points.get(q.c), mesh.points.get(q.d)) {
                    let pts = [[pa.x as f32,pa.y as f32,pa.z as f32],[pb.x as f32,pb.y as f32,pb.z as f32],[pc.x as f32,pc.y as f32,pc.z as f32],[pd.x as f32,pd.y as f32,pd.z as f32]];
                    for (ai, bi, pi, qi) in [(q.a,q.b,0usize,1usize),(q.b,q.c,1,2),(q.c,q.d,2,3),(q.d,q.a,3,0)] {
                        let k = EdgeKey::new(ai as u32, bi as u32);
                        if !boundary_only || edge_count.get(&k).map_or(false, |&n| n == 1) {
                            poly_edges.push(Vertex { position: pts[pi], color: ec, normal: [0.0,0.0,1.0], tex_coord: [0.0, 0.0], use_texture: 0.0 });
                            poly_edges.push(Vertex { position: pts[qi], color: ec, normal: [0.0,0.0,1.0], tex_coord: [0.0, 0.0], use_texture: 0.0 });
                        }
                    }
                }
            }
        }
    }

    (fill, mesh_lines, poly_edges)
}
