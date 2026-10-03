# OpenGlider

This is the AIRG version of OpenGlider.

## Main differences to legacy OpenGlider:

- without the freecad gui & dependencies
- excessive use of Pydantic Models for Physical objects (ribs, cells, panels, etc)
- added a custom qt-gui with compare functionality & auto-reload but only limited editing features.
- reduced the use of numpy and use rust internal module instead

## Try It


Clone the git-repo first:
```bash
git clone https://github.com/airgproducts/openglider
```

### Install with pip

```bash
cd openglider
pip install -e .
```


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
