# Weld Map Understanding And Weld Traceability Assistant

本项目面向单张管道等轴图 / weld map 的本地化解析与焊口追溯，目标是把图纸中的焊口、BOM、图号等信息结构化，并形成可落库、可复核、可更新进度、可导出的焊口追溯闭环。

当前仓库已经完成一版可运行骨架：

- Phase 1：M1 `Input/Ingestion`、M2 `Preprocessing`、M3 `Layout & ROI Planner`、M4 `OCR Extraction` 适配层、M6 `Fusion & Parsing`
- Phase 2：M7 `SQLite` 数据模型、M9 导出、M10 最简 `Streamlit` UI
- Phase 3/4 预留接口：M5 `VLM Understanding`、自动布局增强、`review_queue`、进度与照片事件服务

## 项目目标

围绕一张真实工程图，实现以下闭环：

1. 读懂图纸：输出 `StructuredDrawing.json`
2. 建账落库：生成 drawing / weld / bom / review_queue 等实体
3. 跟踪焊口：支持状态更新、照片绑定、检验状态
4. 导出集成：生成 JSON / CSV，为 ERP 或后续系统对接留接口

设计约束来自前期 Spike 结论：

- `OCR 主，VLM 辅`
- `ROI + 多次短调用`，不做整图一次性 VLM 推理
- `冲突不硬判`，进入 `needs_review`
- `全链路 provenance`，关键字段保留来源信息

## 模块划分

系统按 10 个模块解耦：

- M1 `Input / Ingestion`
- M2 `Preprocessing`
- M3 `Layout & ROI Planner`
- M4 `OCR Extraction`
- M5 `VLM Understanding`
- M6 `Fusion & Parsing`
- M7 `Traceability Data Model`
- M8 `Progress & Photo Linking`
- M9 `Export / Integration`
- M10 `UI / Demo`

模块之间只通过契约对象交互：

- `InputDocument`
- `PreprocessedDocument`
- `LayoutPlan`
- `OCRResult`
- `VLMResult`
- `StructuredDrawing`
- `DB entities`

更完整的模块说明、阶段规划和验收目标见：

- [docs/module-spec-summary.md](docs/module-spec-summary.md)

## 当前实现状态

已落地内容：

- 项目结构、配置系统、Pydantic 契约模型
- 手工 ROI 模式和自动布局 fallback 入口
- OCR 适配器接口与 `PaddleOCR` 接入点
- 简化版 Fusion：drawing / BOM / weld 的基础融合与 `needs_review`
- SQLite schema、导入仓储、导出服务
- 焊口状态 / 检验 / 照片绑定服务骨架
- CLI 和最简 Streamlit 界面
- JSON Schema 生成与基础单元测试

当前默认降级行为：

- `vlm.enabled=false`
- 若本机未安装 `PaddleOCR`，流水线会退到 `NullOCREngine`，保证系统骨架可运行但不会提取真实 OCR 结果

## 仓库结构

```text
.
├─ config/
│  ├─ config.yaml
│  └─ roi_template_default.json
├─ docs/
├─ samples/
│  └─ real/
├─ schemas/
├─ src/weld_assistant/
├─ tests/
├─ app.py
└─ weld_cli.py
```

## 首个真实样本

当前仓库内已纳入一张真实图纸样本：

- [samples/real/1.jpg](samples/real/1.jpg)

它来自用户当前提供的真实图纸，是后续手工 ROI、OCR 调试和真实链路验证的第一张基线样本。

## 快速开始

### 1. 安装依赖

基础依赖：

```powershell
python -m pip install -r requirements.txt
```

UI 依赖：

```powershell
python -m pip install streamlit
```

OCR 依赖：

```powershell
python -m pip install paddleocr
```

### 2. 生成 schema

```powershell
python weld_cli.py write-schema --output schemas\structured_drawing.schema.json
```

### 3. 初始化数据库

```powershell
python weld_cli.py init-db
```

### 4. 跑一张图纸

```powershell
python weld_cli.py parse --input samples\real\1.jpg --persist --overwrite --output data\final\sample_output.json
```

### 5. 启动 UI

```powershell
streamlit run app.py
```

## 配置说明

主配置在 [config/config.yaml](config/config.yaml)，关键项包括：

- `layout.mode`: `manual | auto`
- `layout.weld_id_pattern`: 焊口编号正则
- `ocr.engine`: 当前默认 `paddleocr`
- `vlm.enabled`: 是否启用 VLM
- `database.path`: SQLite 路径
- `export.output_dir`: 导出目录

## 阶段路线图

- Phase 1：解析骨架跑通，先建立 OCR 基线
- Phase 2：落库、展示、导出形成最小可演示产品
- Phase 3：接入自动布局与 VLM 语义增强
- Phase 4：补齐复核队列、状态管理、照片证据闭环
- Phase 5：跑批评估、误差回溯和精度硬化

## 测试

```powershell
$env:PYTHONPATH='src'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
```

## 下一步

围绕 `samples/real/1.jpg`，下一轮重点会是：

- 安装并打通真实 `PaddleOCR`
- 为真实样本建立更贴合的 ROI 模板
- 跑出第一版真实 `StructuredDrawing`
- 用真实图纸推动 Phase 1 从“骨架可跑”进入“结果可用”

