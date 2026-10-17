Installation
============


To Install the python package, first you have to clone the repository:
  ```
  git clone https://github.com/hiaselhans/OpenGlider.git
  ```
Then it must be linked into python-packages Folder:
  ```
  python setup.py develop
  ```
Alternatively do a static install
  ```
  python2 setup.py install
  ```

## Development

### 1. Install UV

```bash
# Option 1: Using curl (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Option 2: Using pip
pip install uv

# Option 3: Using cargo (if you have Rust installed)
cargo install uv
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
uv venv

# Activate it
source .venv/bin/activate  # Linux/macOS
```


### 3. Install

Install in development mode:

```bash
uv pip install -e .
```

## PyO3 Stub Generation

This project uses PyO3's `experimental-inspect` feature to automatically generate `.pyi` type stub files for the Rust extension module.

### How It Works

1. **PyO3 Configuration**: The `Cargo.toml` includes the `experimental-inspect` feature which enables runtime introspection of PyO3 classes and functions.

2. **Build System**: The project uses `setuptools-rust` to build the PyO3 extension during installation.

3. **Stub Generation**: After building, the `.pyi` stub files are automatically generated using the introspection data.

### Building and Generating Stubs

#### Development Installation

To build the extension and generate stubs in editable mode:

```bash
pip install -e .
```

This will:
1. Compile the Rust extension using `setuptools-rust`
2. Generate `.pyi` stub files from the introspection data
3. Install the package in development mode

#### Manual Stub Generation

If you need to regenerate stubs after modifying the Rust code:

```bash
python scripts/generate_pyi_stubs.py
```

### Generated Files

The stub files are generated in `openglider/rs/`

### Type Checking

With the stubs in place, you can now use full type checking with mypy:

```bash
mypy openglider
```

### Troubleshooting

#### Stubs not generated
- Ensure the extension built successfully: `python -c "import openglider.rs; print(openglider.rs.version())"`
- Run the stub generation script manually: `python scripts/generate_pyi_stubs.py`

#### Import errors
- Rebuild the extension: `pip install -e . --force-reinstall --no-cache-dir`
- Check that all dependencies are installed: `pip install setuptools-rust pyo3`

#### Type checking issues
- Ensure `py.typed` marker exists in `openglider/py.typed`
- Check that mypy configuration in `pyproject.toml` is correct
- Verify stubs are in the correct locations

### Future Improvements

- Use `pyo3-inspect` CLI tool once it's stable
- Automate stub generation in CI/CD
- Generate more detailed stubs with type information
- Consider using `stubgen` from mypy for comparison

## Build Desktop Distributables

OpenGlider can be packaged as:

- Windows application folder (`OpenGlider/OpenGlider.exe`)
- macOS application bundle (`OpenGlider.app`)
- Linux AppImage (`OpenGlider-linux-x86_64.AppImage`)

The repository provides helper scripts in `scripts/` using PyInstaller.

### 1. Build Windows `.exe`

Run this on a Windows machine with Python installed:

```bash
./scripts/build_windows_exe.sh
```

Output:

- `dist/OpenGlider/OpenGlider.exe` (onedir build; distribute the whole `dist/OpenGlider` folder)

### 2. Build macOS `.app`

Run this on macOS:

```bash
./scripts/build_macos_app.sh
```

Output:

- `dist/OpenGlider.app`

### 3. Build Linux `.AppImage`

Run this on Linux:

```bash
./scripts/build_linux_appimage.sh
```

Output:

- `dist/OpenGlider-linux-x86_64.AppImage`

### Notes

- Cross-building is not supported here. Build on the target OS (Windows for `.exe`, macOS for `.app`, Linux for `.AppImage`).
- The scripts prefer `uv` when available. In CI they use `uv pip install --system`; locally they use the active venv, or create/use `.venv` automatically.
- The C++ `fmt` dependency is bootstrapped automatically by `setup.py` via `scripts/fetch_cpp_deps.py` into `openglider_xfoil/fmt` when missing.

### GitHub Actions (Manual)

Use the `target` dropdown in **Build Desktop Artifacts** to build only one artifact when needed.

Available targets:

- `all`
- `windows-exe`
- `macos-app-x64`
- `macos-app-arm64`
- `linux-appimage-x64`

Artifact names:

- `OpenGlider-windows-exe` (`dist/OpenGlider-windows.zip`)
- `OpenGlider-macos-app-x64` (`dist/OpenGlider-macos-app-x64.tar.gz`)
- `OpenGlider-macos-app-arm64` (`dist/OpenGlider-macos-app-arm64.tar.gz`)
- `OpenGlider-linux-appimage-x64` (`dist/OpenGlider-linux-x86_64.AppImage`)
