# 公开动作快照 public-motion-v1（2026-10-27）

用户明确授权：**公开 T08，后期 83 条也公开**。本目录只固定公开以下资产：

| 类别 | 数量 | 内容 |
| --- | ---: | --- |
| T08 参考 | 14 | 固定 T08 tokenizer 的预计算编码／解码参考动作 |
| T08 候选 | 3 | 同一权重生成的候选重建，仍保留候选标记 |
| SMPL-X 拟合 | 83 | 已获动作质量人工批准的后期实验拟合动作，不是 T08 解码输出 |

合计 **100 个动作片段**，不是 100 个独立词条，也不是 100 句已通过语言学认证的中国手语。每条姿态、来源摘要和既有批准记录原样保留。

## 使用

在项目 signbridge 子目录执行 `npm ci && npm run build:motion`。解压发布 ZIP 后，在 Chrome 的 `chrome://extensions` 开启开发者模式，加载包含 manifest.json 的文件夹，停用旧副本。插件弹窗打开演示工作台。也可双击 `start-demo.command`，或执行 `python3 start-demo.py`，使用终端打印的网址；不要直接双击 demo/index.html。

验证 T08 可输入“工作忙吗？”，验证拟合动作可输入“认识你很高兴”。在“参考与实验动作”模式看来源标签和 token：T08 显示 token，SMPL-X 拟合明确无 T08 token。内置词库仍是独立来源，未匹配文字可能没有可用动作。

## 授权、限制与隐私

- 公开的是可读取和提取的动作 JSON、索引、来源摘要与批准记录，不是加密保护库。项目自有代码继续使用根目录 MIT 许可。
- 公开分发不重新授权第三方模型、SMPL-X／SMPLer-X／SOKE 工具、源视频或其衍生权利；使用者须独立遵循相关来源条款，不能将根目录 MIT 自动扩展为所有第三方资产的无限制许可。
- 不含源视频、研究图片、训练权重、CE-CSL 数据、后续未授权动作。未来新库默认不公开，不能自动扫描 local-data。
- 83 条仅批准动作质量，不等于已确认中文含义、词界、镜像、惯用手、手语者、数据划分或中国手语正确性；三条 T08 候选仍是候选。
- training_ready、model_training_ready、deployment_ready 均保持 false。能播放不是识别模型或通用文字到手语生成能力。
- 旧拟合缺失的运行摘要及原推理 JPEG 哈希等 provenance_limitations 原样保留，不补造证据。

manifest.json 绑定 88 个输入文件的 SHA-256，构建脚本另锁定清单 SHA-256；修改任何动作、批准、清单都须重新审查，不可沿用旧批准。派生 ZIP 包含 PUBLIC-MOTION.json、MOTION-LIBRARY.md、LICENSE.txt 和 BUILD.json 的逐文件哈希。
