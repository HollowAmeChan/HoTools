# Bundled Python runtimes

HoTools ships separate dependency trees for Blender's embedded Python ABI:

- `py311`: Blender 4.5 / Python 3.11, including Pillow 11.3.0, CFFI 2.0.0,
  pycparser 3.0, and PyOIDN 2.4.0.2.
- `py313`: Blender 5.2 / Python 3.13, including Pillow 12.1.1, CFFI 2.0.0,
  pycparser 3.0, and PyOIDN 2.5.0.1.

PyOIDN 2.4.0.2 can import under Blender 5.2 but fails when it creates an OIDN
device because its bundled runtime conflicts with Blender 5.2's loaded TBB DLL.
Keep the Python 3.13 tree on PyOIDN 2.5.0.1 or later unless the replacement is
tested by creating and committing a `pyoidn.Device` inside Blender itself.

Release ZIPs are built with `tools/build_release_zip.py`; each ZIP must contain
only one of these ABI directories.
