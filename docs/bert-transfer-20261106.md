# 冻结中文BERT迁移对照 · 2026-11-06

本轮已完成预训练权重核验、独立环境、一次GPU训练、归档取回和CPU逐句复算。冻结BERT＋投影/字符Gloss解码器在既有G开发组有小幅改善，**不是独立泛化成绩，模型仍不具备可靠自动翻译能力，不接入Demo。** H和正式test未读取或上传。

## 模型、环境和数据

候选为官方 `google-bert/bert-base-chinese`，固定revision `8f23c25b06e129b6c986331a13d8d025a92cf0ea`。下载的模型元数据许可标记为apache-2.0；原模型卡、元数据、文件树和来源摘要均保留。safetensors文件SHA256 `3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3` 与上游LFS摘要一致，411,553,788字节。只读取本地固定权重，关闭网络加载，不运行remote code，不向模型站点发送项目文本。

原环境没有Transformers。本轮在独立venv安装固定Transformers4.40.2、hub0.23.5、tokenizers0.19.1和regex2024.5.15，通过该新环境的`.pth`复用旧Torch，不修改旧环境。原Torch二进制/源码摘要和旧hub2.2.0版本在结束后核对不变。单纯system-site-packages没有自动继承另一个venv的Torch，初次前向因此失败；追加新环境内的复用路径后真实加载通过，没有重复安装或升级Torch。

所有BERT参数冻结，encoder始终eval/no-grad；768维输出经可训练Linear＋LayerNorm投影到128维，再使用既有2层128维字符Gloss解码器。总参数102,708,867，可训练1,031,811；与之前随机字符编码器的容量、分词和冻结策略不同，不能把差异全部归因为预训练本身。

同一4368条train、489条G选型；目标1795项字符/边界词表仅取train，编号和原始Gloss身份保留。BERT输入分词在G组无UNK，train出现12个UNK token；输入最长28/27 token，不截断。H之前已用于旧实验，本轮完全排除，G此前被开发使用，仍非独立测试。

## 训练与结果

RTX4090D / Torch2.2.2+cu118 / CUDA11.8。seed20261105、batch64、AdamW lr0.0002、label smoothing0.05、30轮上限、patience6；按G原始还原Gloss GER选型。实际15轮、1035步，选第9轮，退出码0。完整历史和实际启动/结束时间在运行报告及`launch.json`、`completion.json`。

| G开发指标             | 随机字符基线 | 本轮冻结BERT |
| --------------------- | -----------: | -----------: |
| 总Gloss错误率，489句  |       76.79% |       76.16% |
| 替换                  |          892 |          913 |
| 删除                  |          906 |          864 |
| 插入                  |           22 |           28 |
| 人物切片错误率，404句 |       73.11% |       72.06% |
| 否定切片错误率，29句  |       77.40% |       77.40% |
| 整句完全匹配          |        0/489 |        0/489 |

总编辑错误1820→1805，少15次，改善约0.63个百分点。漏词减少、错词和多词增加；否定切片只是原始Gloss整句编辑率持平，不证明否定作用范围或具体否定词正确。G开发门槛（总体/人物/否定不退化、无非法输出）均通过，模型最终489条输出合法、非空且EOS完整；这些条件不等于部署许可。

平均输出3.14个Gloss，参考4.85个；固定编辑路径上未见但可拼写标签203次仍无正确匹配，含未知字符标签43次同样无匹配。已见标签出现2124次，匹配593次。编辑路径可能存在并列解，这些只是诊断计数，不能当独立词级准确率。仍然没有整句正确结果，不把这次研究称作可用手语翻译，更不改动动作播放库。

## 验证与实现修正

预训练文件原带MLM/NSP任务头和池化头，加载时仅允许忽略明确的`cls.*`和两项池化参数；任何缺失/维度错误/其他加载错误拒绝，编码器参数完整。独立审查发现递归复制输入可能带入未验证额外文件，已改为只复制摘要绑定的train/G/report三文件并重封清单；含额外H文件和test符号链接的哨兵回归确认不会读取或复制。审查修正发生在训练前，旧v1包不作为执行输入。

本机确认：模型/输入/代码/基线绑定一致，全部适配层及恢复optimizer张量有限、形状dtype正确；选型、步数和早停复算一致。重新加载官方冻结权重与小checkpoint，489条CPU原始输出与GPU逐条一致，指标完全复现；encoder原始、训练后、CPU重放后hash一致。CPU验证零optimizer更新，旧环境和旧模型保持原样。

`npm run verify`退出0：323项JavaScript通过，Python768项、28项跳过、其余通过，构建/ESLint/格式通过；含Torch的迁移专项7项通过，另有真实权重前向/梯度及489条CPU重放。已本地提交、不推送GitHub。human_approved/training_ready/model_training_ready/deployment_ready保持false；Demo、T08、83条历史动作、源视频和待审素材未变。

## 本地交付

目录：`/Users/mac/Desktop/手语/SignBridge-中文迁移实验-20261106-98r014yn/`。

- `prepared-v2/` / `gpu-input-v2/`：实际执行计划、输入和源码，不含H/test。
- `pretrained/`、`model-metadata.json`、`model-tree.json`、`model-download.json`：固定官方权重、许可标记及源摘要。
- `gpu-evidence-v1.tar.gz`：41个文件成员，SHA256 `8a64587d7a35bcd46636ec25f452890c21c014954faf2f80f6887f8f2bb6d269`；内外及解压哈希逐项通过，包含冻结权重、代码、运行/安装日志、依赖版本/模块hash、小checkpoint和完整训练历史。venv实体未归档，按记录可重建。
- `verified-v1/evidence/results/transfer-v1/`：选定适配checkpoint，SHA256 `88c6e539ea277060a846a9ba6a1ff9c2f8a2b27d19a22bb86002eaecca0fb5a6`；恢复optimizer另存。该小文件不能脱离固定编码器资产单独使用。
- `independent-validation.json` / `learning-curve.csv`：完整复算与逐轮结果。

结论：冻结中文预训练编码器的迁移方案已实际完成，改善有限且无整句匹配，暂时仅保留为研究证据，不晋升为展示翻译模型。
