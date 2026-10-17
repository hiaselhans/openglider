# OpenGlider

This is the AIRG version of OpenGlider.

## Main differences to legacy OpenGlider:

- without the freecad gui & dependencies
- excessive use of Pydantic Models for Physical objects (ribs, cells, panels, etc)
- added a custom qt-gui with compare functionality & auto-reload but only limited editing features.
- reduced the use of numpy and use rust internal module instead

## Try It

### Prebuilt versions (easiest)

Compiled desktop builds (Windows, macOS, Linux) are available at
[hiaselhans.github.io/openglider](https://hiaselhans.github.io/openglider/).
No compiler or Python setup is required.

### Developer install (from source)

OpenGlider contains native extensions (Rust and C++), so building from source needs:

- Python >= 3.11
- [Rust toolchain](https://rustup.rs/) (`rustc` + `cargo`, edition 2021)
- A C++17 compiler:
  - Linux: `gcc`/`g++` (e.g. `sudo apt install build-essential`)
  - macOS: Xcode command line tools (`xcode-select --install`)
  - Windows: Visual Studio Build Tools ("Desktop development with C++")
- [uv](https://docs.astral.sh/uv/) (recommended)

Clone the git-repo and install in editable mode with `uv`:
```bash
git clone https://github.com/airgproducts/openglider
cd openglider

uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e ".[gui]"
```

The `gui` extra installs the Qt/VTK based desktop GUI (started with the `openglider` command).
For a headless/library-only install use `uv pip install -e .`.

See [INSTALL.md](./INSTALL.md) for details.


## Documentation

Every module inside openglider *should* have a README where the functionality is documented.  
Please have a look at the [base module](./openglider/README.md).

## Build Desktop Apps

Helper scripts are available to package OpenGlider with PyInstaller:

- Windows `.exe`: `./scripts/build_windows_exe.sh` (run on Windows)
- macOS `.app`: `./scripts/build_macos_app.sh` (run on macOS)
- Linux `.AppImage`: `./scripts/build_linux_appimage.sh` (run on Linux)

The scripts use `uv` when available and automatically fall back to `pip`.

See [INSTALL.md](./INSTALL.md) for details.

### Unittests and Visual Tests

To run all unittests, run this from the main directory:
```bash
./testall.py
```

Or use `-a` flag to also run visual tests
```bash
./testall.py -a
```

## Used Tech

OpenGlider is built on top of these technologies:

- **Python** ([link](http://docs.python.org/3/tutorial/))
- Pydantic
- **[VTK](https://www.vtk.org/)** - visual toolkit for 3d-output
- Qt - Gui toolkit
