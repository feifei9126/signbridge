# CE-CSL格式参照数据库

2026-11-09用户要求以本机CE-CSL对照当前教程，格式保持一致，去重并保留CE-CSL没有的内容，建立新数据库。范围是原CE-CSL与2/100教程、既有基础片段及用户确认的“你”校准候选。本轮整理原片和来源标注，不训练网络、不把5988段录像伪称全部已重建三维骨骼，不擅自扩大到未授权原片；随后用户追加两个目录见下文。

## 来源与核验

- 原数据：`/Users/mac/Desktop/手语/CE-CSL/CE-CSL/`，五列`Number,Translator,Chinese Sentences,Gloss,Note`，原train/dev/test为4973/515/500，共5988条。
- 沿用2026-10-22导入解析器；逐文件重新计算5988个CE视频、62个教程文件SHA-256，实际约10.895GB按十进制计，6050个路径，0错误/0变更。教程62个物理文件对应48份唯一内容，14个重复别名保留映射。
- 573条教程课内义项与3859个来源Gloss精确文字对照：347条重合、226条没有相同标签；后者按标签＋类型去重为224项。原始括号、编号变体、语法/指拼/数字/名字/类标记分别保留。
- 原始视频SHA一致才复用旧容器元数据；没有全量逐帧重新解码CE视频或核准词级起止。CE-CSL是语料来源，不据此宣称所有示范通过国家通用手语标准认证。

## 去重与冲突

全库按完全相同标签去Gloss索引重复，全部来源出现位置保留。教程同词跨课的不同示范保留，不平均、不因中文相同而认定同一动作；word/phrase与CE同名时只关联文字，理论/指拼/数字等类型保留单独命名空间。

`train-03571`和`train-03572`录像SHA相同，但中文/Gloss分别为“暂时不要乱走”和“暂时还没别的计划”。这属于源标注冲突，全部保留来源并隔离，不猜测哪条正确。因此主集为5986段，train4971、dev515、test500；原三份CSV逐字节另存，可恢复原分布。没有发现可按“相同视频＋完全相同中文/Gloss/备注”折叠的重复样本。相同中文或Gloss而不同录像继续保留，不丢失不同人、场景和打法。

新库内相同视频字节共用一份复制内容；硬链接仅限新库内部，新文件与原数据inode不同，原始文件不删除、不改写。训练集合不混入dev/test或教程候选。原`Translator`保持数据集代码，不与教程人物身份相混，不宣称人物独立划分。

## 新数据库与CE格式

自包含数据库含视频副本、SQLite、JSONL、原始CSV、按同样五列导出的主集和可离线打开的检索页。词条/概念联合索引4101项：3859个原Gloss加242个单独保留的教程类型项；这不是4101个已核准单词或可播放动作。

- `ce-csl/label/{train,dev,test}.csv`与`ce-csl/video/<split>/<Translator>/<Number>.mp4`保持原路径结构和原五列。
- `candidates/label/candidates.csv`及`candidates/video/candidates/TUTORIAL/*.mp4`单独保留28段既有基础候选，合计3538帧。“你”使用排除下一词“好”的60帧保守修订；仍是助手词界候选，不改CE官方标注。`TUTORIAL`是来源家族标记，不是认定的真实译者身份。
- 573条教程全部保留来源、词义、讲解、教学时间范围、手部/非手部说明和未决状态；不虚构573条独立词级视频，不把教程整句中文强行写成已对齐Gloss。
- `tutorial/not-in-ce-csl.jsonl`收录224项精确标签缺项，`tutorial/ce-csl-comparison.jsonl`逐条保留573项映射，5条未决不升级。
- `database.sqlite`关联datasets、media、samples、terms、occurrences、lexical_evidence、reviews、motion_assets、duplicate_aliases、conflicts。`ce_train_only`只返回保留的原train，`retained_ce_samples`不含冲突。

## 用户确认与训练边界

用户原话：“我已看过，‘你’现在的动作是对的”（记录保留原中文引号）。确认绑定2026-11-09展示页、具体图片/视频及校准关键帧参数SHA，作为显示表达的人工确认。该确认不自动推广给所有CE“你”、所有73帧原生基线、精确词界、镜像/解剖手别、连续抖动/穿插或新派生版本。新库的单张校准参数有对应review关系，基础候选与其他词条仍未批量批准。

`training_ready/model_training_ready=false`，不接Demo，不改T08，不公开CE原片或新库，不推送GitHub。词义索引、实际视频和骨骼/动作质量是分别可核对的证据。

## 工程与复现

构建工具`signbridge/src/tools/sign-csl-reference-database.py`复用原CE解析器；`sign-csl-reference-review.py`生成无需服务的检索页。构建必须写新目录，源校验报告绑定输入路径/摘要，视频拷贝再次校验，候选逐片核对真实帧数/FPS及NPZ源PTS/帧编号，漏检保持NaN与mask。SQLite执行完整性与外键检查；旧数据库、旧失败快照和原始视频保留。

```sh
.venv-sign-data/bin/python signbridge/tests/sign-csl-reference-database.test.py -v
cd signbridge
npm run verify
```

最终交付位于桌面“手语”的新版本目录，主库约13GB，视频和元数据自包含。另提供较小的元数据ZIP用于检索/备份，其中不含视频，不能声称下载这个小包就能播放所有录像。文件清单SHA、CSV/SQLite/JSONL一致性和浏览器检索/视频播放由独立验证记录说明。

## 追加两批教材

用户随后要求`/Users/mac/Desktop/手语/1/`与`/Users/mac/Desktop/手语/2/shouyu/`同格式接入。重hash、stat稳定和ffprobe核验共44份独立原课（11+33），未与CE或2/100视频字节重复；总时长约6.61小时。复用并逐report字段/SHA确认旧255段字幕候选（239种原标签），新复制片段重新校验字节。

原课无完整Gloss标注的，五列格式的中文/Gloss留空，Note明确仅文件标题与未标注状态；候选单独additional-caption-candidates，caption_candidates独表，保持来源候选、名义时间、手别/镜像未核准与训练false。87种候选标签与CE重合、152种不在CE原标签、149种不在本库全部主索引；这不是149项新核准动作。保留44原课和255候选实际视频，不能仅凭字幕原文说已理解或三维重建。

最终桌面完整库`/Users/mac/Desktop/手语/SignBridge-中国手语参照数据库-20261109-v1/`，约12.93GB媒体内容，6315样本/参考记录、4101词条/概念索引、573审核教程义项，附加字幕候选不污染主词表或CE train/dev/test。

独立代码审查的候选ID路径逃逸、审批参数副本哈希、输入重验证覆盖、默认train词条、展示自包含和失败终态问题均添加针对性修复与回归；全量小型构建fixture证明恶意ID不能覆盖源参数、注入终检失败没有成功report。人审原HTML保留原字节作为证据，另`reviews/index.html`提供使用本地相对视频的可用审阅页，二者不混淆。
