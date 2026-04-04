# 模块设计摘要

本文档提炼自 `weld_module_spec_v1.1.docx`，用于仓库内长期保留的实现基线。它不是逐字转录，而是把真正影响代码结构和阶段推进的内容沉淀下来。

## 1. Spike 结论

前期对 `qwen3.5:0.8b` 的真实图纸实验得到四个关键结论：

- VLM 能识别图纸大致结构，但不适合直接抄录精确字段
- 焊口编号、BOM tag/qty/material 等字段不能交给 VLM 直接决定
- 小模型会出现 hallucination，必须有严格边界
- 先做 OCR 基线，再评估 VLM 的增量价值

由此锁定四条设计原则：

- `OCR 主，VLM 辅`
- `VLM 只做语义补全`
- `ROI + 多次短调用`
- `冲突进入复核队列，不硬判`

## 2. 模块职责

### M1 Input / Ingestion

- 接收原始图纸
- 生成 `document_id`
- 计算 `sha256`
- 管理原始文件目录和重复上传识别

输出：`InputDocument`

### M2 Preprocessing

- 生成 `clean` / `strong` 双版本图像
- 保留预处理日志
- 不修改原图

输出：`PreprocessedDocument`

### M3 Layout & ROI Planner

- 将整图切分为语义 ROI
- 包括 `roi_titleblock`、`roi_bom_table`、`roi_isometric`、`roi_weld_label`
- 初期优先支持 `manual` 模式，后续再增强 `auto`

输出：`LayoutPlan`

### M4 OCR Extraction

- `roi_bom_table` 走表格 OCR
- `titleblock` / `weld_label` 走 token OCR
- 焊口编号纠错仍然保留原始文本和置信度

输出：`OCRResult`

### M5 VLM Understanding

- 只做语义描述、ROI 分类辅助、候选消歧
- 不直接产出最终结构化主值

输出：`VLMResult`

### M6 Fusion & Parsing

- 按字段优先级合并 OCR 和 VLM
- 标准化 weld_id
- 处理 BOM 列对齐
- 生成 `needs_review`

输出：`StructuredDrawing`

### M7 Traceability Data Model

- 将 `StructuredDrawing` 落到 DB
- 维护 `drawing`、`weld`、`bom_item`、`review_queue`

### M8 Progress & Photo Linking

- 焊口状态更新
- 检验状态更新
- 照片绑定
- 全部走 append-only 事件日志

### M9 Export / Integration

- 导出 JSON 全量数据
- 导出 CSV 摘要数据
- 为 ERP 接口留替换点

### M10 UI / Demo

- 上传图纸
- 查看解析结果
- 查看复核队列
- 管理焊口状态和照片
- 下载导出文件

## 3. 数据流

```text
InputDocument
  -> PreprocessedDocument
  -> LayoutPlan
  -> OCRResult (+ VLMResult)
  -> StructuredDrawing
  -> DB entities
  -> UI / Export
```

模块不共享内部状态，只通过契约对象交互。

## 4. 分阶段交付

### Phase 1

- M1 + M2 + M3(manual) + M4 + M6(简化版)
- 目标：输出可校验 `StructuredDrawing.json`

### Phase 2

- M7 + M9 + M10(最简 UI)
- 目标：形成上传、展示、落库、导出的最小产品

### Phase 3

- M3(auto) + M5 + M6(完整版)
- 目标：自动布局和 VLM 语义增强接入主链路

### Phase 4

- M8 + review queue UI + 数据模型完善
- 目标：追溯闭环可演示

### Phase 5

- 跑批评估、精度优化、错误回溯

## 5. 验收指标

核心目标沿用原规格：

- `schema_pass_rate >= 95%`
- `weld_recall >= 90%`
- `weld_precision >= 95%`
- `bom_field_accuracy >= 85%`
- `drawing_field_accuracy >= 90%`

## 6. 当前代码中的对应关系

当前仓库已经把这套分层落到了如下代码位置：

- 契约对象：`src/weld_assistant/contracts.py`
- 模块实现：`src/weld_assistant/modules/`
- 服务层：`src/weld_assistant/services/`
- 数据层：`src/weld_assistant/db/`
- UI：`src/weld_assistant/app.py`
- CLI：`src/weld_assistant/cli.py`

这份摘要会随着实现推进继续更新，但四条 Spike 锁定原则不变。

