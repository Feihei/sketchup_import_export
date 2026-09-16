# AGENTS.md — SketchUp Importer (pyslapi)

## 项目概述

这是 **pyslapi**：官方 SketchUp SDK 的 Python 绑定，以及基于它的 **Blender SketchUp 导入插件**（.skp → Blender 场景）。当前 Blender 插件版本为 0.27.0（见 `sketchup_importer/__init__.py` 的 `bl_info`），Python 包版本 0.24.0（`pyproject.toml`）。

- 兼容：Blender 4.x、Python 3.11、SketchUp 文件至 2025.1
- 平台：Windows / macOS（**不支持 Linux** — SketchUp SDK 不提供 Linux 库）
- 许可：Blender 插件部分为 GPL（见 `sketchup_importer/__init__.py` 头部）

## 目录结构

| 路径 | 说明 |
|---|---|
| `sketchup.pyx` | Cython 源码：官方 SketchUp C API 的 Python 绑定（核心扩展模块 `sketchup`） |
| `sketchup_importer/` | Blender 插件包。`__init__.py`（~1100 行）含 `bl_info`、Operator、Import/Export 逻辑；`SKPutil/` 为工具函数 |
| `slapi/` | Python 层的 SketchUp API 封装：`model/*.pxd` 按 SketchUp 实体类型（face、edge、component 等）划分声明 |
| `slapi_rs/` | 实验性 Rust 绑定（`error.rs`/`lib.rs`/`safe.rs`，`build.rs` + `wrapper.h` 走 bindgen），独立 workspace 成员，不参与 Blender 插件构建 |
| `setup.py` | Cython 扩展构建脚本（按平台区分链接参数：Windows `/Zp8` + x64 lib，macOS framework） |
| `pyproject.toml` | 包元数据 + **ruff 配置（line-length 120，select 见文件内注释）** |
| `编译.md` | Windows 构建步骤（中文） |
| `examples/`（slapi_rs 内） | Rust 使用示例 |

注意：`setup.py` 引用了 `headers/` 和 `binaries/sketchup/` 目录，它们来自 SketchUp SDK，**不在仓库中**，需自行下载 SDK（https://extensions.sketchup.com/sketchup-sdk）。

## 构建与验证

Windows（见 `编译.md`）：
1. 复制 `sdk/headers/SketchUpAPI` 到 Python 安装目录的 `include/` 下
2. 复制 `sdk/binaries/sketchup/x64` 下所有文件到 Python 的 `libs/` 下
3. `python setup.py build_ext --inplace`

macOS：按 README「Build Info」步骤，构建后需手动 `install_name_tool -change` 修复 rpath 并 `xattr -r -d com.apple.quarantine`。

Rust 部分（独立）：`cd slapi_rs && cargo build`（需设置 `SKETCHUP_SDK_PATH` 环境变量）。

验证 Python 代码风格：`ruff check`（配置在 `pyproject.toml`）。Cython 扩展必须链接真实 SDK 才能编译，纯语法检查可用 `cython sketchup.pyx`。

## 代码约定

- Python：ruff 强制 line-length 120；import 排序（isort）；遵循 pyupgrade/PyFlakes 规则
- Cython：`language_level=3`，C++ 编译（`language="c++"`）
- Blender API：插件基于 `bpy` / `bpy_extras.io_utils` / `mathutils`；修改导入逻辑时注意 **层级结构保持、同名实体区分、嵌套组件变换** 是历史上的三大坑（见 README v0.25 说明），改动需回归测试嵌套 group/component 场景
- 提交信息用简体中文，保留 Conventional Commit 类型；代码标识符用英文

## 常见任务入口

- 改导入行为（几何、材质、变换）→ `sketchup_importer/__init__.py`
- 改底层 API 绑定/新增 SU API 调用 → `sketchup.pyx`，声明放 `slapi/model/*.pxd`
- 改构建/平台问题 → `setup.py` + `编译.md`
- Rust 绑定 → `slapi_rs/src/`
