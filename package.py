"""
Blender 插件打包工具 —— 将源目录打包为可直接安装的 .zip 发布包。

用法:
    python package.py <source_dir> <zip_path>

示例:
    python package.py src dist/HoTools_v2.2.0.zip

Author: Lvoxx
"""

import os
import sys
import zipfile
from pathlib import Path



# ==== Config ====
EXCLUDE_PATTERNS = (".pyc", "__pycache__", ".gitignore", ".DS_Store", ".git", ".idea", ".vscode", "venv")
EXCLUDE_FOLDERS = [""]  # Folders to exclude, relative to the source directory (src/)
ADDON_NAME = "HoTools"  # Root folder name inside the zip


def create_zip(source_dir: str, zip_path: str):
    """打包 source_dir 下所有文件到 zip_path，自动过滤隐藏文件/目录和 EXCLUDE_PATTERNS。"""
    source_dir = Path(source_dir).absolute()
    zip_path = Path(zip_path).absolute()

    # Make sure the destination directory exists
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            # Calculate relative path from source directory
            rel_root = Path(root).relative_to(source_dir)
            
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") 
                and not any(p in d for p in EXCLUDE_PATTERNS)
                and not any(str(rel_root / d) == exclude_path or str(rel_root / d).startswith(exclude_path + "/") 
                           for exclude_path in EXCLUDE_FOLDERS)
            ]
            files = [
                f
                for f in files
                if not f.startswith(".") 
                and not any(p in f for p in EXCLUDE_PATTERNS)
                and not any(str(rel_root) == exclude_path or str(rel_root).startswith(exclude_path + "/") 
                           for exclude_path in EXCLUDE_FOLDERS)
            ]

            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(source_dir)
                arcname = Path(ADDON_NAME) / rel_path
                zf.write(file_path, arcname)

    print(f"[INFO] Created: {zip_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("ℹ️ Usage: python package.py <source_dir> <zip_path>")
        print(f"ℹ️ Example: python package.py src dist/LSPotato_v1.0.zip")
        sys.exit(1)

    src_dir = sys.argv[1]
    zip_file = sys.argv[2]

    if not os.path.isdir(src_dir):
        print(f"[ERROR] Source directory not found: {src_dir}")
        sys.exit(1)

    create_zip(src_dir, zip_file)
