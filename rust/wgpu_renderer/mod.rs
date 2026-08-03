use bytemuck::{Pod, Zeroable};
use nalgebra::{Matrix4, Orthographic3, Perspective3, Point3, Vector3};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use raw_window_handle::{
    AppKitDisplayHandle, AppKitWindowHandle, RawDisplayHandle, RawWindowHandle,
    WaylandDisplayHandle, WaylandWindowHandle, Win32WindowHandle, WindowsDisplayHandle,
    XcbDisplayHandle, XcbWindowHandle, XlibDisplayHandle, XlibWindowHandle,
};
use wgpu::util::DeviceExt;
use std::num::{NonZeroIsize, NonZeroU32};
use std::sync::atomic::{AtomicU64, Ordering};

#[cfg(target_os = "linux")]
use x11_dl::xlib;

mod camera;
mod geometry;

use camera::{matrix_to_uniform, ProjectionMode};
use geometry::mesh_to_vertices;

use crate::mesh::{Mesh, MeshTexture};

#[repr(C)]
#[derive(Clone, Copy, Debug, Pod, Zeroable)]
struct Vertex {
    position: [f32; 3],
    color: [f32; 3],
    normal: [f32; 3],
    tex_coord: [f32; 2],
    use_texture: f32,
}

impl Vertex {
    fn layout<'a>() -> wgpu::VertexBufferLayout<'a> {
        wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Vertex>() as u64,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &[
                wgpu::VertexAttribute {
                    offset: 0,
                    shader_location: 0,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: std::mem::size_of::<[f32; 3]>() as u64,
                    shader_location: 1,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: std::mem::size_of::<[f32; 6]>() as u64,
                    shader_location: 2,
                    format: wgpu::VertexFormat::Float32x3,
                },
                wgpu::VertexAttribute {
                    offset: std::mem::size_of::<[f32; 9]>() as u64,
                    shader_location: 3,
                    format: wgpu::VertexFormat::Float32x2,
                },
                wgpu::VertexAttribute {
                    offset: std::mem::size_of::<[f32; 11]>() as u64,
                    shader_location: 4,
                    format: wgpu::VertexFormat::Float32,
                },
            ],
        }
    }
}

#[derive(Clone)]
struct TextureData {
    width: u32,
    height: u32,
    rgba: Vec<u8>,
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct CameraUniform {
    mvp: [[f32; 4]; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ColorBoundsUniform {
    min_val: f32,
    max_val: f32,
    _pad0: f32,
    _pad1: f32,
}

#[derive(Clone, Copy)]
struct CameraState {
    yaw: f32,
    pitch: f32,
    distance: f32,
    target: [f32; 3],
}

impl Default for CameraState {
    fn default() -> Self {
        Self {
            yaw: -1.2,
            pitch: 0.3,
            distance: 20.0,
            target: [0.0, 0.0, 0.0],
        }
    }
}

struct DepthResources {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
}

impl DepthResources {
    fn new(device: &wgpu::Device, width: u32, height: u32) -> Self {
        let size = wgpu::Extent3d {
            width: width.max(1),
            height: height.max(1),
            depth_or_array_layers: 1,
        };

        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("openglider.depth"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth24PlusStencil8,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });

        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
        Self { _texture: texture, view }
    }
}

struct NativeHandles {
    #[cfg(target_os = "linux")]
    _xlib: Option<xlib::Xlib>,
    raw_display_handle: RawDisplayHandle,
    raw_window_handle: RawWindowHandle,
}

#[cfg(target_os = "linux")]
fn linux_xlib_handles(window_id: u64, display_id: Option<u64>) -> PyResult<NativeHandles> {
    let xlib = xlib::Xlib::open().map_err(|_| PyRuntimeError::new_err("failed to load libX11"))?;
    let display = if let Some(id) = display_id {
        id as *mut xlib::Display
    } else {
        unsafe { (xlib.XOpenDisplay)(std::ptr::null()) }
    };
    if display.is_null() {
        return Err(PyRuntimeError::new_err(
            "failed to open X11 display; this renderer currently requires X11",
        ));
    }

    let display_ptr = display.cast::<std::ffi::c_void>();
    let screen = unsafe { (xlib.XDefaultScreen)(display) };

    let mut display_handle = XlibDisplayHandle::new(None, screen);
    display_handle.display = std::ptr::NonNull::new(display_ptr.cast());

    let mut window_handle = XlibWindowHandle::new(window_id);
    window_handle.visual_id = 0;

    Ok(NativeHandles {
        _xlib: Some(xlib),
        raw_display_handle: RawDisplayHandle::Xlib(display_handle),
        raw_window_handle: RawWindowHandle::Xlib(window_handle),
    })
}

fn make_native_handles(platform: &str, window_id: u64, display_id: Option<u64>) -> PyResult<NativeHandles> {
    match platform {
        "wayland" => {
            let display_ptr = display_id
                .and_then(|value| std::ptr::NonNull::new(value as *mut std::ffi::c_void))
                .ok_or_else(|| PyValueError::new_err("wayland requires non-zero display_id"))?;
            let surface_ptr = std::ptr::NonNull::new(window_id as *mut std::ffi::c_void)
                .ok_or_else(|| PyValueError::new_err("wayland requires non-zero window_id"))?;

            let display_handle = WaylandDisplayHandle::new(display_ptr);
            let window_handle = WaylandWindowHandle::new(surface_ptr);

            Ok(NativeHandles {
                #[cfg(target_os = "linux")]
                _xlib: None,
                raw_display_handle: RawDisplayHandle::Wayland(display_handle),
                raw_window_handle: RawWindowHandle::Wayland(window_handle),
            })
        }
        "xcb" => {
            let connection_ptr = display_id
                .and_then(|value| std::ptr::NonNull::new(value as *mut std::ffi::c_void));
            let window = NonZeroU32::new(window_id as u32)
                .ok_or_else(|| PyValueError::new_err("xcb requires non-zero 32-bit window_id"))?;

            let display_handle = XcbDisplayHandle::new(connection_ptr, 0);
            let window_handle = XcbWindowHandle::new(window);

            Ok(NativeHandles {
                #[cfg(target_os = "linux")]
                _xlib: None,
                raw_display_handle: RawDisplayHandle::Xcb(display_handle),
                raw_window_handle: RawWindowHandle::Xcb(window_handle),
            })
        }
        "x11" => {
            #[cfg(target_os = "linux")]
            {
                linux_xlib_handles(window_id, display_id)
            }

            #[cfg(not(target_os = "linux"))]
            {
                let _ = display_id;
                Err(PyRuntimeError::new_err("x11 surface is only available on Linux"))
            }
        }
        "win32" => {
            let hwnd = NonZeroIsize::new(window_id as isize)
                .ok_or_else(|| PyValueError::new_err("win32 requires non-zero window_id"))?;
            let display_handle = WindowsDisplayHandle::new();
            let window_handle = Win32WindowHandle::new(hwnd);

            Ok(NativeHandles {
                #[cfg(target_os = "linux")]
                _xlib: None,
                raw_display_handle: RawDisplayHandle::Windows(display_handle),
                raw_window_handle: RawWindowHandle::Win32(window_handle),
            })
        }
        "appkit" => {
            let ns_view = std::ptr::NonNull::new(window_id as *mut std::ffi::c_void)
                .ok_or_else(|| PyValueError::new_err("appkit requires non-zero window_id"))?;
            let display_handle = AppKitDisplayHandle::new();
            let window_handle = AppKitWindowHandle::new(ns_view);

            Ok(NativeHandles {
                #[cfg(target_os = "linux")]
                _xlib: None,
                raw_display_handle: RawDisplayHandle::AppKit(display_handle),
                raw_window_handle: RawWindowHandle::AppKit(window_handle),
            })
        }
        other => Err(PyValueError::new_err(format!(
            "unsupported platform '{other}', expected one of: x11, xcb, wayland, win32, appkit"
        ))),
    }
}

const SHADER_SOURCE: &str = include_str!("shader.wgsl");

struct MeshData {
    fill_vertex_buffer: wgpu::Buffer,
    fill_vertex_count: u32,
    mesh_line_vertex_buffer: wgpu::Buffer,
    mesh_line_vertex_count: u32,
    poly_edge_vertex_buffer: wgpu::Buffer,
    poly_edge_vertex_count: u32,
}

struct TextureResources {
    _texture: wgpu::Texture,
    _view: wgpu::TextureView,
    bind_group: wgpu::BindGroup,
}

/// Pre-calculated mesh with all edge mode variants cached
struct CachedActor {
    no_edges: MeshData,
    all_edges: MeshData,
    boundary_edges: MeshData,
    texture: Option<TextureResources>,
    current_mode: EdgeMode,
    visible: bool,
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum EdgeMode {
    NoEdges,
    AllEdges,
    BoundaryOnly,
}

impl CachedActor {
    fn get_data(&self) -> &MeshData {
        match self.current_mode {
            EdgeMode::NoEdges => &self.no_edges,
            EdgeMode::AllEdges => &self.all_edges,
            EdgeMode::BoundaryOnly => &self.boundary_edges,
        }
    }

    fn set_edge_mode(&mut self, draw_edges: bool, boundary_only: bool) {
        self.current_mode = match (draw_edges, boundary_only) {
            (false, _) => EdgeMode::NoEdges,
            (true, false) => EdgeMode::AllEdges,
            (true, true) => EdgeMode::BoundaryOnly,
        };
    }
}

static ACTOR_COUNTER: AtomicU64 = AtomicU64::new(0);

/// Pre-computed mesh actor: holds CPU-side vertex data for all edge variants.
/// Create once from a Mesh; add/remove from the renderer cheaply via visibility toggle.
#[pyclass]
pub struct MeshActor {
    id: u64,
    fill: Vec<Vertex>,
    mesh_lines: Vec<Vertex>,
    all_poly_edges: Vec<Vertex>,
    boundary_poly_edges: Vec<Vertex>,
    texture: Option<TextureData>,
    draw_edges: bool,
    boundary_only: bool,
}

#[pymethods]
impl MeshActor {
    #[new]
    #[pyo3(signature = (mesh, draw_edges=false, boundary_only=false))]
    fn new(mesh: PyRef<'_, Mesh>, draw_edges: bool, boundary_only: bool) -> Self {
        let id = ACTOR_COUNTER.fetch_add(1, Ordering::Relaxed);
        let (fill, mesh_lines, _) = mesh_to_vertices(&mesh, false, false);
        let (_, _, all_poly) = mesh_to_vertices(&mesh, true, false);
        let (_, _, boundary_poly) = mesh_to_vertices(&mesh, true, true);
        let texture = mesh.texture.as_ref().map(|texture: &MeshTexture| TextureData {
            width: texture.width,
            height: texture.height,
            rgba: texture.rgba.clone(),
        });
        MeshActor {
            id,
            fill,
            mesh_lines,
            all_poly_edges: all_poly,
            boundary_poly_edges: boundary_poly,
            texture,
            draw_edges,
            boundary_only,
        }
    }
}

struct RendererState {
    _instance: wgpu::Instance,
    surface: wgpu::Surface<'static>,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    fill_pipeline: wgpu::RenderPipeline,
    mesh_line_pipeline: wgpu::RenderPipeline,
    polygon_edge_pipeline: wgpu::RenderPipeline,
    camera: CameraState,
    projection_mode: ProjectionMode,
    uniform_buffer: wgpu::Buffer,
    uniform_bind_group: wgpu::BindGroup,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    texture_sampler: wgpu::Sampler,
    default_texture_bind_group: wgpu::BindGroup,
    color_bounds_buffer: wgpu::Buffer,
    depth: DepthResources,
    actors: Vec<(String, CachedActor)>,
    width: u32,
    height: u32,
    draw_edges: bool,
    boundary_only: bool,
    _native: NativeHandles,
}

impl RendererState {
    fn create_texture_resources(&self, texture: &TextureData) -> Option<TextureResources> {
        if texture.width == 0 || texture.height == 0 {
            return None;
        }
        if texture.rgba.len() != texture.width as usize * texture.height as usize * 4 {
            return None;
        }

        let gpu_texture = self.device.create_texture_with_data(
            &self.queue,
            &wgpu::TextureDescriptor {
                label: Some("openglider.texture.actor"),
                size: wgpu::Extent3d {
                    width: texture.width,
                    height: texture.height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8UnormSrgb,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            },
            wgpu::util::TextureDataOrder::LayerMajor,
            &texture.rgba,
        );

        let view = gpu_texture.create_view(&wgpu::TextureViewDescriptor::default());
        let bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("openglider.texture.actor.bindgroup"),
            layout: &self.texture_bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.texture_sampler),
                },
            ],
        });

        Some(TextureResources {
            _texture: gpu_texture,
            _view: view,
            bind_group,
        })
    }

    fn new(platform: &str, window_id: u64, width: u32, height: u32, display_id: Option<u64>) -> PyResult<Self> {
        let native = make_native_handles(platform, window_id, display_id)?;

        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::default());
        let surface = unsafe {
            instance.create_surface_unsafe(wgpu::SurfaceTargetUnsafe::RawHandle {
                raw_display_handle: native.raw_display_handle,
                raw_window_handle: native.raw_window_handle,
            })
        }
        .map_err(|error| PyRuntimeError::new_err(format!("failed to create wgpu surface: {error}")))?;

        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: Some(&surface),
            force_fallback_adapter: false,
        }))
        .ok_or_else(|| PyRuntimeError::new_err("failed to acquire wgpu adapter"))?;

        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("openglider.wgpu.device"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
            },
            None,
        ))
        .map_err(|error| PyRuntimeError::new_err(format!("failed to create wgpu device: {error}")))?;

        let caps = surface.get_capabilities(&adapter);
        let surface_format = caps
            .formats
            .iter()
            .copied()
            .find(|format| format.is_srgb())
            .unwrap_or_else(|| caps.formats[0]);

        let present_mode = caps
            .present_modes
            .iter()
            .copied()
            .find(|mode| *mode == wgpu::PresentMode::Fifo)
            .unwrap_or(caps.present_modes[0]);

        let alpha_mode = caps.alpha_modes[0];

        let mut config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format: surface_format,
            width: width.max(1),
            height: height.max(1),
            present_mode,
            alpha_mode,
            view_formats: vec![],
            desired_maximum_frame_latency: 2,
        };

        surface.configure(&device, &config);

        let uniform = CameraUniform {
            mvp: matrix_to_uniform(Matrix4::identity()),
        };
        let uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("openglider.camera.uniform"),
            contents: bytemuck::bytes_of(&uniform),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let color_bounds = ColorBoundsUniform {
            min_val: 0.12,
            max_val: 0.95,
            _pad0: 0.0,
            _pad1: 0.0,
        };
        let color_bounds_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("openglider.colorbounds.uniform"),
            contents: bytemuck::bytes_of(&color_bounds),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let uniform_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("openglider.uniforms.layout"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::VERTEX,
                        ty: wgpu::BindingType::Buffer {
                            ty: wgpu::BufferBindingType::Uniform,
                            has_dynamic_offset: false,
                            min_binding_size: wgpu::BufferSize::new(std::mem::size_of::<CameraUniform>() as u64),
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Buffer {
                            ty: wgpu::BufferBindingType::Uniform,
                            has_dynamic_offset: false,
                            min_binding_size: wgpu::BufferSize::new(std::mem::size_of::<ColorBoundsUniform>() as u64),
                        },
                        count: None,
                    },
                ],
            });

        let texture_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("openglider.texture.layout"),
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            multisampled: false,
                            view_dimension: wgpu::TextureViewDimension::D2,
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                        count: None,
                    },
                ],
            });

        let uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("openglider.uniforms.bindgroup"),
            layout: &uniform_bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform_buffer.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: color_bounds_buffer.as_entire_binding(),
                },
            ],
        });

        let texture_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("openglider.texture.sampler"),
            address_mode_u: wgpu::AddressMode::ClampToEdge,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            address_mode_w: wgpu::AddressMode::ClampToEdge,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Nearest,
            ..Default::default()
        });

        let default_texture = device.create_texture_with_data(
            &queue,
            &wgpu::TextureDescriptor {
                label: Some("openglider.texture.default"),
                size: wgpu::Extent3d {
                    width: 1,
                    height: 1,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8UnormSrgb,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            },
            wgpu::util::TextureDataOrder::LayerMajor,
            &[255, 255, 255, 255],
        );
        let default_texture_view = default_texture.create_view(&wgpu::TextureViewDescriptor::default());
        let default_texture_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("openglider.texture.default.bindgroup"),
            layout: &texture_bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&default_texture_view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&texture_sampler),
                },
            ],
        });

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("openglider.mesh.shader"),
            source: wgpu::ShaderSource::Wgsl(SHADER_SOURCE.into()),
        });

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("openglider.pipeline.layout"),
            bind_group_layouts: &[&uniform_bind_group_layout, &texture_bind_group_layout],
            push_constant_ranges: &[],
        });

        let fill_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("openglider.mesh.pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_main",
                buffers: &[Vertex::layout()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: config.format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                strip_index_format: None,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                polygon_mode: wgpu::PolygonMode::Fill,
                unclipped_depth: false,
                conservative: false,
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth24PlusStencil8,
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::Less,
                // Write actor stencil ID so polygon edges can test against it
                stencil: wgpu::StencilState {
                    front: wgpu::StencilFaceState {
                        compare: wgpu::CompareFunction::Always,
                        fail_op: wgpu::StencilOperation::Keep,
                        depth_fail_op: wgpu::StencilOperation::Keep,
                        pass_op: wgpu::StencilOperation::Replace,
                    },
                    back: wgpu::StencilFaceState {
                        compare: wgpu::CompareFunction::Always,
                        fail_op: wgpu::StencilOperation::Keep,
                        depth_fail_op: wgpu::StencilOperation::Keep,
                        pass_op: wgpu::StencilOperation::Replace,
                    },
                    read_mask: 0xFF,
                    write_mask: 0xFF,
                },
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        // Mesh lines: depth-tested only, no stencil interaction
        let mesh_line_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("openglider.mesh.line.pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_main",
                buffers: &[Vertex::layout()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: config.format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::LineList,
                strip_index_format: None,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                polygon_mode: wgpu::PolygonMode::Fill,
                unclipped_depth: false,
                conservative: false,
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth24PlusStencil8,
                depth_write_enabled: false,
                depth_compare: wgpu::CompareFunction::LessEqual,
                stencil: wgpu::StencilState::default(),  // no stencil interaction
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        // Polygon edges: only draw on pixels where stencil == actor ID
        let polygon_edge_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("openglider.mesh.polyedge.pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_main",
                buffers: &[Vertex::layout()],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: config.format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: wgpu::PipelineCompilationOptions::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::LineList,
                strip_index_format: None,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                polygon_mode: wgpu::PolygonMode::Fill,
                unclipped_depth: false,
                conservative: false,
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth24PlusStencil8,
                depth_write_enabled: false,
                depth_compare: wgpu::CompareFunction::LessEqual,
                stencil: wgpu::StencilState {
                    front: wgpu::StencilFaceState {
                        compare: wgpu::CompareFunction::Equal,
                        fail_op: wgpu::StencilOperation::Keep,
                        depth_fail_op: wgpu::StencilOperation::Keep,
                        pass_op: wgpu::StencilOperation::Keep,
                    },
                    back: wgpu::StencilFaceState {
                        compare: wgpu::CompareFunction::Equal,
                        fail_op: wgpu::StencilOperation::Keep,
                        depth_fail_op: wgpu::StencilOperation::Keep,
                        pass_op: wgpu::StencilOperation::Keep,
                    },
                    read_mask: 0xFF,
                    write_mask: 0x00,
                },
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        let depth = DepthResources::new(&device, config.width, config.height);

        config.width = config.width.max(1);
        config.height = config.height.max(1);

        let mut state = Self {
            _instance: instance,
            surface,
            device,
            queue,
            config,
            fill_pipeline,
            mesh_line_pipeline,
            polygon_edge_pipeline,
            camera: CameraState::default(),
            projection_mode: ProjectionMode::Orthographic,
            uniform_buffer,
            uniform_bind_group,
            texture_bind_group_layout,
            texture_sampler,
            default_texture_bind_group,
            color_bounds_buffer,
            depth,
            actors: Vec::new(),
            width,
            height,
            draw_edges: false,
            boundary_only: false,
            _native: native,
        };

        state.update_camera();
        Ok(state)
    }

    fn update_camera(&mut self) {
        let target = Point3::new(self.camera.target[0], self.camera.target[1], self.camera.target[2]);

        let yaw = self.camera.yaw;
        let pitch = self.camera.pitch;
        let zoom_distance = self.camera.distance.max(0.1);

        // In orthographic mode, treat camera.distance as zoom scale, not as
        // physical camera translation. Keeping the camera far away avoids
        // clipping geometry when users zoom in close.
        let eye_distance = match self.projection_mode {
            ProjectionMode::Perspective => zoom_distance,
            ProjectionMode::Orthographic => 2000.0,
        };

        let eye = Point3::new(
            target.x + eye_distance * pitch.cos() * yaw.cos(),
            target.y + eye_distance * pitch.cos() * yaw.sin(),
            target.z + eye_distance * pitch.sin(),
        );

        let up = Vector3::new(0.0, 0.0, 1.0);
        let view = Matrix4::look_at_rh(&eye, &target, &up);

        let aspect = (self.config.width.max(1) as f32) / (self.config.height.max(1) as f32);
        let projection = match self.projection_mode {
            ProjectionMode::Perspective => {
                // Keep near small and avoid clamping to large values that can
                // clip close geometry too early.
                let near = (zoom_distance * 0.001).clamp(0.0001, 0.1);
                let far = (zoom_distance * 4000.0).max(20_000.0);
                Perspective3::new(aspect, 45f32.to_radians(), near, far).to_homogeneous()
            }
            ProjectionMode::Orthographic => {
                // Ortho zoom is controlled by half extents, not camera motion.
                let half_height = (zoom_distance * 0.5).max(0.05);
                let half_width = half_height * aspect;
                let near = 0.0001;
                let far = 10_000.0;
                Orthographic3::new(
                    -half_width,
                    half_width,
                    -half_height,
                    half_height,
                    near,
                    far,
                )
                .to_homogeneous()
            }
        };

        // Convert OpenGL-style clip space (z in [-1, 1]) to WGPU clip space
        // (z in [0, 1]). This keeps depth testing and perspective consistent.
        let opengl_to_wgpu = Matrix4::new(
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 0.5, 0.5,
            0.0, 0.0, 0.0, 1.0,
        );

        let uniform = CameraUniform {
            mvp: matrix_to_uniform(opengl_to_wgpu * projection * view),
        };
        self.queue
            .write_buffer(&self.uniform_buffer, 0, bytemuck::bytes_of(&uniform));
    }

    fn set_projection(&mut self, mode: &str) -> PyResult<()> {
        self.projection_mode = ProjectionMode::from_str(mode)?;
        self.update_camera();
        Ok(())
    }

    fn set_color_bounds(&mut self, min_val: f32, max_val: f32) {
        let color_bounds = ColorBoundsUniform {
            min_val: min_val.clamp(0.0, 1.0),
            max_val: max_val.clamp(0.0, 1.0),
            _pad0: 0.0,
            _pad1: 0.0,
        };
        self.queue.write_buffer(&self.color_bounds_buffer, 0, bytemuck::bytes_of(&color_bounds));
    }

    fn resize(&mut self, width: u32, height: u32) {
        self.config.width = width.max(1);
        self.config.height = height.max(1);
        self.width = width;
        self.height = height;
        self.surface.configure(&self.device, &self.config);
        self.depth = DepthResources::new(&self.device, self.config.width, self.config.height);
        self.update_camera();
    }

    fn make_buf(&self, data: &[Vertex]) -> wgpu::Buffer {
        if data.is_empty() {
            self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("openglider.mesh.empty"),
                size: std::mem::size_of::<Vertex>() as u64,
                usage: wgpu::BufferUsages::VERTEX,
                mapped_at_creation: false,
            })
        } else {
            self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("openglider.mesh.buf"),
                contents: bytemuck::cast_slice(data),
                usage: wgpu::BufferUsages::VERTEX,
            })
        }
    }

    fn create_mesh_data(&self, fill: &[Vertex], mesh_lines: &[Vertex], poly_edges: &[Vertex]) -> MeshData {
        MeshData {
            fill_vertex_buffer: self.make_buf(fill),
            fill_vertex_count: fill.len() as u32,
            mesh_line_vertex_buffer: self.make_buf(mesh_lines),
            mesh_line_vertex_count: mesh_lines.len() as u32,
            poly_edge_vertex_buffer: self.make_buf(poly_edges),
            poly_edge_vertex_count: poly_edges.len() as u32,
        }
    }

    fn add_mesh(&mut self, name: String, mesh: &Mesh, draw_edges: Option<bool>, boundary_only: Option<bool>) {
        let (fill, mesh_lines, _) = mesh_to_vertices(mesh, false, false);
        let (_, _, all_poly) = mesh_to_vertices(mesh, true, false);
        let (_, _, bnd_poly) = mesh_to_vertices(mesh, true, true);

        let no_edges = self.create_mesh_data(&fill, &mesh_lines, &[]);
        let all_edges = self.create_mesh_data(&fill, &mesh_lines, &all_poly);
        let boundary_edges = self.create_mesh_data(&fill, &mesh_lines, &bnd_poly);

        let draw_edges = draw_edges.unwrap_or(false);
        let boundary_only = boundary_only.unwrap_or(false);

        let mut actor = CachedActor {
            no_edges,
            all_edges,
            boundary_edges,
            texture: mesh.texture.as_ref().and_then(|t| {
                self.create_texture_resources(&TextureData {
                    width: t.width,
                    height: t.height,
                    rgba: t.rgba.clone(),
                })
            }),
            current_mode: EdgeMode::NoEdges,
            visible: true,
        };
        
        // Set initial mode based on parameters
        actor.set_edge_mode(draw_edges, boundary_only);

        // Remove existing actor with same name
        self.actors.retain(|(n, _)| n != &name);
        self.actors.push((name, actor));
    }

    fn set_actor_visibility(&mut self, name: &str, visible: bool) {
        for (actor_name, actor) in &mut self.actors {
            if actor_name == name {
                actor.visible = visible;
                break;
            }
        }
    }

    fn set_actor_edges(&mut self, name: &str, draw_edges: bool, boundary_only: bool) {
        for (actor_name, actor) in &mut self.actors {
            if actor_name == name {
                actor.set_edge_mode(draw_edges, boundary_only);
                break;
            }
        }
    }

    fn remove_mesh(&mut self, name: &str) {
        self.actors.retain(|(n, _)| n != name);
    }

    fn clear_meshes(&mut self) {
        self.actors.clear();
    }

    fn add_actor(&mut self, actor: &MeshActor) {
        let id = actor.id.to_string();
        // Already in GPU cache — just make visible
        if let Some((_, cached)) = self.actors.iter_mut().find(|(n, _)| n == &id) {
            cached.visible = true;
            return;
        }
        // Not cached — upload vertex data to GPU
        let no_edges = self.create_mesh_data(&actor.fill, &actor.mesh_lines, &[]);
        let all_edges = self.create_mesh_data(&actor.fill, &actor.mesh_lines, &actor.all_poly_edges);
        let boundary_edges = self.create_mesh_data(&actor.fill, &actor.mesh_lines, &actor.boundary_poly_edges);
        let mut cached = CachedActor {
            no_edges,
            all_edges,
            boundary_edges,
            texture: actor.texture.as_ref().and_then(|t| self.create_texture_resources(t)),
            current_mode: EdgeMode::NoEdges,
            visible: true,
        };
        cached.set_edge_mode(actor.draw_edges, actor.boundary_only);
        self.actors.push((id, cached));
    }

    fn remove_actor(&mut self, actor: &MeshActor) {
        let id = actor.id.to_string();
        if let Some((_, cached)) = self.actors.iter_mut().find(|(n, _)| n == &id) {
            cached.visible = false;
        }
    }

    fn set_mesh(&mut self, mesh: &Mesh) {
        // Backward compatibility: clear all and add single default mesh
        self.clear_meshes();
        self.add_mesh("default".to_string(), mesh, None, None);
    }

    fn render(&mut self) -> PyResult<()> {
        let frame = match self.surface.get_current_texture() {
            Ok(frame) => frame,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                self.surface.configure(&self.device, &self.config);
                return Ok(());
            }
            Err(wgpu::SurfaceError::OutOfMemory) => {
                return Err(PyRuntimeError::new_err("wgpu surface out of memory"));
            }
            Err(wgpu::SurfaceError::Timeout) => {
                return Ok(());
            }
        };

        let view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        let mut encoder =
            self.device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("openglider.wgpu.encoder"),
                });

        {
            let mut render_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("openglider.wgpu.pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: 0.12,
                            g: 0.16,
                            b: 0.2,
                            a: 1.0,
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth.view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(0),
                        store: wgpu::StoreOp::Store,
                    }),
                }),
                occlusion_query_set: None,
                timestamp_writes: None,
            });

            render_pass.set_bind_group(0, &self.uniform_bind_group, &[]);

            // Pass 1: fills — write depth + stencil(actor_index+1)
            render_pass.set_pipeline(&self.fill_pipeline);
            for (i, (_, actor)) in self.actors.iter().enumerate() {
                if !actor.visible { continue; }
                let stencil_id = ((i % 255) + 1) as u32;
                render_pass.set_stencil_reference(stencil_id);
                let texture_bind_group = actor
                    .texture
                    .as_ref()
                    .map(|texture| &texture.bind_group)
                    .unwrap_or(&self.default_texture_bind_group);
                render_pass.set_bind_group(1, texture_bind_group, &[]);
                let d = actor.get_data();
                if d.fill_vertex_count > 0 {
                    render_pass.set_vertex_buffer(0, d.fill_vertex_buffer.slice(..));
                    render_pass.draw(0..d.fill_vertex_count, 0..1);
                }
            }

            // Pass 2: mesh lines (object.lines) — depth-tested only, no stencil
            render_pass.set_pipeline(&self.mesh_line_pipeline);
            for (_, actor) in &self.actors {
                if !actor.visible { continue; }
                render_pass.set_bind_group(1, &self.default_texture_bind_group, &[]);
                let d = actor.get_data();
                if d.mesh_line_vertex_count > 0 {
                    render_pass.set_vertex_buffer(0, d.mesh_line_vertex_buffer.slice(..));
                    render_pass.draw(0..d.mesh_line_vertex_count, 0..1);
                }
            }

            // Pass 3: polygon edges — only where stencil == this actor's ID
            render_pass.set_pipeline(&self.polygon_edge_pipeline);
            for (i, (_, actor)) in self.actors.iter().enumerate() {
                if !actor.visible { continue; }
                let stencil_id = ((i % 255) + 1) as u32;
                render_pass.set_stencil_reference(stencil_id);
                render_pass.set_bind_group(1, &self.default_texture_bind_group, &[]);
                let d = actor.get_data();
                if d.poly_edge_vertex_count > 0 {
                    render_pass.set_vertex_buffer(0, d.poly_edge_vertex_buffer.slice(..));
                    render_pass.draw(0..d.poly_edge_vertex_count, 0..1);
                }
            }
        }

        self.queue.submit(Some(encoder.finish()));
        frame.present();
        Ok(())
    }
}

#[pyclass(module = "openglider.rs.wgpu", unsendable)]
pub struct NativeWgpuRenderer {
    state: Option<RendererState>,
}

#[pymethods]
impl NativeWgpuRenderer {
    #[new]
    #[pyo3(signature = (platform, window_id, width, height, display_id = None))]
    fn new(platform: &str, window_id: u64, width: u32, height: u32, display_id: Option<u64>) -> PyResult<Self> {
        if window_id == 0 {
            return Err(PyValueError::new_err("window_id must be non-zero"));
        }

        let state = RendererState::new(platform, window_id, width, height, display_id)?;
        Ok(Self { state: Some(state) })
    }

    fn resize(&mut self, width: u32, height: u32) {
        if let Some(state) = self.state.as_mut() {
            state.resize(width, height);
        }
    }

    fn set_mesh(&mut self, mesh: PyRef<'_, Mesh>) {
        if let Some(state) = self.state.as_mut() {
            state.set_mesh(&mesh);
        }
    }

    #[pyo3(signature = (yaw, pitch, distance, target_x, target_y, target_z))]
    fn set_camera(
        &mut self,
        yaw: f32,
        pitch: f32,
        distance: f32,
        target_x: f32,
        target_y: f32,
        target_z: f32,
    ) {
        if let Some(state) = self.state.as_mut() {
            state.camera = CameraState {
                yaw,
                pitch,
                distance,
                target: [target_x, target_y, target_z],
            };
            state.update_camera();
        }
    }

    fn render(&mut self) -> PyResult<()> {
        if let Some(state) = self.state.as_mut() {
            state.render()
        } else {
            Ok(())
        }
    }

    fn set_projection(&mut self, mode: &str) -> PyResult<()> {
        if let Some(state) = self.state.as_mut() {
            state.set_projection(mode)?;
        }
        Ok(())
    }

    fn set_color_bounds(&mut self, min_val: f32, max_val: f32) {
        if let Some(state) = self.state.as_mut() {
            state.set_color_bounds(min_val, max_val);
        }
    }

    fn set_draw_edges(&mut self, enabled: bool) {
        if let Some(state) = self.state.as_mut() {
            state.draw_edges = enabled;
        }
    }

    fn set_boundary_only(&mut self, enabled: bool) {
        if let Some(state) = self.state.as_mut() {
            state.boundary_only = enabled;
        }
    }

    #[pyo3(signature = (name, mesh, draw_edges=None, boundary_only=None))]
    fn add_mesh(&mut self, name: String, mesh: PyRef<'_, Mesh>, draw_edges: Option<bool>, boundary_only: Option<bool>) {
        if let Some(state) = self.state.as_mut() {
            state.add_mesh(name, &mesh, draw_edges, boundary_only);
        }
    }

    fn remove_mesh(&mut self, name: String) {
        if let Some(state) = self.state.as_mut() {
            state.remove_mesh(&name);
        }
    }

    fn clear_meshes(&mut self) {
        if let Some(state) = self.state.as_mut() {
            state.clear_meshes();
        }
    }

    fn add_actor(&mut self, actor: &MeshActor) {
        if let Some(state) = self.state.as_mut() {
            state.add_actor(actor);
        }
    }

    fn remove_actor(&mut self, actor: &MeshActor) {
        if let Some(state) = self.state.as_mut() {
            state.remove_actor(actor);
        }
    }

    fn set_actor_visibility(&mut self, name: String, visible: bool) {
        if let Some(state) = self.state.as_mut() {
            state.set_actor_visibility(&name, visible);
        }
    }

    fn set_actor_edges(&mut self, name: String, draw_edges: bool, boundary_only: bool) {
        if let Some(state) = self.state.as_mut() {
            state.set_actor_edges(&name, draw_edges, boundary_only);
        }
    }

    fn close(&mut self) {
        self.state = None;
    }
}

impl Drop for NativeWgpuRenderer {
    fn drop(&mut self) {
        self.state = None;
    }
}

#[pymodule(submodule, name = "wgpu")]
pub(crate) mod wgpu_mod {
    #[pymodule_export]
    use super::NativeWgpuRenderer;
    #[pymodule_export]
    use super::MeshActor;
}
