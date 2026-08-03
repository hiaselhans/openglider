struct Camera {
    mvp: mat4x4<f32>,
};

@group(0) @binding(0)
var<uniform> camera: Camera;
@group(1) @binding(0)
var color_texture: texture_2d<f32>;
@group(1) @binding(1)
var color_sampler: sampler;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) color: vec3<f32>,
    @location(2) normal: vec3<f32>,
    @location(3) tex_coord: vec2<f32>,
    @location(4) use_texture: f32,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(linear) color: vec3<f32>,
    @location(1) @interpolate(linear) normal: vec3<f32>,
    @location(2) @interpolate(linear) tex_coord: vec2<f32>,
    @location(3) @interpolate(flat) use_texture: f32,
};

@vertex
fn vs_main(input: VertexInput) -> VertexOutput {
    var output: VertexOutput;
    output.clip_position = camera.mvp * vec4<f32>(input.position, 1.0);
    output.color = input.color;
    output.normal = input.normal;
    output.tex_coord = input.tex_coord;
    output.use_texture = input.use_texture;
    return output;
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    let tex_sample = textureSample(color_texture, color_sampler, input.tex_coord);
    let texture_weight = select(0.0, tex_sample.a, input.use_texture > 0.5);
    let source_color = mix(input.color, tex_sample.rgb, texture_weight);

    let light_dir = normalize(vec3<f32>(0.35, 0.8, 0.45));
    let view_dir = normalize(vec3<f32>(0.0, 0.0, 1.0));
    let n = normalize(input.normal);
    let ndotl = abs(dot(n, light_dir));
    let ambient = 0.16;
    let diffuse = 0.24 + 0.76 * pow(ndotl, 0.9);

    let reflected = reflect(-light_dir, n);
    let specular = pow(max(dot(reflected, view_dir), 0.0), 64.0);
    let rim = pow(1.0 - max(dot(n, view_dir), 0.0), 3.2);

    let luma = dot(source_color, vec3<f32>(0.2126, 0.7152, 0.0722));
    let saturated = mix(vec3<f32>(luma, luma, luma), source_color, 1.75);

    let base = saturated * (ambient + diffuse * 1.02);
    let highlight = vec3<f32>(1.0, 0.98, 0.92) * (0.12 * specular + 0.10 * rim);
    let color = clamp(base + highlight, vec3<f32>(0.0, 0.0, 0.0), vec3<f32>(1.0, 1.0, 1.0));

    return vec4<f32>(color, 1.0);
}
