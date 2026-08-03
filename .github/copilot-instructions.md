# Copilot Instructions for OpenGlider

## Environment
- Use the project virtual environment at `../venv` (relative to this repository root).
- Activate it before running Python tooling:
  - `source ../venv/bin/activate`
- Prefer this interpreter for tests, scripts, and packaging commands.
- For all local install/build validation steps in this repo, always use:
  - `uv pip install -e .`
- Do not use `pip install -e .` directly in this repository.

## Core Repository Structure
- `openglider/`: main Python package.
- `tests/`: Python tests.
- `scripts/`: helper scripts for dependency fetches, stub generation, and packaging.
- `docs/`: project documentation.

## Native Packages

### Rust package (PyO3)
- Rust crate metadata is in `Cargo.toml`.
- Crate name: `openglider-rs`.
- PyO3 extension target: `openglider.rs` (configured in `pyproject.toml`).
- Main Rust sources are in `rust/` (`lib.rs`, `mesh.rs`, `plane.rs`, `spline.rs`, ...).

### C++ package (pybind11)
- C++ extension target: `openglider.xfoil` (configured in `setup.py`).
- C++ sources are in `src_cpp/` (`pybind.cpp`, `solver.cpp`, `xfoil.cpp`, headers).
- Build dependency fetch runs via `scripts/fetch_cpp_deps.py` from `setup.py`.

## Build Notes for AI Agents
- Changes touching `rust/` likely impact the `openglider.rs` extension build.
- Changes touching `src_cpp/` likely impact the `openglider.xfoil` extension build.
- When both Python and native code change, validate with an editable install from repo root:
  - `uv pip install -e .`