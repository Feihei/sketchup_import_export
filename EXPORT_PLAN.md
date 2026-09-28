# Export 功能实施计划（v1）

## 背景与决定

- `SceneExporter.save()` 目前是空壳（只打日志返回 FINISHED），export 需要从零实现
- `sketchup.pyx` 已有 `Model.save()`（`SUModelSaveToFile`）、`Face.create_simple`、`Entities.addFace` 等基础，写方向绑定大部分缺失
- 用户偏好：不喜欢 SketchUp 自由嵌套，采用 **Blender 扁平 object 语义映射 SketchUp**

## 核心设计决定

1. **层级语义（对应 importer 三大坑的简化）**：
   - 每个 Blender object → 一个 SketchUp group（单层，无嵌套）
   - 数学模型等价于 "Clear Parent (Keep Transform)" 后的状态：mesh 局部顶点 + object `matrix_world`
   - | Blender | SketchUp |
     |---|---|
     | mesh 局部顶点 | group/definition entities 坐标（÷0.0254 米→英寸） |
     | `matrix_world` | group transform / instance transform（直接拷矩阵，不做 TRS 分解） |
     | mesh data `users>1` | ComponentDefinition + 多个 ComponentInstance |
     | mesh data `users==1` | 独立 Group |
   - 烘焙在导出器内存中完成，不要求用户 clear parent，不修改用户文件
2. **单位换算**：SketchUp C API 内部坐标恒为英寸（与界面单位设置无关）；换算放 Cython 批量循环内，不放 Python 逐顶点调用
3. **数据通道**：Blender 侧 `foreach_get` 收集顶点到 numpy → `GeometryInput` 绑定签名用 `double[:, ::1]` typed memoryview 零拷贝接入；纯 Python 降级路径用 `array.array('d')` 供 Blender 外测试
4. **组件复用**：v1 就要（`users>1` 的 linked mesh → definition + instances）；含非均匀缩放混合旋转的实例暂不特殊处理（直接矩阵拷贝不失真）

## Phase 1：Cython 写方向绑定（sketchup.pyx）

1. `GeometryInput` 类：`SUGeometryInputCreate` / `AddVertices(double[:, ::1])`（循环内 ÷0.0254）/ `AddFace`（顶点索引 + loop）
2. `Entities.addGeometryInput()` → `SUEntitiesFill`
3. Material/Texture 写方向：`SUMaterialCreate` / `SetName` / `SetColor` / `SetColorizeType` / `SetOpacity` / `SUMaterialsAdd`；`SUTextureCreateFromFile`
4. Group 写方向：`SUGroupCreate` / `SUGroupSetTransform`（单层够用）
5. Component 写方向：`SUComponentDefinitionCreate` / `SetEntities` / `SUComponentInstancesAdd` / `SUComponentInstanceSetTransform`
6. 冒烟测试（Blender 外）：创建立方体 → save → `from_file` 读回断言 face 数

## Phase 2：SceneExporter（sketchup_import_export/__init__.py）

7. 几何收集：`evaluated_get(depsgraph)` 取 modifier 后网格 → `foreach_get` 顶点 → numpy → `@ matrix_world`（仅 `users==1` 路径需要世界坐标时）→ GeometryInput
8. object → SU group（transform = matrix_world 拷贝）；`users>1` mesh → ComponentDefinition（局部坐标）+ 每 object 一个 ComponentInstance
9. 材质导出：diffuse/alpha/贴图（image 存临时 PNG 再 `SUTextureCreateFromFile`）
10. `ExportSKP` UI：选项 property（选中物体 only、导出材质开关）；失败 `report({'ERROR'})` + 清理半成品文件
11. `Model.save()` 落盘

## Phase 3：验证与文档

12. 测试矩阵：立方体 / 多物体各 group / linked data ×4 实例 / 材质球；SketchUp 打开核对位置尺寸
13. README 标注 export 现状与限制

## 风险

- Component 路径的 transform 直接矩阵拷贝理论无损，但需实测 SketchUp 端显示
- 修改器依赖项（如 Cloth 模拟帧状态）导出结果随 depsgraph 状态浮动，v1 不处理
