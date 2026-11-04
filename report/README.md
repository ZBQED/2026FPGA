# 工程报告与原始记录

| 材料 | 路径 |
|---|---|
| 系统工程报告 Word | [design/system_report.docx](design/system_report.docx) |
| 系统工程报告 PDF | [design/system_report.pdf](design/system_report.pdf) |
| 固定输入完整视觉记录 | [source_complete_fixed/result.json](../board/outputs/source_complete_fixed/result.json) |
| TCN序列回放原始记录 | [installed_tcn/result.json](../board/outputs/installed_tcn/result.json) |
| 手部重建验证原始记录 | [rebuilt_hand/result.json](../board/outputs/rebuilt_hand/result.json) |

两份报告采用用户提供的修订版，原文件内容保持不变。三份JSON从先前提交包中原样恢复，SHA256与最快记录摘录引用的来源一致。

运行结果由`board/verification_summary.json`索引，其中`records`指向原有结果与摘录，`source_records`指向恢复的完整原始记录。构建与数值结果见`build/reports/`，新增材料的来源与交付摘要见`material_sources.json`。

已有Skill协作节选位于[技能提炼与纠错记录](../skill/pynq-evidence-audit/references/development_record.md)，保留原件。
