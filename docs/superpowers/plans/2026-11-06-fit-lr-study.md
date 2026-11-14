# 全量拟合诊断与学习率单因素对照

目标：按用户确认的顺序，先测旧BERT迁移模型在全部4368条train及489条G上的teacher-forcing和自由生成，再固定一个GPU优化因素。不是继续追逐G分数的无限搜索，不读H/test，不接Demo。

本机CPU诊断：原始权重不改，分别输出teacher-forcing token/整句准确率与NLL、自由生成原始Gloss GER/整句/错词漏词多词/非法边界，人物/否定/未见字符/稀有词切片，全部逐句绑定ID和参考。CPU零optimizer更新，按run内摘要验证encoder、适配checkpoint、prepared输入。

单因素：如果完整train仍拟合差，执行学习率0.001对照，基线0.0002。复用同一官方冻结BERT、投影/字符decoder结构、同一随机初始化seed、数据/词表/次序、AdamWweight_decay0.01、batch64、label_smoothing0.05及梯度clip1。精确匹配旧run实际执行15轮/1035步预算，固定此预算而不延长；按15轮内最低G原Gloss GER选best，同分最早。旧run在第15轮触发早停；新run没有中途早停，两个run实际观察和更新预算相同，规则差异必须披露。不从旧best续训，不改标签、负采样或encoder。

所有模型源码与原预训练权重保持绑定；小checkpoint只含可训练部分。输入包不含H或test。不事先承诺改善；采用至少要求G总GER、人物/否定GER、删除数及格式不退化。G开发已用多次，无新独立泛化；即使通过不自动晋升Demo。

- [x] 先失败测试：teacher-forcing PAD/EOS、pred/reference/ID校验、切片、只改变学习率和固定步数、CUDA不可用不回退。
- [x] 本机全4368+489诊断，并据此冻结0.001、15轮一次run。
- [x] 独立审查、GPU/进程/摘要/初始trainable hash预检、唯一独立新目录训练。
- [x] 取回归档并复算G全部预测与train拟合，冻结BERT未变，旧权重未改。
- [x] build/lint/format/全量测试、文档、桌面文件和本地提交，不推送。

结果：train自由GER75.61%→55.64%、完整匹配17→319/4368；G GER76.16%→71.90%，完整匹配0→4/489，人物/否定/删除指标改善但1条G重复至上限无EOS，格式门槛未通过，不晋升Demo。全部train/G CPU逐条重放一致；详见 `docs/fit-lr-study-20261106.md`。
