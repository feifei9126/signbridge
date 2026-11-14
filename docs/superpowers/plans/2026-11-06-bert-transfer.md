# 中文BERT冻结编码器迁移实验

用户已授权下一步。先核实模型、许可、隔离环境，再只运行一次GPU研究对照，不自动接入Demo。

候选固定：google-bert/bert-base-chinese，revision 8f23c25b06e129b6c986331a13d8d025a92cf0ea，模型卡license apache-2.0，safetensors上游LFS SHA256 3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3。不加载远程代码；使用固定版本Transformers4.40.2，独立venv继承旧torch但不修改旧环境。没有向模型站点发送语料。

设计：冻结全部BERT参数，encoder始终eval，768维输出经可训练投影和LayerNorm转128维；使用相同2层128维字符Gloss解码器，保留原标签和gloss_end边界。encoder tokenizer取官方词表，目标字符词表仍仅由4368条train构建。batch64、AdamW lr0.0002、label smoothing0.05、seed20261105、最多30轮、patience6，G组489条按原始Gloss GER选型。基线为已核验的实际字符实验（76.79%），不是整词实验。

变量边界：预训练语言表征、输入分词、冻结策略、投影层及参数量发生变化；这不是等参数纯预训练因果消融。G已被开发使用，不能宣称独立泛化。H及正式test不读取、不上传，不用小样本记忆成绩替代翻译验证。

- [x] 先失败测试：冻结encoder/eval、投影decoder梯度、原目标及词界保持、tokenizer不截断、attention mask、完整checkpoint绑定。
- [x] 本机只前向/反向契约检查且零optimizer更新，真实权重加载和许可/源摘要封存。
- [x] 独立审查与GPU预检；全新目录运行唯一实验，记录实际命令/PID/退出状态；不改运行中脚本。
- [x] 训练后取回、全部哈希及冻参一致性，复算原始Gloss GER和人物/否定切片、完整489条CPU推理复现。
- [x] 完整项目验证、文档、桌面产物、本地提交；所有批准/部署/训练就绪仍false。

结果：15轮、选9轮、1035步；G GER76.79%→76.16%，人物73.11%→72.06%，否定77.40%持平，0/489整句匹配。开发门槛通过但不晋升Demo。见 `docs/bert-transfer-20261106.md`。
