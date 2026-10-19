const PRIVATE_ZH = {
  privateTitle: "SignBridge · 中国手语理解研究版",
  privateScope:
    "当前已训练：受限中文语义角色解析。训练标签为助手合成中文示例，尚未训练出中国手语翻译或视频识别能力。",
  privateEndpoint: "本机推理服务地址",
  privateToken: "本次服务的会话口令",
  privateTokenHelp:
    "口令由本机服务终端生成，仅在本页面内存中使用；重启服务后失效。",
  privateSentence: "输入一句中文（最多500字）",
  privateAnalyze: "解析意思",
  privateDisconnect: "清空会话",
  privateResult: "语义解析结果",
  privateWaiting: "启动本机服务并填写会话口令后可解析。",
  privateAnalyzing: "正在调用本机训练模型…",
  privateParsed: "已解析角色；尚需中国手语动作对齐与表达核验。",
  privateAbstained: "该句超出已训练范围或存在歧义；已停止解析，请保留原文。",
  privateMotionGap:
    "手语输出暂未启用：词级动作边界、空间指代和非手部表达仍需核对。这里不会用整句检索或手工词库播放代替理解。",
  privateProtectionScope:
    "此客户端不包含完整词库、动作数据或模型权重。页面展示的结果仍可被复制；已发出的旧版安装包无法撤回。",
  privateModel: "本次模型：{model}",
  privateDisconnected: "会话已清空。",
  privateEndpointInvalid: "请使用明确端口的 http://127.0.0.1 本机服务地址。",
  privateTokenInvalid: "请填写本次终端生成的完整会话口令。",
  privateTextInvalid: "请输入1至500字的中文。",
  privateUnauthorized: "口令无效或已失效，请使用当前服务终端的口令。",
  privateForbidden: "服务拒绝了来源；插件需在启动服务时加入其准确的扩展来源。",
  privateRateLimited: "请求过于频繁，请稍后重试。",
  privateBusy: "服务忙，请稍后重试。",
  privateRequestFailed: "推理请求失败，请检查本机服务。",
  privateResponseInvalid: "服务返回内容不符合当前模型接口。",
  privateConnectionFailed:
    "无法连接本机服务或请求已超时，请检查服务地址和运行状态。",
  privateRoles: {
    actor: "谁／施事",
    predicate: "动作／状态",
    patient: "对谁／受事",
    goal: "目标地点",
    time: "时间",
    negation: "否定",
    modal: "意愿／能力／必要性",
    question: "疑问",
    aspect: "体貌",
    politeness: "请求",
    degree: "程度",
  },
};
const PRIVATE_EN = {
  privateTitle: "SignBridge · CSL understanding research",
  privateScope:
    "Trained capability: bounded Chinese semantic roles, using assistant synthetic Chinese labels. CSL translation and video recognition are not trained.",
  privateEndpoint: "Local inference service",
  privateToken: "Session token",
  privateTokenHelp:
    "The local service prints a new token in its terminal. This page holds it in memory only; restart invalidates it.",
  privateSentence: "Chinese sentence (up to 500 characters)",
  privateAnalyze: "Analyze meaning",
  privateDisconnect: "Clear session",
  privateResult: "Semantic result",
  privateWaiting: "Start the local service and enter its session token.",
  privateAnalyzing: "Running the local trained model…",
  privateParsed:
    "Roles parsed; CSL motion alignment and realization still require review.",
  privateAbstained:
    "Unsupported or ambiguous sentence. Parsing stopped; retain the original text.",
  privateMotionGap:
    "Signing output awaits word-level motion alignment, spatial reference and nonmanual review. No retrieval or dictionary playback substitutes for understanding here.",
  privateProtectionScope:
    "This client includes no complete lexicon, motion data or model weights. Displayed results can still be copied; previously distributed packages cannot be recalled.",
  privateModel: "Model: {model}",
  privateDisconnected: "Session cleared.",
  privateEndpointInvalid:
    "Use an http://127.0.0.1 address with an explicit local service port.",
  privateTokenInvalid:
    "Enter the complete token from the current service terminal.",
  privateTextInvalid: "Enter 1–500 characters.",
  privateUnauthorized:
    "Invalid or expired token. Use the current service terminal token.",
  privateForbidden:
    "Origin rejected. Start the service with this exact extension origin allowed.",
  privateRateLimited: "Too many requests. Try again later.",
  privateBusy: "Service busy. Try again shortly.",
  privateRequestFailed: "Inference request failed. Check the local service.",
  privateResponseInvalid: "Unexpected model response.",
  privateConnectionFailed:
    "Local service unavailable or request timed out. Check the address and service.",
  privateRoles: {
    actor: "Actor",
    predicate: "Action / state",
    patient: "Patient / recipient",
    goal: "Goal",
    time: "Time",
    negation: "Negation",
    modal: "Modality",
    question: "Question",
    aspect: "Aspect",
    politeness: "Request",
    degree: "Degree",
  },
};
const SEMANTIC_ZH = {
  cslMode: "中文意思分析（规则研究）",
  cslAnalysisOnly:
    "仅分析中文意思：未完成中国手语词级对齐与语言复核，不播放动作。",
  cslTitle: "意思分析与表达草案",
  cslScope:
    "有限规则原型：先分析意思，再检查动作。不是已训练的中国手语理解模型；词序、手型、空间关系和表情仍需核对。",
  cslActor: "施事 / 谁",
  cslPredicate: "动作 / 状态",
  cslPatient: "受事 / 对谁",
  cslGoal: "地点 / 目标",
  cslTime: "时间",
  cslNegation: "否定及范围",
  cslModality: "意愿 / 能力 / 必要性",
  cslQuestion: "疑问",
  cslDegree: "程度",
  cslPoliteness: "请求",
  cslUnset: "未明确",
  cslDraft: "候选表达单元（非固定中国手语语序）",
  cslNoDraft: "句法超出原型范围，请核对原文。",
  cslGaps: "缺少动作证据：{words}",
  cslUnknown: "保留的未解析内容：{words}",
  cslMeaningKey: "机器语义表示（草案）",
  cslNoMatch: "该语义计划仍有证据缺口，不能播放为完整表达。",
  cslSources: "词级ID仅作为草案引用；分析结果不会触发词库或视频动作播放。",
  cslIssues: {
    csl_alignment_unreviewed:
      "中国手语词级对齐、空间指代和非手部语法尚未复核。",
    empty_input: "请输入一句中文。",
    unknown_input: "仍有未解析的词或符号。",
    unsupported_predicate_structure: "多个动作或缺少谓词，需进一步标注。",
    ambiguous_scope: "否定、情态或时间的范围有歧义。",
    actor_unresolved: "句中执行动作的人尚未明确。",
    ambiguous_participants: "人物关系超出当前简单句范围。",
    unsupported_operator_order: "否定或情态位置超出已支持结构。",
    unsupported_predicate_arguments: "动作的参与关系需进一步核对。",
    goal_unresolved: "目标地点或动作受事尚未解析清楚。",
    question_role_unresolved: "疑问词的语义角色尚未确认。",
    multiple_clauses: "包含多分句，原型不会擅自合并。",
    unassigned_meaning: "仍有未归属的语义单元。",
    unsupported_degree_scope: "程度修饰的范围尚未确认。",
    motion_evidence_missing: "部分概念没有可靠的独立动作资产。",
    nonmanual_question_unavailable: "疑问需要的面部或头部表达尚未实现。",
    spatial_agreement_unavailable: "帮助的方向、人物空间指代尚未核验。",
    modal_interpretation_unreviewed: "情态含义不能直接用一个词库动作替代。",
    input_limit: "超过500字，尾部保留并停止组合。",
  },
};
const SEMANTIC_EN = {
  cslMode: "Chinese meaning analysis (rules)",
  cslAnalysisOnly:
    "Chinese analysis only: CSL alignment and language review are incomplete. Motion playback is disabled.",
  cslTitle: "Meaning and expression draft",
  cslScope:
    "Bounded rule prototype: analyze meaning, then check motion evidence. This is not a trained CSL understanding model. Order, handshape, spatial agreement and nonmanuals remain unverified.",
  cslActor: "Actor",
  cslPredicate: "Action / state",
  cslPatient: "Patient / recipient",
  cslGoal: "Location / goal",
  cslTime: "Time",
  cslNegation: "Negation and scope",
  cslModality: "Desire / ability / obligation",
  cslQuestion: "Question",
  cslDegree: "Degree",
  cslPoliteness: "Request",
  cslUnset: "Unspecified",
  cslDraft: "Candidate units (not a fixed CSL word order)",
  cslNoDraft: "Outside the supported syntax. Review the original input.",
  cslGaps: "Missing motion evidence: {words}",
  cslUnknown: "Unparsed content preserved: {words}",
  cslMeaningKey: "Machine meaning representation (draft)",
  cslNoMatch:
    "Evidence is missing; this plan cannot play as a complete expression.",
  cslSources:
    "Word IDs are draft references only. Analysis never triggers dictionary or video motion playback.",
  cslIssues: {
    csl_alignment_unreviewed:
      "CSL word alignment, spatial reference and nonmanual grammar remain unreviewed.",
    empty_input: "Enter one Chinese sentence.",
    unknown_input: "Some words or symbols remain unparsed.",
    unsupported_predicate_structure:
      "Multiple actions or a missing predicate require annotation.",
    ambiguous_scope: "Negation, modality or time scope is ambiguous.",
    actor_unresolved: "The actor is unresolved.",
    ambiguous_participants:
      "Participant relations exceed this simple-clause prototype.",
    unsupported_operator_order: "Negation or modality order is unsupported.",
    unsupported_predicate_arguments: "Predicate arguments require review.",
    goal_unresolved: "The goal or patient is unresolved.",
    question_role_unresolved: "The question role is unresolved.",
    multiple_clauses: "Multiple clauses cannot be silently merged.",
    unassigned_meaning: "Some meaning units have no assigned role.",
    unsupported_degree_scope: "Degree scope is unresolved.",
    motion_evidence_missing:
      "Some concepts have no reliable independent motion.",
    nonmanual_question_unavailable:
      "Question-related facial and head expressions are unavailable.",
    spatial_agreement_unavailable:
      "Direction and spatial reference for help remain unverified.",
    modal_interpretation_unreviewed:
      "Modal meaning cannot be replaced by one dictionary motion.",
    input_limit:
      "Input exceeds 500 characters; the tail is retained and composition stopped.",
  },
};
const SEMANTIC_JA = {
  ...SEMANTIC_EN,
  cslMode: "中国語の意味分析（規則研究）",
  cslAnalysisOnly:
    "中国語の意味分析のみです。中国手話の語単位対応と確認は未完了のため、動作は再生しません。",
  cslTitle: "意味分析と表現案",
  cslScope:
    "限定した規則による試作です。意味を分析して動作資料を確認します。学習済みの中国手話理解モデルではなく、語順・手形・空間表現・表情は未確認です。",
  cslActor: "動作主",
  cslPredicate: "動作・状態",
  cslPatient: "対象・受け手",
  cslGoal: "場所・目標",
  cslTime: "時",
  cslNegation: "否定と範囲",
  cslModality: "希望・能力・必要性",
  cslQuestion: "疑問",
  cslDegree: "程度",
  cslPoliteness: "依頼",
  cslUnset: "未指定",
  cslDraft: "表現単位案（固定した中国手話の語順ではありません）",
  cslNoDraft: "構文が試作の範囲外です。原文を確認してください。",
  cslGaps: "動作資料の不足：{words}",
  cslUnknown: "未解析の内容を保持：{words}",
  cslMeaningKey: "意味の機械表現（案）",
  cslNoMatch: "資料が不足しているため、完全な表現として再生できません。",
  cslSources:
    "既存の手作成辞書を使います。動画の候補は自動的に有効化しません。",
};
const DEMO_ZH = {
  intakeRefinementTitle: "来源 {name} · 动作边界复核",
  intakeRefinementPending: "文字与边界建议 · 未人工确认",
  intakePrevious: "原候选窗口 {start}–{end}s：{text}",
  intakeBefore: "原候选窗口（供对比）",
  intakeAfter: "调整后的候选窗口",
  intakeRefinedWindow:
    "调整后名义区间 {start}–{end}s；实际解码 {frames} 帧 / {duration}s。临近视频结尾的动作仍需核对是否完整。",
  intakeCoverageComparison:
    "观测到至少一只手的帧占比：原窗口 {before}% → 调整后 {after}%。这是不同窗口的取材对比，不代表检测器准确率提升。",
  intakeTitle: "来源 {name} · 新视频复核",
  intakeSummary:
    "{files} 个文件 / {unique} 份不同内容；{screened} 个来源完成 OCR，{candidates} 条文字候选；{references} 段、{frames} 帧完成 2D 参考。",
  intakeLimits:
    "字幕语义、动作边界、镜像、手别和人物分组待确认。这里只展示 OCR 候选及二维观测，没有生成新的 SMPL-X 动作或训练模型；training_ready=false。",
  intakePending: "OCR候选 · 未复核",
  intakeWindow: "名义区间 {start}–{end}s · OCR均值 {confidence}",
  intakeOriginal: "查看授权原视频区间",
  intakeDuplicate: "与旧批次内容重复",
  catchupTitle: "手语视频续处理 · 原片与手部参考",
  catchupSummary:
    "{files} 个视频文件 / {sources} 份不同内容 · 新增 {windows} 段连续参考 / {frames} 帧 · 另有 {sampled} 帧独立手部观测",
  catchupLimits:
    "本页是标注候选和技术观测。字幕可能有错字或多句对话，边界、镜像和人物分组待确认；未开始训练，未生成新的 SMPL-X 参数。5帧抽样不代表整段已标注。",
  catchupReferences: "新增连续片段",
  catchupSources: "全部视频进度",
  catchupCaptions: "原始字幕候选",
  catchupIndex: "程序调用索引",
  catchupRegistry: "完整来源登记",
  catchupReport: "阶段报告",
  catchupSearch: "搜索句子、视频名或来源 ID",
  catchupPage: "{count} 项 · 第 {page}/{pages} 页",
  catchupPrevious: "上一页",
  catchupNext: "下一页",
  catchupOriginal: "原片候选窗口",
  catchupOverlay: "关键点叠加预览",
  catchupSync: "同步播放 / 暂停",
  catchupKeyframes: "展开5帧原图与手部裁剪",
  catchupKeyframeAlt: "{text} 的原图与估计手部槽裁剪",
  catchupIndependentAlt: "该来源5个独立抽样帧的手部观测",
  catchupCoverage:
    "技术观测可用帧：left {left}/{frames}，right {right}/{frames}；这不是准确率或解剖侧别核验。",
  catchupSourceStages:
    "旧参考 {prior} 段 · 旧连续动作 {motions} 段 · 新连续参考 {fresh} 段 · 新独立抽样 {sampled} 帧；完整视频处理仍见报告。",
  catchupHksl:
    "标题提示香港手语，语言尚待核验；独立保存，未纳入中国手语句子训练。",
  catchupEmptyCaption: "无可读取字幕",
  catchupMediaError: "媒体播放失败，请检查本地文件并重试。",
  demoSample: "工作忙吗？谢谢",
  demoRetry: "重新加载演示",
  demoLimit: "每次最多播放40个动作，其余文字列在暂不支持内容中。",
  demoCheckpoint: "Checkpoint：{hash} · {steps}步",
  demoWebGL: "3D渲染环境不可用",
  demoOpen: "打开演示工作台",
  demoLocal: "本地离线演示",
  demoExport: "导出本次结果",
  demoEyebrow: "让手语动起来 · 实验演示",
  demoHeading: "从文字，到看得见的表达",
  demoLead: "选择片段或输入文字，在虚拟人上播放参考动作、实验重建与词库动作。",
  demoInput: "输入文字",
  demoMode: "动作来源模式",
  demoAuto: "自动匹配",
  demoT08: "参考与实验动作",
  demoDictionary: "内置词库",
  demoPlaceholder: "试试：工作忙吗？谢谢",
  demoShortcut: "Ctrl / ⌘ + Enter 播放",
  demoPlay: "播放动作",
  demoPause: "暂停",
  demoResume: "继续",
  demoStop: "停止",
  demoLoading: "正在加载角色与动作…",
  demoMatches: "已识别内容",
  demoCatalog: "短句与词库",
  demoCatalogViews: "短句或词库动作",
  demoPhraseTab: "短句与片段",
  demoWordTab: "单词动作",
  demoPhraseSourceNote:
    "共 {total} 条：{reference} 条 T08 参考、{candidate} 条候选、{experimental} 条实验重建、{composed} 条词库组合。",
  demoWordSourceNote:
    "共 {count} 个内置词条；词条动画不是本轮新增的句子训练结果。",
  demoSearch: "搜索短句或词条",
  demoAvatarLabel: "当前项目角色 · Godette",
  demoStage: "虚拟人物",
  demoReadyBadge: "准备就绪",
  demoAtRest: "待机",
  demoView: "视角",
  demoFront: "正面",
  demoLeft: "左侧",
  demoRight: "右侧",
  demoSpeed: "速度",
  demoSmoothing: "动作平滑",
  demoExperimentalSmoothedBadge: "SMPL-X · 实验重建 · 平滑",
  demoExperimentalSmoothedWarningBadge: "SMPL-X · 实验平滑 · 原始跳变较大",
  demoExperimentalRawBadge: "SMPL-X · 实验重建 · 原始",
  demoModel: "研究模型",
  demoLearned: "T08原参考句",
  demoWords: "内置词库动作",
  demoCandidates: "候选参考动作",
  demoExperimental: "实验重建动作",
  demoExperimentalBadge: "SMPL-X · 实验重建",
  demoExperimentalWarningBadge: "SMPL-X · 实验重建 · 跳变较大",
  demoExperimentalToken:
    "当前为视频拟合的 SMPL-X 实验动作，未经过 T08 token 解码，未更新模型权重。",
  demoExperimentalWarning:
    "实验动作保留未经动作质量、镜像和人物核验的状态；仅用于 Demo，可能出现手型误差、跳变或穿模。",
  demoExperimentalPreviewWarning:
    "第 6 批人物预览：文字和动作首尾是未核验候选，可能夹带相邻教学动作。请对照原片检查手型、方向和抖动；镜像、人物及动作质量仍待确认。显示平滑只改变播放效果，未训练模型。",
  demoInvalidExperimentalAsset: "实验动作文件不完整或来源校验失败",
  demoCandidateBadge: "T08 tokenizer · 候选重建",
  demoCandidateDetail: "T08候选 · 归一化误差 {mse}",
  demoInvalidCandidateAsset: "候选动作来源或审核状态不符",
  demoCandidateWarning:
    "新增3条候选句：由现有T08权重编码/解码，未更新权重；重建误差高于原14条，镜像方向和人物分组未确认。仅供Demo比较，不作为准确翻译或正式训练数据。",
  demoTokens: "查看最近播放的动作编码",
  demoTokenNote:
    "下方为实际 T08 编码的 token。播放来自这些 token 的离线解码结果；浏览器不执行 PyTorch。",
  demoEvidence: "重建证据",
  demoComparison: "研究关键帧对照",
  demoReadonly: "只读候选 · 点击放大",
  demoClose: "收起对照",
  demoScope:
    "实验性展示：T08 负责已有参考动作的编码/重建；文字用于检索，内置词库用于补充。未覆盖文字不会自动生成手语，拼接也不代表正确的手语语法。",
  demoHow: "这份 Demo 怎样工作？",
  demoHowBody:
    "目录合并了 T08 参考与候选、视频拟合的实验动作和词库组合；重复文字只保留一个入口。实验动作未更新模型权重；词库组合并非句级训练或经手语者核验的翻译。",
  demoRetargetNote:
    "SMPL-X 姿态通过源骨架与角色 REST 校准后转换为四元数。根部、下身保持角色待机，表情系数尚未完整映射。手型和穿模仍为实验效果。",
  demoReady: "已就绪，输入文字或选择片段。",
  demoNoMatch: "暂未匹配到可用动作，请从下方选择一个例子。",
  demoUnknown: "暂不支持：{text}",
  demoAllMatched: "已覆盖全部输入内容。",
  demoCount: "{count} 个动作",
  demoPlaying: "正在播放 {index}/{count}：{text}",
  demoPaused: "已暂停，可继续或停止。",
  demoStopped: "已停止并回到待机。",
  demoFinished: "本次播放完成。",
  demoFailed: "加载失败：{detail}。请重新加载页面。",
  demoTokenEmpty: "播放一段 T08 参考短句后，可查看三路编码。",
  demoDictionaryToken: "当前播放内置词库动作，不使用 T08 token。",
  demoSourceT08: "T08 · 参考动作重建",
  demoSourceDictionary: "词库 · 内置动作",
  demoSourceFallback: "词库回退 · 参考动作加载失败",
  demoSourceComposition: "词库组合 · 逐词播放，非句级训练",
  demoResearchLabel: "{text} · {series} · 原图 / baseline / candidate",
  demoResearchMissing: "此工作区尚未打包研究对照图。",
  demoPartialAsset: "T08 资产不可用，现有词库仍可播放。",
  demoExported: "本次匹配与来源报告已下载。",
  demoInvalidMode: "未知动作模式",
  demoInvalidAsset: "T08资产格式或checkpoint来源不符",
  demoInvalidRotation: "无效姿态旋转",
  demoMissingBone: "角色缺少必要手部骨骼",
  demoNotReady: "角色尚未加载完成",
  demoTooLong: "输入过长，仅匹配前500个字符。",
};
const DEMO_EN = {
  intakeRefinementTitle: "Source {name} · Motion boundary review",
  intakeRefinementPending: "Text/boundary proposal · Not human-confirmed",
  intakePrevious: "Previous candidate window {start}–{end}s: {text}",
  intakeBefore: "Previous candidate window",
  intakeAfter: "Revised candidate window",
  intakeRefinedWindow:
    "Revised nominal window {start}–{end}s; {frames} decoded frames / {duration}s. Check completion near the original video end.",
  intakeCoverageComparison:
    "Frames with at least one observed hand: {before}% → {after}%. Different windows are compared; this is not improved detector accuracy.",
  intakeTitle: "Source {name} · New video review",
  intakeSummary:
    "{files} files / {unique} unique contents; {screened} sources screened, {candidates} caption candidates; {references} 2D references / {frames} frames.",
  intakeLimits:
    "Text meaning, boundaries, mirroring, handedness and signer groups are unverified. OCR candidates and 2D observations only; no new SMPL-X motions or model training. training_ready=false.",
  intakePending: "OCR candidate · Unreviewed",
  intakeWindow:
    "Nominal window {start}–{end}s · Mean OCR confidence {confidence}",
  intakeOriginal: "Open authorized source interval",
  intakeDuplicate: "Same bytes as an earlier source",
  catchupTitle: "Video catch-up · Source clips and hand references",
  catchupSummary:
    "{files} video files / {sources} unique contents · {windows} new reference windows / {frames} frames · {sampled} independent hand observations",
  catchupLimits:
    "Caption candidates and estimated observations only. Text, boundaries, mirroring and signer groups are unverified; no new training or SMPL-X parameters. Five samples do not annotate an entire video.",
  catchupReferences: "New continuous windows",
  catchupSources: "All source progress",
  catchupCaptions: "Raw caption candidates",
  catchupIndex: "Fitting index",
  catchupRegistry: "Source registry",
  catchupReport: "Stage report",
  catchupSearch: "Search text, video name or source ID",
  catchupPage: "{count} items · Page {page}/{pages}",
  catchupPrevious: "Previous",
  catchupNext: "Next",
  catchupOriginal: "Source candidate window",
  catchupOverlay: "Landmark preview",
  catchupSync: "Play / pause together",
  catchupKeyframes: "Five source frames and hand crops",
  catchupKeyframeAlt: "Source images and estimated hand crops for {text}",
  catchupIndependentAlt: "Five independent hand observation samples",
  catchupCoverage:
    "Eligible estimated frames: left {left}/{frames}, right {right}/{frames}; this is not accuracy or anatomical verification.",
  catchupSourceStages:
    "{prior} prior references · {motions} prior motions · {fresh} new reference windows · {sampled} independent samples. Whole-video completion remains described in the report.",
  catchupHksl:
    "Title suggests Hong Kong Sign Language; unverified, stored separately and excluded from CSL sentence training.",
  catchupEmptyCaption: "No readable caption",
  catchupMediaError: "Media playback failed. Check the local files and retry.",
  demoOpen: "Open demo workspace",
  demoLocal: "Local offline demo",
  demoExport: "Export session",
  demoEyebrow: "Sign language in motion · Experimental demo",
  demoHeading: "Words you can see",
  demoLead:
    "Choose a clip or enter text to play reference motions, experimental fits and dictionary motions.",
  demoInput: "Text input",
  demoMode: "Motion source",
  demoAuto: "Automatic",
  demoT08: "Reference / experimental",
  demoDictionary: "Dictionary",
  demoPlaceholder: "Try: 工作忙吗？谢谢",
  demoSample: "工作忙吗？谢谢",
  demoShortcut: "Ctrl / ⌘ + Enter to play",
  demoPlay: "Play",
  demoPause: "Pause",
  demoResume: "Resume",
  demoStop: "Stop",
  demoRetry: "Reload demo",
  demoLoading: "Loading avatar and motions…",
  demoMatches: "Matched text",
  demoCatalog: "Phrases and dictionary",
  demoCatalogViews: "Phrase or dictionary view",
  demoPhraseTab: "Phrases / clips",
  demoWordTab: "Dictionary motions",
  demoPhraseSourceNote:
    "{total} entries: {reference} T08 references, {candidate} candidates, {experimental} experimental fits, {composed} dictionary compositions.",
  demoWordSourceNote:
    "{count} built-in entries. These word motions are not new sentence-training results.",
  demoSearch: "Search phrases or dictionary entries",
  demoAvatarLabel: "Project avatar · Godette",
  demoStage: "Avatar",
  demoReadyBadge: "Ready",
  demoAtRest: "Idle",
  demoView: "View",
  demoFront: "Front",
  demoLeft: "Left",
  demoRight: "Right",
  demoSpeed: "Speed",
  demoSmoothing: "Motion smoothing",
  demoExperimentalSmoothedBadge: "SMPL-X · Experimental fit · Smoothed",
  demoExperimentalSmoothedWarningBadge:
    "SMPL-X · Experimental · Smoothed · Raw jitter flagged",
  demoExperimentalRawBadge: "SMPL-X · Experimental fit · Raw",
  demoModel: "Research model",
  demoLearned: "Original T08 phrases",
  demoWords: "Dictionary motions",
  demoCandidates: "Motion candidates",
  demoExperimental: "Experimental fits",
  demoExperimentalBadge: "SMPL-X · Experimental fit",
  demoExperimentalWarningBadge: "SMPL-X · Experimental fit · High jitter",
  demoExperimentalToken:
    "Video-fitted SMPL-X motion, not T08 token decoding. No model weights were updated.",
  demoExperimentalWarning:
    "Experimental motions have unreviewed motion quality, mirroring and signer identity. Demo only; hand errors, jitter and mesh intersections may occur.",
  demoExperimentalPreviewWarning:
    "Source-6 avatar preview: text and motion boundaries are unverified proposals and may include adjacent teaching demonstrations. Compare with the source for hand shapes, direction and jitter. Mirror, signer and motion quality remain unreviewed. Display smoothing changes playback only; no model was trained.",
  demoInvalidExperimentalAsset:
    "Incomplete experimental motion or provenance mismatch",
  demoCandidateBadge: "T08 tokenizer · Candidate reconstruction",
  demoCandidateDetail: "T08 candidate · normalized error {mse}",
  demoInvalidCandidateAsset:
    "Candidate motion provenance or review contract differs",
  demoCandidateWarning:
    "Three added phrase candidates are encoded/decoded with the existing T08 weights; weights were not updated. Reconstruction error is higher than for the original 14, and mirroring/signer grouping remain unconfirmed. Demo comparison only; not approved translation or training data.",
  demoTokens: "Last played motion tokens",
  demoTokenNote:
    "Actual T08 tokens are shown below. Playback uses their offline decoded motions; the browser does not run PyTorch.",
  demoEvidence: "Reconstruction evidence",
  demoComparison: "Research keyframe comparisons",
  demoReadonly: "Read-only candidates · Click to enlarge",
  demoClose: "Close comparison",
  demoScope:
    "Experimental showcase: T08 encodes and reconstructs existing reference motions. Text retrieves clips; dictionary entries supplement coverage. Unsupported text is reported. Concatenation does not establish correct sign language grammar.",
  demoHow: "How does this demo work?",
  demoHowBody:
    "The catalog merges T08 references and candidates, video-fitted experimental motions and dictionary compositions. Duplicate text has one entry. Experimental fits do not update model weights; dictionary compositions are not sentence-trained or sign-expert reviewed.",
  demoRetargetNote:
    "SMPL-X poses are calibrated to the avatar skeleton and played as quaternions. The root and lower body remain at rest; facial coefficients are not mapped. Hand shapes and mesh contact remain experimental.",
  demoReady: "Ready. Enter text or choose an example.",
  demoNoMatch: "No motion matched. Choose an example below.",
  demoUnknown: "Not supported: {text}",
  demoAllMatched: "All input text is covered.",
  demoCount: "{count} motions",
  demoPlaying: "Playing {index}/{count}: {text}",
  demoPaused: "Paused. Resume or stop.",
  demoStopped: "Stopped and reset to idle.",
  demoFinished: "Playback complete.",
  demoFailed: "Playback unavailable: {detail}. Reload to retry.",
  demoTokenEmpty:
    "Play a T08 reference phrase to inspect its three token streams.",
  demoDictionaryToken:
    "The last played dictionary motion does not use T08 tokens.",
  demoSourceT08: "T08 · Reference reconstruction",
  demoSourceDictionary: "Dictionary · Built-in motion",
  demoSourceFallback: "Dictionary fallback · Reference unavailable",
  demoSourceComposition:
    "Dictionary composition · Word-by-word, not sentence-trained",
  demoResearchLabel: "{text} · {series} · Original / baseline / candidate",
  demoResearchMissing:
    "No research comparisons were packaged in this workspace.",
  demoPartialAsset:
    "T08 assets unavailable. Dictionary motions can still play.",
  demoExported: "Session matching and provenance report downloaded.",
  demoInvalidMode: "Unknown motion mode",
  demoInvalidAsset: "Invalid T08 asset or checkpoint provenance",
  demoInvalidRotation: "Invalid pose rotation",
  demoMissingBone: "Required avatar hand bones are missing",
  demoNotReady: "Avatar is still loading",
  demoTooLong: "Only the first 500 characters are matched.",
  demoLimit:
    "Up to 40 motions per playback; the remaining text is listed as unsupported.",
  demoCheckpoint: "Checkpoint: {hash} · {steps} steps",
  demoWebGL: "3D rendering context unavailable",
};

/**
 * SignBridge 国际化支持
 * Supports: zh-CN, en, ja
 */
const LOCALES = {
  "zh-CN": {
    ...DEMO_ZH,
    ...SEMANTIC_ZH,
    ...PRIVATE_ZH,
    batchTitle: "本批补词清单 · 最多 8 个",
    batchManual: "手动加入完整词组（可选，避免分词误拆）",
    batchInvalidWord:
      "请输入 1–100 个字符的有效词语或词组，不能只有空白或标点。",
    batchIntro:
      "在分析结果中挑选高频缺词加入清单。先制作并保存草稿，再去“动作验收”检查，最后在编辑器或录制工具中人工确认启用。可匹配只表示词库有对应数据，不代表手语含义正确；此清单不会生成、修改或自动启用动作。",
    batchAdd: "加入本批",
    batchRefresh: "刷新补词状态",
    batchExport: "下载补词进度 JSON",
    batchClear: "清空本批清单",
    batchClearConfirm: "只清空补词清单？不会删除任何动作或视觉基准。",
    batchRemove: "移出本批",
    batchState: "实际匹配状态 / 动作 ID",
    batchLoading: "正在核对当前动作库…",
    batchEmpty: "清单为空。分析材料后，在未覆盖词旁点击“加入本批”。",
    batchMissing: "待制作 · 尚未完全匹配",
    batchDraft: "已保存候选 · 尚未启用或完全匹配",
    batchMatched: "可完全匹配 · 手语仍需人工核验",
    batchUnverified: "状态未核验，请重试",
    batchSummary:
      "本批 {count}/{max} 个 · 可完全匹配 {matched} 个 · 无效库记录 {invalid} 个。修改动作后会自动重新核对。",
    batchPrivacy:
      "只有主动加入的词会保存到本扩展本地存储（刷新后保留），不保存原文或例句、不上传。清单不属于动作包，下载的进度包含所选词及匹配 ID，分享前请检查隐私。",
    batchFailure: "补词清单操作失败：{detail}",
    batchFull: "本批已满 8 个，请先完成或移除部分词。",
    batchInvalid: "补词清单数据无效，原记录未被覆盖。可明确清空后重新加入。",
    batchLockUnavailable:
      "跨页面写入锁不可用，已停止修改。请从扩展控制面板打开此页。",
    reviewTitle: "动作验收",
    reviewIntro:
      "批量回放已保存的动作，以固定正面、右侧、左侧截图对照自己确认的基准。不改骨骼参数，也不自动启用翻译。",
    reviewLimits:
      "每批最多 8 个动作，每个最多抽取 12 个关键帧，包含首尾帧。截图仅检查目标姿态，不覆盖所有过渡、碰撞、字幕句级播放或手语含义；视觉变化需人工复核。内置列表使用 SIGNS，不包含 CHARS 单字回退。",
    reviewHelp:
      "控制面板 → 动作验收。勾选动作后可自动依次回放或生成三视图；查看手形、方向和穿模，确认后点击“保存 / 替换视觉基准”。以后重新截图可并排对比。动作数据改变会提示重新核验，模型/浏览器/渲染环境改变时不进行数值对比。保存基准不等于确认手语正确，不会修改动作库的草稿或启用状态。",
    reviewStorageHelp:
      "视觉基准只存于当前扩展的 IndexedDB，与动作库分开，最多 100 个 / 64 MiB。不包含在动作包备份中；卸载前请下载 PNG 和 JSON 报告留存（本轮不支持重新导入基准）。截图和报告仅在你点击下载时导出，不发送到网络。",
    reviewReload: "重新加载模型 / 重试",
    reviewSelect: "1 · 选择动作",
    reviewSearch: "按名称、ID 或状态筛选（不会取消已勾选动作）",
    reviewCatalogCount:
      "可用 {total} 个 · 已选 {count}/{max} · 无效库记录 {invalid} 个",
    reviewPlay: "依次回放全部帧",
    reviewCapture: "生成关键帧三视图",
    reviewStop: "停止当前任务",
    reviewPreview: "固定视角预览",
    reviewView: "回放视角",
    reviewFront: "正面",
    reviewRight: "人物右侧",
    reviewLeft: "人物左侧",
    reviewPreviewHelp:
      "视角只用于检查，不改变浮窗位置或大小。回放每个动作前恢复 REST；截图完成后恢复正面。",
    reviewResults: "2 · 人工核验与基准对比",
    reviewExport: "下载本批 JSON 报告",
    reviewBuiltin: "内置 · 待人工核验",
    reviewEnabled: "自定义 · 已启用",
    reviewDraft: "自定义 · 草稿",
    reviewLoading: "正在加载实际模型、骨骼和动作库…",
    reviewReady: "已就绪，共 {total} 个动作。选择动作后回放或截图。",
    reviewFailure: "验收失败：{detail}",
    reviewCatalogChanged:
      "动作库已变化，本批结果失效。请重新选择并截图，旧基准不会自动覆盖。",
    reviewPlaying: "正在回放 {index}/{total}：{name}",
    reviewCapturing: "正在截图 {index}/{total}：{name}",
    reviewFinished:
      "本批完成 {count} 个，结构错误 {failures} 个；结果仍需人工检查。",
    reviewCancelled: "已停止；未完成批次不保留截图结果，不修改基准。",
    reviewDiagnostics:
      "共 {frames} 帧 / {duration} 秒，使用 {bones} 个骨骼。截图行对应帧：{indices}；未截图 {omitted} 帧。",
    reviewSheetOrder:
      "每行从左到右：正面 → 人物右侧 → 人物左侧；行顺序按帧号。下载 PNG 可放大检查。",
    reviewCurrent: "当前截图",
    reviewBaseline: "已确认的视觉基准",
    reviewNoBaseline: "尚无视觉基准。先检查动作，再手动保存。",
    reviewCompared:
      "基准时间 {date}。RGB 单通道差异 >16 的像素占 {ratio}%，平均通道差异 {mean}/255。仅供人工复核，不代表手语正确或不存在穿模。",
    reviewMotionChanged:
      "动作数据已改变（包括时长或名称），旧基准仍保留。数值对比已停止，请重新核验。",
    reviewIncompatible:
      "模型、骨骼、浏览器或渲染环境与旧基准不同，不能可靠进行数值对比。旧图只供参考。",
    reviewUnavailable:
      "基准读取 / 对比失败：{detail}。当前截图仍可下载，保存将再次尝试。",
    reviewSaveBaseline: "保存 / 替换视觉基准",
    reviewDeleteBaseline: "删除此动作基准",
    reviewDownloadImage: "下载当前 PNG",
    reviewSaveConfirm:
      "确认已检查“{name}”的三视图？将保存当前截图并替换已有视觉基准，仅用于回归比较；不会启用翻译或认证手语正确性。",
    reviewDeleteConfirm: "删除“{name}”的视觉基准？此操作不删除动作库中的动作。",
    reviewSaved: "视觉基准已保存；动作库与翻译启用状态未改变。",
    reviewDeleted: "此动作的视觉基准已删除，动作数据未改变。",
    reviewStorageError:
      "无法访问本地基准存储。请检查浏览器可用空间并从扩展控制面板重开。",
    reviewStorageFull:
      "视觉基准达到 100 个或 64 MiB 上限。请先下载留存，再删除不需要的基准。",
    reviewBaselineChanged:
      "另一页面已更新基准，未覆盖。请重新截图读取最新基准后再确认。",
    reviewModelError: "模型加载失败或尺寸无效，请重新构建扩展并重试。",
    reviewMissingBones: "模型缺少手语必需骨骼，已阻止验收。",
    reviewRenderError:
      "渲染失败或 WebGL 上下文丢失，停止任务后请点击重新加载。",
    reviewInvalidSamples: "关键帧抽样参数无效。",
    reviewImageMismatch: "基准图片损坏或尺寸不一致，不能进行对比。",
    motionPackTitle: "动作库备份 / 批量导入",
    motionPackHelp:
      "导出当前模型下全部已保存的自定义动作（不含未保存编辑或内置词典）。选文件只做预检，确认后新增草稿；同 ID 同内容跳过，不同内容拒绝整包导入。新动作仍须逐条载入、预览、确认启用。",
    motionPackPrivacy:
      "文件只包含动作名称、匹配文字、标签、骨骼绑定、帧数据及导出时启用标记，不含密钥或字幕。名称和标签也可能含隐私，分享前请检查。导入不会继承审核记录，也不上传文件。",
    motionPackExport: "备份全部已保存动作",
    motionPackFile: "选择动作包 JSON（不是单动作 JSON）",
    motionPackLimits:
      "每包最多 500 个动作、8 MiB；单动作最多 2 MiB。模型与 REST 必须一致。",
    motionPackInspect: "重新预检",
    motionPackImport: "确认导入新草稿",
    motionPackClear: "取消待导入文件",
    motionPackSummary:
      "预检：新增 {new}，已存在 {existing}，ID 冲突 {conflict}。尚未写入动作库。",
    motionPackName: "动作 / ID",
    motionPackState: "处理方式",
    motionPackWarnings: "需要注意",
    motionPackNew: "新增草稿",
    motionPackExisting: "相同内容，跳过",
    motionPackIdConflict: "ID 冲突，不覆盖",
    motionPackWasEnabled: "包内标记曾启用；只是来源信息，不代表审核可信。",
    motionPackAliases:
      "匹配文字可能重复：{aliases}。草稿可保存，启用前需检查（含未启用条目）。",
    motionPackMaterial: "无匹配文字，只作姿势素材，不能启用翻译。",
    motionPackReady:
      "预检完成。只会新增草稿，不改变当前姿势或已有动作的启用状态。",
    motionPackChecking: "正在核对模型和本地动作库…",
    motionPackCleared: "已取消，动作库没有改变。",
    motionPackConfirm:
      "将新增 {count} 个草稿，不覆盖旧动作、不自动启用。请确认来源授权，导入后逐条检查手形、方向和含义。继续？",
    motionPackImported:
      "已新增 {imported} 个草稿，跳过 {skipped} 个已有动作。请从列表载入、预览并逐条确认。",
    motionPackExported:
      "已发起 {count} 个已保存动作的下载，请检查下载结果；不含尚未保存的编辑。",
    motionPackInvalid:
      "不是有效的 v1 动作包 JSON；单动作文件请使用上方“导入动作 JSON”。",
    motionPackEmpty: "动作包为空，或当前没有可备份的已保存动作。",
    motionPackTooLarge:
      "超过限制：动作包 8 MiB / 500 个动作，单动作 2 MiB。没有写入。",
    motionPackDuplicateId:
      "包内存在重复 ID，无法确定应保留哪个动作，已拒绝导入。",
    motionPackInvalidStored:
      "本地库有损坏或与当前模型不兼容的记录，未生成不完整备份；原数据保留，请先检查这些记录。",
    motionPackConflict:
      "同 ID 的本地内容不同或损坏，整包导入已阻止，不会覆盖。需要另存时请使用单动作导入创建副本。",
    motionPackStale:
      "动作库已改变，旧预检失效。请点击“重新预检”，确认清单后再导入。",
    motionPackLockUnavailable:
      "跨页面写入锁不可用，已停止批量导入。请从扩展控制面板重新打开工具页。",
    motionPackEncoding: "文件不是有效的 UTF-8 JSON，请转换编码后重试。",
    coverageTitle: "词库覆盖分析",
    coverageHelpWorkflow:
      "在控制面板打开“词库覆盖分析”，粘贴文字或导入 UTF-8 TXT / SRT / VTT，分析未覆盖词的频次与语境。点击词条旁的姿势编辑器或录制工具只会预填名称和匹配文字；制作并人工确认动作后回到分析页重新分析，可核对是否实际生效。",
    coverageIntro:
      "先找出真实语料里缺少的词，再制作并验证动作。不会自动生成手语，也不会改动现有姿势。",
    coverageInput: "1 · 选择分析材料",
    coverageTextLabel: "粘贴文字（每行一段），或导入 UTF-8 字幕",
    coverageLimits:
      "上限：256 KiB 文件、50,000 字符、1,000 段、每段 2,000 字符。SRT / WebVTT 按字幕条目分析。",
    coverageFormat: "格式",
    coveragePlainText: "纯文字 · 每行一段",
    coverageImport: "导入文件",
    coverageAnalyze: "分析当前词库",
    coverageClear: "清空",
    coverageResults: "2 · 找到补词优先级",
    coverageMetricHelp:
      "覆盖率 = 命中的分词数 ÷（命中分词数 + 未覆盖分词数），跳过的虚词与标点不计入。统计的是整段词库覆盖，不是手语准确率，也不保证句意完整或全部动作会播完。",
    coverageUnknownTitle: "未覆盖词 · 按出现次数排序",
    coverageDraftHelp:
      "优先级只是分词结果，先结合语境判断是否应制作完整词组。进入工具只预填名称和匹配文字，不会自动保存或启用，也不会把当前姿势当成该词的正确手语。",
    coverageWord: "未覆盖词",
    coverageFrequency: "次数 / 段数",
    coverageExamples: "例句段号",
    coverageMake: "制作与人工验证",
    coverageDetailsTitle: "3 · 逐段核对实际命中",
    coverageDisplayLimit:
      "页面最多显示前 100 个未覆盖词和前 200 段；统计包含全部输入。导出报告可保留全部结果。",
    coverageIncludeText: "导出时包含原文和逐段明细（可能含隐私）",
    coverageExport: "导出分析报告 JSON",
    coveragePrivacy:
      "材料仅在本页内存分析，不上传、不自动保存，关闭页面即丢弃。默认报告不含原文，但仍包含未覆盖词，分享前请检查。",
    coverageSummary:
      "覆盖 {ratio} · {segments} 段 · 命中 {matched} / 未覆盖 {unknown} / 跳过 {skipped}",
    coverageNoTokens: "不适用（无待翻译词）",
    coverageTruncation:
      "{count} 段触及实时播放每段 12 个动作上限；这部分可能未播放，请查看逐段剩余文本。",
    coverageOccurrences: "{count} 次 / {segments} 段",
    coverageUniqueUnknown:
      "共 {count} 个不同的未覆盖词。过长的词请先拆分或重新判断分词。",
    coverageNoUnknown: "未发现未覆盖词；仍需人工核对手语含义与动作。",
    coverageMatches: "命中：{value}",
    coverageUnmatched: "未覆盖：{value}",
    coverageSkipped: "跳过：{value}",
    coverageRemaining: "达到播放上限后的剩余文本：{value}",
    coverageCatalog:
      "当前词库：{signs} 内置词条 / {aliases} 查找别名 / {chars} 单字；已启用自定义 {enabled}；未生效 {drafts}；无效或模型不匹配 {invalid}（原数据保留）。",
    coverageReady:
      "粘贴或导入材料后点击分析。首次分析会读取当前模型，核验自定义动作绑定。",
    coverageLoading: "正在核验模型与动作库并分析…",
    coverageDone: "分析完成。可制作缺失动作，人工确认启用后回到此页再次分析。",
    coverageChanged: "材料已改变，请重新分析；旧报告不可导出。",
    coverageCatalogChanged:
      "共享动作库已改变，请重新分析以查看最新覆盖；旧报告不可导出。",
    coverageImported: "材料已导入。点击分析，不会自动播放或保存。",
    coverageFailure: "分析未完成：{detail}",
    coverageTooLarge: "超过材料大小、段数或单段长度上限，请拆分后分析。",
    coverageEmpty: "请提供至少一段非空文字。",
    coverageInvalidFormat: "仅支持 TXT、SRT、WebVTT，请选择正确格式。",
    coverageInvalidSubtitles:
      "字幕格式无效。请检查空行、时间轴、起止顺序及 WebVTT 文件头；不会把时间轴当正文统计。",
    coverageEncoding: "文件不是有效 UTF-8，请转换编码后重试。",
    coverageModelError:
      "无法核验当前模型或共享动作库，请确认从插件打开且模型可加载，然后重试。没有退回到不完整的统计。",
    coverageOpenFailed: "工具页面未能打开，请从插件控制面板重试。",
    coveragePrefilled:
      "已从覆盖分析预填名称和匹配文字。当前姿势不是该词的已验证动作；请制作、保存、预览并人工确认。",
    motionLibraryTitle: "共享动作库 · 第二阶段",
    motionLibraryHelp:
      "编辑器、录制器、浮窗使用同一份弧度数据。保存的是草稿；预览并确认启用后，匹配文字才参与翻译。",
    motionName: "动作名称（必填）",
    motionTexts: "匹配文字（多个用逗号分隔；留空仅作姿势素材）",
    motionTags: "分类标签（逗号分隔）",
    motionNew: "新建副本",
    motionNewHelp: "当前姿势保留，请填写新的动作名称。",
    motionSave: "保存草稿",
    motionSaved: "已保存草稿，需重新预览、确认后启用。",
    motionLoad: "载入选中",
    motionLoaded: "已载入。导入文件不会自动保存或启用，请检查后保存草稿。",
    motionChoose: "选择已保存的动作…",
    motionDraft: "草稿 / 未启用",
    motionEnabled: "已确认启用",
    motionPreview: "预览当前动作",
    motionPreviewHelp:
      "正在使用与浮窗相同的播放器。请检查手形、方向、穿模和含义；修改后需重新保存。",
    motionEnable: "确认后用于翻译",
    motionDisable: "停用选中动作",
    motionConfirm:
      "我已完整预览并检查手形、方向、穿模和文字含义，确认将这个动作用于翻译。此确认不是专业手语认证。是否启用？",
    motionEnabledHelp:
      "已启用；已打开的浮窗会自动读取，新输入的匹配文字使用此动作。",
    motionDisabledHelp: "已停用，草稿保留。浮窗取消正在排队的自定义动作。",
    motionRefresh: "刷新动作列表",
    motionExport: "下载统一 JSON",
    motionExportCode: "导出代码（不保存）",
    motionImport: "导入动作 JSON",
    motionImportFormat: "导入文件的单位和格式",
    motionFormat: "统一格式 · 弧度 / REST 增量",
    motionLegacyEditor: "旧编辑器 delta · 度数（仅姿势对象）",
    motionLegacyRecorder: "旧录制器 frames.pose · 度数",
    motionLegacyAbsolute: "旧编辑器绝对旋转 · 弧度",
    motionMigrate: "迁移本页旧动作库",
    motionLegacyConfirm:
      "旧文件没有模型绑定信息。仅当它来自当前模型且所选格式与单位正确时才继续；转换后必须逐个检查。原始本地动作库不会删除。是否继续？",
    motionMigrated:
      "已迁移 {count} 个草稿；旧库保留，尚未启用。重复迁移会生成副本。",
    motionIgnored: "有 {count} 个损坏或模型不匹配的条目未载入；原数据保留。",
    motionFailure: "未完成：{detail}",
    motionInvalidData: "动作格式或参数无效：{detail}",
    motionModelNotReady: "模型尚未加载完成。",
    motionRigMismatch: "模型骨骼或 REST 初始姿势不一致，已拒绝应用。",
    motionStorageUnavailable: "共享存储不可用，请从插件控制面板打开工具页面。",
    motionSelectFirst: "请先保存或选择一个动作。",
    motionSaveFirst: "动作已改变，请重新保存为草稿、预览后启用。",
    motionPreviewFirst: "请先预览当前动作，再确认启用。",
    motionAliasConflict:
      "匹配文字为空或与已启用/内置词条重复：{detail}。请换一个明确的新词组。",
    motionFileTooLarge: "文件过大或条目过多（单文件上限 2 MiB）。",
    motionEditorSingleFrame:
      "编辑器只编辑单帧姿势；请用录制器打开多帧动画，避免丢帧。",
    motionFrameLimit: "已达到 240 帧上限，录制已停止。",
    motionFrameDuration: "关键帧时长（秒，0.05–10）",
    motionUpdateFrame: "更新选中帧",
    motionHelpRig:
      "Godette 使用标准 Humanoid 骨名映射及完整可用指骨链。编辑器、录制器与浮窗共用同一个 profile 和 REST 初始姿势，不再各自解释骨骼。",
    motionHelpAxes:
      "X/Y/Z 是骨骼本地轴，不是固定的世界方向；不同骨骼的轴向不能一概而论。统一导出为 REST 增量弧度，录制器骨骼滑块显示绝对本地弧度。",
    motionHelpCreate:
      "姿势编辑器制作单帧，录制器制作多帧。填写动作名称、匹配文字、标签后保存草稿；匹配文字留空可只作姿势素材。自定义文字不能覆盖内置词或其它已启用词条。",
    motionHelpReview:
      "保存草稿 → 预览当前动作 → 检查手形、方向、穿模和含义 → 确认后用于翻译。之后在控制面板输入匹配文字验证浮窗。人工确认不是专业手语认证。",
    motionHelpFrames:
      "录制器点击时间线选帧，调好骨骼和时长后点击“更新选中帧”；新增姿势用添加关键帧。单帧 0.05–10 秒，最多 240 帧且总计不超过 120 秒。自动录制每 0.3 秒采样。",
    motionHelpUpdates:
      "两个工具页与浮窗共享同一扩展 ID、同一浏览器用户配置的本地动作库。启用/停用会自动更新浮窗并取消旧播放队列；再次保存撤销旧确认。新建副本保留姿势但不覆盖原动作。",
    motionHelpBackup:
      "下载统一 JSON 用于备份，导出不会自动保存或启用。导入是新草稿副本，必须重新保存、预览、确认。编辑器不截断多帧文件，请用录制器载入。卸载扩展或更换扩展 ID 前务必下载备份。",
    motionHelpLegacy:
      "迁移本页旧动作库会保留 sb_gestures 原数据，重复迁移会生成副本。导入旧 JSON 时须明确选择度数/绝对弧度等格式，不猜单位、不执行代码。旧文件没有模型绑定，必须来自当前模型并人工复核。",
    motionHelpBinding:
      "文件最多 2 MiB，骨骼/REST 不一致、未知骨名或不合法参数会被拒绝。绑定不是整个 GLB 或蒙皮的指纹。请从扩展控制面板打开工具；独立 localhost 页面不能共享这份存储。升级构建后须重新加载扩展并关闭、重开旧工具页。",
    motionHelpCollision:
      "先定位具体词条和关键帧，在编辑器/录制器从正面与侧面检查肘部和手腕；仅修改该动作、重新预览确认，不全局反转或批量增加角度。",
    motionHelpCoverage:
      "查看命中的 motionIds 和未命中文本；无匹配时不打断正在播放的动作。",
    motionHelpCatalog:
      "查看已启用自定义动作数量和无效记录数量；未启用草稿不会参与翻译。",
    motionDurationInvalid: "关键帧时长须为 0.05–10 秒。",
    motionLoadingFailed: "模型加载失败：{detail}",
    name: "中文（简体）",
    title: "SignBridge — 手语翻译",
    description: "实时将视频语音翻译成手语，通过3D虚拟人展示",
    settings: "设置",
    avatar: "虚拟人",
    language: "语言",
    sourceLanguage: "视频语言",
    targetSignLanguage: "手语类型",
    avatarStyle: "虚拟人外观",
    avatarSize: "虚拟人大小",
    avatarPosition: "虚拟人位置",
    positionBottomRight: "右下角",
    positionBottomLeft: "左下角",
    positionTopRight: "右上角",
    positionTopLeft: "左上角",
    enableAutoDetect: "自动检测视频",
    enableSubtitles: "显示字幕",
    voiceVolume: "语音音量",
    speed: "手语速度",
    about: "关于",
    start: "开始翻译",
    stop: "停止翻译",
    loading: "加载中...",
    noVideo: "未检测到视频",
    error: "出错了",
    errorNoVideo: "页面上没有找到视频",
    ready: "已就绪",
    translating: "正在翻译...",
    unavailable: "当前页面不可用",
    inputPlaceholder: "输入文字，虚拟人打手语...",
    send: "发送",
    sent: "已发送",
    audioOff: "视频声音：关闭",
    audioOn: "视频声音：开启",
    audioStopped: "已关闭",
    audioListening: "识别中...",
    audioStarting: "正在捕获声音...",
    audioUnavailable: "当前页面不可捕获",
    audioCaptureFailed: "声音捕获失败",
    audioCloudKeyRequired: "请先配置云端 API Key",
    audioPermissionRequired: "请先保存识别设置并授权服务地址",
    audioLocalUnavailable: "请先一键部署本地 Whisper",
    asrSettings: "声音识别设置",
    asrTitle: "视频声音识别",
    asrPurpose: "选择本地 Whisper 或云端 ASR，将当前视频声音转换为手语动作。",
    asrProvider: "识别方式",
    asrLocal: "本地 Whisper",
    asrCloud: "云端 ASR",
    asrLocalSettings: "本地 Whisper 设置",
    asrLocalPrivacy:
      "模型和音频都在浏览器扩展内处理，视频声音不会上传到识别服务。",
    asrDeployLocal: "一键部署本地 Whisper",
    asrEndpoint: "服务地址",
    asrModel: "模型",
    asrModelTiny: "tiny（最快，约 75 MB）",
    asrModelBase: "base（均衡，约 150 MB）",
    asrModelSmall: "small（更准确，约 500 MB）",
    asrDeployHint: "点击后自动下载并缓存模型，无需安装 Python 或运行本地服务。",
    asrDeployRequired: "当前模型尚未部署。",
    asrRequestingModelPermission: "正在申请模型下载权限...",
    asrDeploying: "正在下载并初始化模型：{progress}%",
    asrDeployReady: "本地模型 {model} 已就绪。",
    asrDeployFailed: "本地模型部署失败",
    asrCloudSettings: "云端 ASR 设置",
    asrCloudPrivacy:
      "视频音频分片会发送到你配置的服务，请确认服务的隐私与计费规则。",
    asrApiKey: "API Key",
    asrCommonSettings: "通用设置",
    asrLanguage: "识别语言",
    asrChunkSeconds: "音频分片",
    asrTest: "测试连接",
    asrSave: "保存设置",
    asrPermissionDenied: "未授予该服务地址的网络权限。",
    asrSaved: "设置已保存。",
    asrInvalidConfig:
      "设置无效：远程服务需HTTPS；HTTP仅允许127.0.0.1、localhost或[::1]本机地址，URL不可含账号密码。",
    asrTesting: "正在测试识别服务...",
    asrTestPassed: "连接测试通过。",
    asrTestFailed: "连接测试失败",
    poseEditor: "姿势编辑器",
    recorder: "录制工具",
    help: "帮助文档",
    tagline: "让信息无障碍",
    auto: "自动检测",
    simplifiedChinese: "中文（普通话）",
    footer: "SignBridge — 让信息无障碍",
    signLanguageTypes: {
      csl: "中国手语 (CSL)",
      asl: "美国手语 (ASL)",
      bsl: "英国手语 (BSL)",
      jsl: "日本手语 (JSL)",
      ksl: "韩国手语 (KSL)",
      tsl: "台湾手语 (TSL)",
    },
    avatarStyles: {
      default: "默认",
      friendly: "友好",
      professional: "专业",
      anime: "动漫风格",
    },
    voiceVolumeLevels: {
      low: "低（仅视频）",
      medium: "中（视频+手语）",
      high: "高（仅手语）",
    },
  },
  en: {
    ...DEMO_EN,
    ...SEMANTIC_EN,
    ...PRIVATE_EN,
    batchTitle: "Vocabulary batch · up to 8 items",
    batchManual:
      "Add a complete phrase manually (optional, avoids token-splitting mistakes)",
    batchInvalidWord:
      "Enter a word or phrase of 1–100 characters, not only whitespace or punctuation.",
    batchIntro:
      "Add frequent gaps from the analysis. Save a draft, inspect it in Motion review, then explicitly enable it in the editor or recorder. A full match means data is available, not that the sign is linguistically correct. This list never generates, edits or enables motions.",
    batchAdd: "Add to batch",
    batchRefresh: "Refresh batch status",
    batchExport: "Download progress JSON",
    batchClear: "Clear batch list",
    batchClearConfirm:
      "Clear only this list? Motions and visual baselines will not be deleted.",
    batchRemove: "Remove from batch",
    batchState: "Actual match status / motion IDs",
    batchLoading: "Checking the current motion library…",
    batchEmpty:
      "No selected words. Analyze a sample, then add vocabulary gaps to this batch.",
    batchMissing: "Needs authoring · not fully matched",
    batchDraft: "Candidate saved · not enabled or fully matched",
    batchMatched: "Fully matched · human sign-language review still required",
    batchUnverified: "Status not verified; please retry",
    batchSummary:
      "Batch {count}/{max} · fully matched {matched} · invalid library entries {invalid}. Motion changes trigger a fresh check.",
    batchPrivacy:
      "Only words you explicitly add persist in this extension's local storage. No source text or examples are saved or uploaded. The list is not part of a motion pack. Progress exports contain selected words and motion IDs; check privacy before sharing.",
    batchFailure: "Vocabulary batch failed: {detail}",
    batchFull: "This batch already has 8 words. Complete or remove some first.",
    batchInvalid:
      "Invalid batch data. Existing data was not overwritten; explicitly clear the list to start again.",
    batchLockUnavailable:
      "Cross-page write lock unavailable. No changes made. Open this page from the extension panel.",
    reviewTitle: "Motion review",
    reviewIntro:
      "Replay saved motions and compare fixed front, right and left snapshots with manually approved visual references. No rig changes or automatic translation approval.",
    reviewLimits:
      "Up to 8 motions per batch and 12 sampled keyframes per motion, including first and last. Snapshots cover target poses, not every transition, collision, subtitle sequence or linguistic meaning. Human review is required. The built-in list covers SIGNS, not CHARS fallbacks.",
    reviewHelp:
      "Control panel → Motion review. Select motions to replay or capture three views. Check hands, directions and intersections before saving a visual baseline. Later captures appear alongside it. Changed motion data requires new review; different model/browser/rendering environments disable numeric comparison. Baselines do not change draft or enabled status, and do not certify correct signing.",
    reviewStorageHelp:
      "References stay in this extension's IndexedDB, separate from the motion library, capped at 100 / 64 MiB. Motion packs do not include them. Download PNG and JSON before uninstalling (baseline reimport is not supported yet). Nothing is sent over the network.",
    reviewReload: "Reload model / retry",
    reviewSelect: "1 · Select motions",
    reviewSearch:
      "Filter by name, ID or status (checked motions remain selected)",
    reviewCatalogCount:
      "{total} available · {count}/{max} selected · {invalid} invalid library records",
    reviewPlay: "Replay all frames in order",
    reviewCapture: "Capture three-view keyframes",
    reviewStop: "Stop current task",
    reviewPreview: "Fixed-view preview",
    reviewView: "Playback view",
    reviewFront: "Front",
    reviewRight: "Character's right",
    reviewLeft: "Character's left",
    reviewPreviewHelp:
      "Views never change the floating avatar. Each replay starts from REST; capture resets to the front view.",
    reviewResults: "2 · Human review and baseline comparison",
    reviewExport: "Download batch JSON report",
    reviewBuiltin: "Built-in · needs human review",
    reviewEnabled: "Custom · enabled",
    reviewDraft: "Custom · draft",
    reviewLoading: "Loading the actual model, rig and motion library…",
    reviewReady: "Ready: {total} motions. Select motions to replay or capture.",
    reviewFailure: "Review failed: {detail}",
    reviewCatalogChanged:
      "The library changed; these results are stale. Select and capture again. Existing baselines are never overwritten automatically.",
    reviewPlaying: "Playing {index}/{total}: {name}",
    reviewCapturing: "Capturing {index}/{total}: {name}",
    reviewFinished:
      "Finished {count} motions; {failures} structural errors. Human review is still required.",
    reviewCancelled:
      "Stopped. Incomplete batch captures discarded; baselines unchanged.",
    reviewDiagnostics:
      "{frames} frames / {duration}s, {bones} bones. Sheet rows: frames {indices}; {omitted} frames not captured.",
    reviewSheetOrder:
      "Columns: front → character's right → character's left. Rows follow frame indices. Download PNG to inspect at full size.",
    reviewCurrent: "Current capture",
    reviewBaseline: "Confirmed visual reference",
    reviewNoBaseline:
      "No visual reference yet. Inspect the motion before saving one.",
    reviewCompared:
      "Baseline {date}. Pixels with RGB channel difference >16: {ratio}%; mean channel difference {mean}/255. Review hint only, not signing or collision certification.",
    reviewMotionChanged:
      "Motion data changed (including duration or name). Previous reference retained; numeric comparison disabled. Review again.",
    reviewIncompatible:
      "Model, rig, browser or rendering environment differs. Numeric comparison is unreliable and disabled. Old image is for reference only.",
    reviewUnavailable:
      "Baseline read / comparison failed: {detail}. Current PNG remains downloadable; saving will retry.",
    reviewSaveBaseline: "Save / replace visual reference",
    reviewDeleteBaseline: "Delete this reference",
    reviewDownloadImage: "Download current PNG",
    reviewSaveConfirm:
      "Have you checked all three views of “{name}”? Saving replaces its existing visual reference for regression comparison only. It neither enables translation nor certifies correct signing.",
    reviewDeleteConfirm:
      "Delete the visual reference for “{name}”? The motion itself is not deleted.",
    reviewSaved:
      "Visual reference saved; motion library and translation status unchanged.",
    reviewDeleted: "Visual reference deleted; motion data unchanged.",
    reviewStorageError:
      "Cannot access local baseline storage. Check disk space and reopen from the extension control panel.",
    reviewStorageFull:
      "Reference limit reached (100 or 64 MiB). Download a copy, then remove unneeded references.",
    reviewBaselineChanged:
      "Another page updated this reference. Nothing overwritten. Capture again before confirming.",
    reviewModelError:
      "Model load failed or dimensions invalid. Rebuild the extension and retry.",
    reviewMissingBones: "Required signing bones are missing; review blocked.",
    reviewRenderError:
      "Rendering failed or WebGL context was lost. Stop and reload the model.",
    reviewInvalidSamples: "Invalid keyframe sampling parameters.",
    reviewImageMismatch:
      "Reference image is damaged or dimensions differ; comparison blocked.",
    motionPackTitle: "Library backup / batch import",
    motionPackHelp:
      "Export all saved custom motions for this model, not unsaved edits or built-in signs. Choosing a file only runs preflight. Confirmation adds drafts: identical IDs/content are skipped; differing content blocks the entire import. Load, preview and confirm each new motion separately.",
    motionPackPrivacy:
      "Files contain names, matching text, tags, rig binding, frames and an informational enabled-at-export flag, not keys or subtitles. Names and tags may be sensitive; check before sharing. Imports never inherit approval and are not uploaded.",
    motionPackExport: "Back up all saved motions",
    motionPackFile: "Select motion pack JSON (not a single-motion file)",
    motionPackLimits:
      "Up to 500 motions / 8 MiB per pack; 2 MiB per motion. Rig and REST must match.",
    motionPackInspect: "Run preflight again",
    motionPackImport: "Confirm import as new drafts",
    motionPackClear: "Cancel pending file",
    motionPackSummary:
      "Preflight: {new} new, {existing} existing, {conflict} ID conflicts. Nothing has been saved.",
    motionPackName: "Motion / ID",
    motionPackState: "Action",
    motionPackWarnings: "Review notes",
    motionPackNew: "New draft",
    motionPackExisting: "Identical; skip",
    motionPackIdConflict: "ID conflict; no overwrite",
    motionPackWasEnabled:
      "Pack says previously enabled; this is source information, not trusted approval.",
    motionPackAliases:
      "Potential duplicate matching text: {aliases}. Draft saving is allowed; review before enabling (includes disabled entries).",
    motionPackMaterial:
      "No matching text; pose material only, not eligible for translation.",
    motionPackReady:
      "Preflight complete. Only new drafts are added; current pose and existing approval remain unchanged.",
    motionPackChecking: "Checking the rig and local library…",
    motionPackCleared: "Cancelled. The library is unchanged.",
    motionPackConfirm:
      "Add {count} drafts without overwriting or enabling motions? Ensure you have permission to use the source. Review handshape, direction and meaning individually after import.",
    motionPackImported:
      "Added {imported} drafts; skipped {skipped} existing motions. Load, preview and confirm each from the list.",
    motionPackExported:
      "Started download of {count} saved motions. Check the downloaded file; unsaved edits are not included.",
    motionPackInvalid:
      "Not a valid v1 motion pack JSON. For one motion, use the single-motion import above.",
    motionPackEmpty:
      "The pack is empty, or there are no saved motions to back up.",
    motionPackTooLarge:
      "Limit exceeded: 8 MiB / 500 motions per pack, 2 MiB per motion. Nothing was saved.",
    motionPackDuplicateId:
      "Duplicate IDs within the pack are ambiguous; import was rejected.",
    motionPackInvalidStored:
      "Local entries are damaged or incompatible with the current model. No incomplete backup was produced; originals are preserved. Inspect those entries first.",
    motionPackConflict:
      "A local ID has different or damaged content. The entire import is blocked; nothing is overwritten. Use single-motion import to create a separate copy if needed.",
    motionPackStale:
      "The library changed and preflight expired. Run preflight again and review the list before importing.",
    motionPackLockUnavailable:
      "Cross-page write locking is unavailable. Batch import stopped; reopen the tool from the extension panel.",
    motionPackEncoding: "Not valid UTF-8 JSON. Convert the encoding and retry.",
    coverageTitle: "Vocabulary coverage",
    coverageHelpWorkflow:
      "Open Vocabulary coverage from the control panel. Paste text or import UTF-8 TXT / SRT / VTT to inspect unknown words, frequency and context. Editor and recorder buttons only prefill a name and matching text. Create and review a motion, enable it, then analyze again to verify it is active.",
    coverageIntro:
      "Find missing vocabulary in real text, then create and review motions. This does not generate signs or change existing poses.",
    coverageInput: "1 · Choose material",
    coverageTextLabel:
      "Paste text (one segment per line), or import UTF-8 subtitles",
    coverageLimits:
      "Limits: 256 KiB file, 50,000 characters, 1,000 segments, 2,000 characters per segment. SRT / WebVTT use subtitle cues.",
    coverageFormat: "Format",
    coveragePlainText: "Plain text · one segment per line",
    coverageImport: "Import file",
    coverageAnalyze: "Analyze current vocabulary",
    coverageClear: "Clear",
    coverageResults: "2 · Prioritize missing vocabulary",
    coverageMetricHelp:
      "Coverage = matched word tokens / (matched + unknown word tokens). Skipped function words and punctuation are excluded. This measures full-segment dictionary coverage, not sign accuracy, sentence meaning or completed playback.",
    coverageUnknownTitle: "Unknown words · most frequent first",
    coverageDraftHelp:
      "These are tokenizer suggestions. Check context before deciding whether a full phrase is needed. Tools only prefill the name and matching text: no automatic save, approval or claim that the current pose represents the word.",
    coverageWord: "Unknown word",
    coverageFrequency: "Occurrences / segments",
    coverageExamples: "Example segment numbers",
    coverageMake: "Create and review",
    coverageDetailsTitle: "3 · Inspect actual matches by segment",
    coverageDisplayLimit:
      "Shows up to 100 unknown words and 200 segments. Totals cover all input; export for complete results.",
    coverageIncludeText:
      "Include source text and segment details in export (may contain private data)",
    coverageExport: "Export JSON report",
    coveragePrivacy:
      "Analysis stays in this page's memory: no uploads or automatic saving. Closing the page discards it. Default exports omit source text but still contain unknown words; check before sharing.",
    coverageSummary:
      "Coverage {ratio} · {segments} segments · {matched} matched / {unknown} unknown / {skipped} skipped",
    coverageNoTokens: "N/A (no translatable tokens)",
    coverageTruncation:
      "{count} segments reach the runtime limit of 12 motions per segment. Some text may not play; inspect the remaining text below.",
    coverageOccurrences: "{count} occurrences / {segments} segments",
    coverageUniqueUnknown:
      "{count} distinct unknown words. Split or reconsider tokenization for very long words.",
    coverageNoUnknown:
      "No unknown words found. Sign meaning and motion still need human review.",
    coverageMatches: "Matched: {value}",
    coverageUnmatched: "Unknown: {value}",
    coverageSkipped: "Skipped: {value}",
    coverageRemaining: "Text remaining after playback limit: {value}",
    coverageCatalog:
      "Vocabulary: {signs} built-in signs / {aliases} lookup aliases / {chars} characters; {enabled} active custom; {drafts} inactive; {invalid} invalid or incompatible entries (originals kept).",
    coverageReady:
      "Paste or import, then analyze. The first analysis loads the model to validate custom motion bindings.",
    coverageLoading: "Validating model and library, then analyzing…",
    coverageDone:
      "Analysis complete. Create missing motions, review and enable them, then analyze again here.",
    coverageChanged:
      "Input changed. Analyze again; the old report cannot be exported.",
    coverageCatalogChanged:
      "Shared library changed. Analyze again for current coverage; the old report cannot be exported.",
    coverageImported:
      "Imported. Click Analyze; nothing is played or saved automatically.",
    coverageFailure: "Analysis did not complete: {detail}",
    coverageTooLarge:
      "Material exceeds size, segment count or segment length limits. Split it and try again.",
    coverageEmpty: "Provide at least one non-empty text segment.",
    coverageInvalidFormat:
      "Only TXT, SRT and WebVTT are supported. Select the matching format.",
    coverageInvalidSubtitles:
      "Invalid subtitles. Check blank lines, timestamps, start/end order and WebVTT header. Timing lines will not be counted as text.",
    coverageEncoding: "Not valid UTF-8. Convert the file encoding and retry.",
    coverageModelError:
      "Cannot validate the current model or shared library. Open from the extension, check model loading and retry. No incomplete fallback report was produced.",
    coverageOpenFailed:
      "Could not open the tool. Retry from the extension panel.",
    coveragePrefilled:
      "Name and matching text prefilled from coverage. The current pose is not a verified sign for this word. Create, save, preview and review it before enabling.",
    motionLibraryTitle: "Shared motion library · Phase 2",
    motionLibraryHelp:
      "Editor, recorder and avatar share radians and REST deltas. Saved drafts affect translation only after preview and explicit confirmation.",
    motionName: "Motion name (required)",
    motionTexts: "Matching text (comma separated; empty for pose-only assets)",
    motionTags: "Tags (comma separated)",
    motionNew: "New copy",
    motionNewHelp: "Current pose retained. Enter a new motion name.",
    motionSave: "Save draft",
    motionSaved: "Draft saved. Preview and confirm again before enabling.",
    motionLoad: "Load selected",
    motionLoaded:
      "Loaded. Imported files are not automatically saved or enabled. Review and save a draft.",
    motionChoose: "Choose a saved motion…",
    motionDraft: "Draft / disabled",
    motionEnabled: "Confirmed and enabled",
    motionPreview: "Preview current motion",
    motionPreviewHelp:
      "Using the same player as the avatar. Check handshape, direction, collisions and meaning. Save again after edits.",
    motionEnable: "Confirm for translation",
    motionDisable: "Disable selected",
    motionConfirm:
      "I have previewed the entire motion and checked its handshape, direction, collisions and meaning. This is my confirmation, not professional sign-language certification. Enable it?",
    motionEnabledHelp:
      "Enabled. Open avatars reload automatically; newly matched text will use this motion.",
    motionDisabledHelp:
      "Disabled; draft retained. Queued custom motions are cancelled in open avatars.",
    motionRefresh: "Refresh list",
    motionExport: "Download unified JSON",
    motionExportCode: "Export code (no save)",
    motionImport: "Import motion JSON",
    motionImportFormat: "Import format and units",
    motionFormat: "Unified · radians / REST delta",
    motionLegacyEditor: "Legacy editor delta · degrees (pose object only)",
    motionLegacyRecorder: "Legacy recorder frames.pose · degrees",
    motionLegacyAbsolute: "Legacy editor absolute rotation · radians",
    motionMigrate: "Migrate this page's old library",
    motionLegacyConfirm:
      "Legacy data has no rig binding. Continue only if it came from the current model with the selected format and units. Review each converted draft. Original local data will be retained. Continue?",
    motionMigrated:
      "Migrated {count} drafts; originals retained, none enabled. Repeating creates copies.",
    motionIgnored:
      "Skipped {count} damaged or rig-incompatible entries; original data retained.",
    motionFailure: "Not completed: {detail}",
    motionInvalidData: "Invalid motion format or parameters: {detail}",
    motionModelNotReady: "The model is not ready.",
    motionRigMismatch: "Skeleton or REST pose mismatch. Motion rejected.",
    motionStorageUnavailable:
      "Shared storage unavailable. Open this tool from the extension panel.",
    motionSelectFirst: "Save or select a motion first.",
    motionSaveFirst:
      "Motion changed. Save a draft and preview again before enabling.",
    motionPreviewFirst: "Preview this motion before confirming.",
    motionAliasConflict:
      "Empty text or alias conflicts with an enabled/built-in sign: {detail}. Choose a distinct phrase.",
    motionFileTooLarge: "File or entry count too large (2 MiB per file).",
    motionEditorSingleFrame:
      "The editor handles single poses. Open multi-frame clips in the recorder to avoid losing frames.",
    motionFrameLimit: "240-frame limit reached. Recording stopped.",
    motionFrameDuration: "Keyframe duration (seconds, 0.05–10)",
    motionUpdateFrame: "Update selected frame",
    motionHelpRig:
      "Godette uses standard Humanoid bone mappings and the available finger chains. The editor, recorder and floating avatar share one profile and REST pose.",
    motionHelpAxes:
      "X/Y/Z are bone-local axes, not fixed world directions. Exports use REST-relative radians; recorder bone sliders show absolute local radians. Do not assume the same axis direction for every bone.",
    motionHelpCreate:
      "Use the editor for single poses and the recorder for clips. Enter a name, matching text and tags, then save a draft. Leave matching text empty for pose material. Custom aliases cannot override built-in or enabled aliases.",
    motionHelpReview:
      "Save draft → Preview current motion → Check handshape, direction, collisions and meaning → Confirm for translation. Test the matching text from the control panel. Confirmation is not professional sign-language certification.",
    motionHelpFrames:
      "Select a timeline frame, edit bones and duration, then click Update selected frame. Add keyframes for new poses. Each frame is 0.05–10 seconds; up to 240 frames and 120 seconds total. Automatic recording samples every 0.3 seconds.",
    motionHelpUpdates:
      "Both tools and the avatar share local storage within one extension ID and browser profile. Enabling or disabling refreshes the avatar and cancels old playback queues. Saving again revokes approval. New copy keeps poses without overwriting the original motion.",
    motionHelpBackup:
      "Download unified JSON for backups; exporting does not save or enable. Imports are new draft copies requiring saving, preview and confirmation. Open multi-frame files in the recorder, not the single-pose editor. Back up before uninstalling or changing extension IDs.",
    motionHelpLegacy:
      "Migrating the old page library retains sb_gestures; repeating migration creates copies. Explicitly select degrees or absolute radians for old JSON files. Units are never guessed and code is never executed. Legacy data must use the current model and requires manual review.",
    motionHelpBinding:
      "Files are limited to 2 MiB. Incompatible bone/REST bindings, unknown bones and invalid values are rejected. This binding is not a full GLB or skin-weight fingerprint. Open tools from the extension popup; standalone localhost pages cannot share this storage. Reload the extension and reopen old tool tabs after updating.",
    motionHelpCollision:
      "Identify the exact motion and frame. Inspect elbows and wrists from front and side views in the tools. Edit and review only that motion; do not globally reverse axes or increase angles.",
    motionHelpCoverage:
      "Inspect matched motionIds and unmatched text. Unknown input does not interrupt current playback.",
    motionHelpCatalog:
      "Inspect enabled custom motion and invalid entry counts. Drafts do not participate in translation.",
    motionDurationInvalid: "Keyframe duration must be 0.05–10 seconds.",
    motionLoadingFailed: "Model loading failed: {detail}",
    name: "English",
    title: "SignBridge — Sign Language Translation",
    description:
      "Real-time video speech to sign language translation via 3D avatar",
    settings: "Settings",
    avatar: "Avatar",
    language: "Language",
    sourceLanguage: "Video Language",
    targetSignLanguage: "Sign Language",
    avatarStyle: "Avatar Style",
    avatarSize: "Avatar Size",
    avatarPosition: "Avatar Position",
    positionBottomRight: "Bottom Right",
    positionBottomLeft: "Bottom Left",
    positionTopRight: "Top Right",
    positionTopLeft: "Top Left",
    enableAutoDetect: "Auto-detect Video",
    enableSubtitles: "Show Subtitles",
    voiceVolume: "Voice Volume",
    speed: "Sign Speed",
    about: "About",
    start: "Start Translation",
    stop: "Stop Translation",
    loading: "Loading...",
    noVideo: "No video detected",
    error: "Error",
    errorNoVideo: "No video found on this page",
    ready: "Ready",
    translating: "Translating...",
    unavailable: "Unavailable on this page",
    inputPlaceholder: "Enter text for the avatar to sign...",
    send: "Send",
    sent: "Sent",
    audioOff: "Video audio: Off",
    audioOn: "Video audio: On",
    audioStopped: "Stopped",
    audioListening: "Recognizing...",
    audioStarting: "Capturing audio...",
    audioUnavailable: "Audio capture is unavailable on this page",
    audioCaptureFailed: "Audio capture failed",
    audioCloudKeyRequired: "Configure the cloud API key first",
    audioPermissionRequired: "Save ASR settings and allow the service origin",
    audioLocalUnavailable: "Deploy local Whisper first",
    asrSettings: "Audio recognition settings",
    asrTitle: "Video audio recognition",
    asrPurpose:
      "Choose local Whisper or cloud ASR to convert video audio into sign language motion.",
    asrProvider: "Recognition provider",
    asrLocal: "Local Whisper",
    asrCloud: "Cloud ASR",
    asrLocalSettings: "Local Whisper settings",
    asrLocalPrivacy:
      "The model and audio stay inside the extension. Video audio is not uploaded to an ASR service.",
    asrDeployLocal: "Deploy local Whisper",
    asrEndpoint: "Service endpoint",
    asrModel: "Model",
    asrModelTiny: "tiny (fastest, about 75 MB)",
    asrModelBase: "base (balanced, about 150 MB)",
    asrModelSmall: "small (more accurate, about 500 MB)",
    asrDeployHint:
      "Downloads and caches the model automatically. Python and a local service are not required.",
    asrDeployRequired: "The selected model is not deployed.",
    asrRequestingModelPermission: "Requesting model download access...",
    asrDeploying: "Downloading and initializing model: {progress}%",
    asrDeployReady: "Local model {model} is ready.",
    asrDeployFailed: "Local model deployment failed",
    asrCloudSettings: "Cloud ASR settings",
    asrCloudPrivacy:
      "Video audio chunks are sent to the configured service. Review its privacy and billing terms.",
    asrApiKey: "API Key",
    asrCommonSettings: "Common settings",
    asrLanguage: "Recognition language",
    asrChunkSeconds: "Audio chunk",
    asrTest: "Test connection",
    asrSave: "Save settings",
    asrPermissionDenied: "Network access to this service was not granted.",
    asrSaved: "Settings saved.",
    asrInvalidConfig:
      "Invalid settings: use HTTPS remotely or HTTP on loopback only. URL credentials are not allowed.",
    asrTesting: "Testing the recognition service...",
    asrTestPassed: "Connection test passed.",
    asrTestFailed: "Connection test failed",
    poseEditor: "Pose editor",
    recorder: "Recorder",
    help: "Help",
    tagline: "Accessible information",
    auto: "Auto detect",
    simplifiedChinese: "Chinese (Mandarin)",
    footer: "SignBridge — Making Information Accessible",
    signLanguageTypes: {
      csl: "Chinese Sign Language (CSL)",
      asl: "American Sign Language (ASL)",
      bsl: "British Sign Language (BSL)",
      jsl: "Japanese Sign Language (JSL)",
      ksl: "Korean Sign Language (KSL)",
      tsl: "Taiwan Sign Language (TSL)",
    },
    avatarStyles: {
      default: "Default",
      friendly: "Friendly",
      professional: "Professional",
      anime: "Anime Style",
    },
    voiceVolumeLevels: {
      low: "Low (video only)",
      medium: "Medium (video + sign)",
      high: "High (sign only)",
    },
  },
  ja: {
    ...DEMO_EN,
    ...SEMANTIC_JA,
    ...PRIVATE_EN,
    batchTitle: "今回の語彙追加リスト · 最大 8 件",
    batchManual: "語句を手動で追加（任意・分割の誤りを回避）",
    batchInvalidWord:
      "空白や記号だけではない、1～100 文字の語句を入力してください。",
    batchIntro:
      "分析結果から頻出の未対応語を追加します。下書きを保存し「動作の目視検証」で確認してから、編集・録画ツールで明示的に有効化してください。完全一致はデータの存在を示すだけで、手話の正確さを保証しません。このリストは動作の生成・変更・有効化を行いません。",
    batchAdd: "今回のリストに追加",
    batchRefresh: "対応状況を更新",
    batchExport: "進捗 JSON を保存",
    batchClear: "今回のリストを消去",
    batchClearConfirm:
      "リストだけを消去しますか？動作と比較基準は削除されません。",
    batchRemove: "リストから外す",
    batchState: "実際の対応状況 / 動作 ID",
    batchLoading: "現在の動作ライブラリを確認中…",
    batchEmpty: "リストは空です。素材を分析し、未対応語を追加してください。",
    batchMissing: "制作待ち · 完全一致なし",
    batchDraft: "候補を保存済み · 未有効化または完全一致なし",
    batchMatched: "完全一致あり · 手話の人による確認が必要",
    batchUnverified: "未検証です。再試行してください",
    batchSummary:
      "今回 {count}/{max} 件 · 完全一致 {matched} 件 · 無効な記録 {invalid} 件。動作の変更時に再確認します。",
    batchPrivacy:
      "明示的に追加した語だけを拡張機能内に保存し、再読み込み後も保持します。原文・例文は保存も送信もしません。リストは動作パックに含まれません。進捗ファイルには選択語と動作 ID が入るため共有前に確認してください。",
    batchFailure: "語彙リストの操作に失敗：{detail}",
    batchFull: "最大 8 件に達しました。一部を完了または削除してください。",
    batchInvalid:
      "リストのデータが無効です。元の記録は維持されます。明示的に消去して再作成できます。",
    batchLockUnavailable:
      "ページ間書き込みロックを利用できません。変更を停止しました。拡張機能パネルから開いてください。",
    reviewTitle: "動作の目視検証",
    reviewIntro:
      "保存済み動作を再生し、正面・右側・左側の固定画像を手動確認済みの基準と比較します。骨格や翻訳の有効化状態は変更しません。",
    reviewLimits:
      "一度に8動作まで、各動作は先頭と末尾を含む最大12キーフレームを抽出します。画像は目標姿勢のみで、全遷移・衝突・字幕文の再生・手話の意味は検証できません。目視確認が必要です。内蔵一覧はSIGNSのみで、CHARSは含みません。",
    reviewHelp:
      "パネル → 動作の目視検証。動作を選び再生または3方向撮影を行い、手形・方向・めり込みを確認して基準を保存します。次回の画像を並べて比較できます。動作データの変更は再確認が必要で、モデル・ブラウザ・描画環境が異なる場合は数値比較しません。基準保存は手話の正しさを保証せず、下書きや有効化状態も変えません。",
    reviewStorageHelp:
      "基準画像は拡張機能のIndexedDBに保存され、動作ライブラリとは別で最大100件 / 64 MiBです。動作パックには含まれません。削除前にPNGとJSONを保存してください（基準の再取込は未対応）。ネットワーク送信はありません。",
    reviewReload: "モデル再読込 / 再試行",
    reviewSelect: "1 · 動作を選択",
    reviewSearch: "名前・ID・状態で検索（選択は維持されます）",
    reviewCatalogCount:
      "{total}件 · 選択{count}/{max} · 無効レコード{invalid}件",
    reviewPlay: "全フレームを順番に再生",
    reviewCapture: "キーフレームを3方向から撮影",
    reviewStop: "停止",
    reviewPreview: "固定視点プレビュー",
    reviewView: "再生視点",
    reviewFront: "正面",
    reviewRight: "人物の右側",
    reviewLeft: "人物の左側",
    reviewPreviewHelp:
      "フローティング表示には影響しません。各再生はRESTから開始し、撮影後は正面に戻ります。",
    reviewResults: "2 · 目視確認と基準比較",
    reviewExport: "JSONレポートを保存",
    reviewBuiltin: "内蔵 · 目視確認が必要",
    reviewEnabled: "カスタム · 有効",
    reviewDraft: "カスタム · 下書き",
    reviewLoading: "実際のモデル・骨格・動作ライブラリを読込中…",
    reviewReady: "{total}動作を読込完了。選択して再生または撮影してください。",
    reviewFailure: "検証失敗：{detail}",
    reviewCatalogChanged:
      "ライブラリが変わったため結果は無効です。選択し直して撮影してください。既存の基準は自動上書きしません。",
    reviewPlaying: "再生 {index}/{total}：{name}",
    reviewCapturing: "撮影 {index}/{total}：{name}",
    reviewFinished:
      "{count}動作完了、構造エラー{failures}件。目視確認が必要です。",
    reviewCancelled:
      "停止しました。未完了の撮影結果は破棄し、基準は変更しません。",
    reviewDiagnostics:
      "{frames}フレーム / {duration}秒、{bones}骨格。画像の行：{indices}。未撮影{omitted}フレーム。",
    reviewSheetOrder:
      "各行は左から正面 → 人物の右側 → 左側。行はフレーム順です。PNGを保存して拡大確認できます。",
    reviewCurrent: "現在の画像",
    reviewBaseline: "確認済みの基準画像",
    reviewNoBaseline: "基準未保存。動作を確認してから保存してください。",
    reviewCompared:
      "基準日時{date}。RGB差分>16の画素：{ratio}%、平均差分{mean}/255。参考値であり手話の正しさや衝突を保証しません。",
    reviewMotionChanged:
      "動作データ（時間や名称を含む）が変わりました。旧基準は保持し、数値比較を停止しました。再確認してください。",
    reviewIncompatible:
      "モデル・骨格・ブラウザ・描画環境が異なります。数値比較は行わず、旧画像は参考用です。",
    reviewUnavailable:
      "基準読込 / 比較失敗：{detail}。現在の画像は保存可能です。基準保存で再試行します。",
    reviewSaveBaseline: "目視基準を保存 / 置換",
    reviewDeleteBaseline: "この基準を削除",
    reviewDownloadImage: "現在のPNGを保存",
    reviewSaveConfirm:
      "「{name}」を3方向から確認しましたか？既存の目視基準を置換します。翻訳の有効化や手話の正しさの認証は行いません。",
    reviewDeleteConfirm:
      "「{name}」の目視基準を削除しますか？動作自体は削除しません。",
    reviewSaved:
      "目視基準を保存しました。動作データと翻訳状態は変更していません。",
    reviewDeleted: "目視基準を削除しました。動作データは変更していません。",
    reviewStorageError:
      "基準ストレージにアクセスできません。空き容量を確認し、拡張機能パネルから開き直してください。",
    reviewStorageFull:
      "基準の上限（100件 / 64 MiB）です。画像を保存して不要な基準を削除してください。",
    reviewBaselineChanged:
      "別ページで基準が更新されました。上書きせず停止しました。再撮影して確認してください。",
    reviewModelError:
      "モデル読込失敗または寸法が無効です。再ビルドして再試行してください。",
    reviewMissingBones: "手話に必要な骨格が不足しているため停止しました。",
    reviewRenderError:
      "描画失敗またはWebGL接続が失われました。停止して再読込してください。",
    reviewInvalidSamples: "キーフレーム抽出設定が無効です。",
    reviewImageMismatch:
      "基準画像が破損しているか寸法が異なるため比較できません。",
    motionPackTitle: "動作ライブラリのバックアップ / 一括取込",
    motionPackHelp:
      "現在のモデルに対応する保存済みカスタム動作をすべて書き出します。未保存の編集や内蔵辞書は含みません。ファイル選択は事前確認のみです。同じ ID・内容はスキップし、内容が異なる場合は一括取込全体を停止します。新しい動作は下書きとして追加し、個別に読込・プレビュー・確認してください。",
    motionPackPrivacy:
      "ファイルには名前、照合文字列、タグ、骨格情報、フレーム、書出時の有効フラグのみ含まれ、キーや字幕は含まれません。名前やタグの個人情報を共有前に確認してください。承認記録は引き継がず、ファイルもアップロードしません。",
    motionPackExport: "保存済みの全動作をバックアップ",
    motionPackFile: "動作パック JSON を選択（単一動作ファイルではありません）",
    motionPackLimits:
      "1 パック最大 500 動作・8 MiB、1 動作 2 MiB。骨格と REST の一致が必要です。",
    motionPackInspect: "再度事前確認",
    motionPackImport: "新規下書きとして取込を確認",
    motionPackClear: "取込待ちファイルをキャンセル",
    motionPackSummary:
      "事前確認：新規 {new}、既存 {existing}、ID 競合 {conflict}。まだ保存していません。",
    motionPackName: "動作 / ID",
    motionPackState: "処理",
    motionPackWarnings: "確認事項",
    motionPackNew: "新規下書き",
    motionPackExisting: "同一内容・スキップ",
    motionPackIdConflict: "ID 競合・上書き禁止",
    motionPackWasEnabled:
      "パック上では以前有効。ただし出所の情報であり、信頼された承認ではありません。",
    motionPackAliases:
      "照合文字列が重複する可能性：{aliases}。下書き保存は可能ですが、有効化前に確認してください（無効な動作も含む）。",
    motionPackMaterial:
      "照合文字列なし。ポーズ素材専用で、翻訳には有効化できません。",
    motionPackReady:
      "事前確認が完了しました。新規下書きのみ追加し、現在のポーズと既存動作の承認は変更しません。",
    motionPackChecking: "骨格とローカルライブラリを確認中…",
    motionPackCleared: "キャンセルしました。ライブラリは変更していません。",
    motionPackConfirm:
      "{count} 件の下書きを追加します。上書きや自動有効化はしません。利用権限を確認し、取込後に手形・向き・意味を個別に確認してください。続行しますか？",
    motionPackImported:
      "下書き {imported} 件を追加、既存 {skipped} 件をスキップしました。一覧から個別に読込・プレビュー・確認してください。",
    motionPackExported:
      "保存済み {count} 件のダウンロードを開始しました。結果を確認してください。未保存の編集は含みません。",
    motionPackInvalid:
      "有効な v1 動作パック JSON ではありません。単一動作には上の動作 JSON 取込を使ってください。",
    motionPackEmpty:
      "パックが空か、バックアップできる保存済み動作がありません。",
    motionPackTooLarge:
      "上限超過：1 パック 8 MiB / 500 動作、1 動作 2 MiB。保存していません。",
    motionPackDuplicateId:
      "パック内に重複 ID があり、動作を特定できないため取込を拒否しました。",
    motionPackInvalidStored:
      "ローカル記録が破損しているか現在のモデルに非対応です。不完全なバックアップは作成せず、元データを保持します。先に該当記録を確認してください。",
    motionPackConflict:
      "同じ ID のローカル内容が異なるか破損しています。全体の取込を停止し、上書きしません。必要なら単一動作の取込でコピーを作成してください。",
    motionPackStale:
      "ライブラリが変更され、事前確認が失効しました。再度事前確認し、一覧を確認してから取り込んでください。",
    motionPackLockUnavailable:
      "ページ間の書込ロックが利用できません。一括取込を停止しました。拡張パネルからツールを開き直してください。",
    motionPackEncoding:
      "有効な UTF-8 JSON ではありません。文字コードを変換して再試行してください。",
    coverageTitle: "語彙カバー率分析",
    coverageHelpWorkflow:
      "パネルから語彙カバー率分析を開き、文章または UTF-8 TXT / SRT / VTT を入力して未対応語の頻度と文脈を確認します。編集・録画ツールには名前と一致文字列だけが入力されます。動作の作成・確認・有効化後に再分析し、反映を確認してください。",
    coverageIntro:
      "実際の文章から不足する語彙を探し、動作を作成・確認します。手話の自動生成や既存ポーズの変更は行いません。",
    coverageInput: "1 · 分析する素材",
    coverageTextLabel:
      "文章を貼り付け（1行1区間）、または UTF-8 字幕を読み込み",
    coverageLimits:
      "上限：ファイル256 KiB、50,000文字、1,000区間、1区間2,000文字。SRT / WebVTT は字幕単位で分析します。",
    coverageFormat: "形式",
    coveragePlainText: "テキスト · 1行1区間",
    coverageImport: "ファイルを読み込む",
    coverageAnalyze: "現在の語彙を分析",
    coverageClear: "クリア",
    coverageResults: "2 · 追加する語彙の優先順位",
    coverageMetricHelp:
      "カバー率 = 一致した分割語数 ÷（一致 + 未対応の分割語数）。省略した機能語・句読点は除外します。辞書のカバー率であり、手話の正確さ・文意・再生完了を保証する値ではありません。",
    coverageUnknownTitle: "未対応の語 · 頻度順",
    coverageDraftHelp:
      "分割結果を文脈と照合し、句全体が必要か判断してください。ツールには名前と一致文字列のみ入力します。自動保存・有効化はせず、現在のポーズがその語の正しい手話とは限りません。",
    coverageWord: "未対応の語",
    coverageFrequency: "回数 / 区間数",
    coverageExamples: "例文の区間番号",
    coverageMake: "作成と確認",
    coverageDetailsTitle: "3 · 区間ごとの一致結果",
    coverageDisplayLimit:
      "未対応語は100件、区間は200件まで表示します。集計は全入力が対象です。全結果はエクスポートできます。",
    coverageIncludeText:
      "原文と区間明細をエクスポートに含める（個人情報に注意）",
    coverageExport: "JSON レポートを出力",
    coveragePrivacy:
      "分析はページのメモリ内のみで行い、送信・自動保存しません。閉じると破棄されます。既定の出力は原文を除外しますが未対応語を含むため、共有前に確認してください。",
    coverageSummary:
      "カバー率 {ratio} · {segments} 区間 · 一致 {matched} / 未対応 {unknown} / 省略 {skipped}",
    coverageNoTokens: "対象外（翻訳対象語なし）",
    coverageTruncation:
      "{count} 区間が1区間12動作の再生上限に達しています。一部は再生されない可能性があるため、残りの文章を確認してください。",
    coverageOccurrences: "{count} 回 / {segments} 区間",
    coverageUniqueUnknown:
      "未対応語は {count} 種類です。長すぎる語は分割や文脈を再確認してください。",
    coverageNoUnknown:
      "未対応語はありません。手話の意味と動作は人による確認が必要です。",
    coverageMatches: "一致：{value}",
    coverageUnmatched: "未対応：{value}",
    coverageSkipped: "省略：{value}",
    coverageRemaining: "再生上限以降の文章：{value}",
    coverageCatalog:
      "語彙：内蔵 {signs} 件 / 別名 {aliases} 件 / 文字 {chars} 件。有効な独自動作 {enabled}、無効 {drafts}、不正・非互換 {invalid}（元データは保持）。",
    coverageReady:
      "貼り付け・読み込み後に分析してください。初回はモデルを読み込み、独自動作の互換性を確認します。",
    coverageLoading: "モデルと動作ライブラリを確認し、分析しています…",
    coverageDone:
      "分析完了。不足する動作を作成し、確認・有効化してから再分析してください。",
    coverageChanged:
      "素材が変更されました。再分析してください。古いレポートは出力できません。",
    coverageCatalogChanged:
      "ライブラリが変更されました。再分析してください。古いレポートは出力できません。",
    coverageImported:
      "読み込み完了。分析をクリックしてください。自動再生・保存はしません。",
    coverageFailure: "分析できませんでした：{detail}",
    coverageTooLarge:
      "容量・区間数・区間長の上限を超えています。分割して再試行してください。",
    coverageEmpty: "空でない文章を入力してください。",
    coverageInvalidFormat:
      "TXT、SRT、WebVTT のみ対応しています。正しい形式を選択してください。",
    coverageInvalidSubtitles:
      "字幕形式が不正です。空行、時刻、開始・終了順序、WebVTT ヘッダーを確認してください。時刻行を本文として集計しません。",
    coverageEncoding:
      "UTF-8 ではありません。文字コードを変換して再試行してください。",
    coverageModelError:
      "モデルまたは共有ライブラリを確認できません。拡張から開き、モデル読み込みを確認して再試行してください。不完全な集計には切り替えません。",
    coverageOpenFailed:
      "ツールを開けませんでした。拡張パネルから再試行してください。",
    coveragePrefilled:
      "分析結果から名前と一致文字列を入力しました。現在のポーズはこの語の検証済み手話ではありません。作成・保存・プレビュー・確認してから有効化してください。",
    motionLibraryTitle: "共有動作ライブラリ · 第2段階",
    motionLibraryHelp:
      "エディター・録画ツール・アバターはラジアンと REST 差分を共有します。下書きはプレビューと確認後に翻訳へ使用します。",
    motionName: "動作名（必須）",
    motionTexts: "対応する文字（カンマ区切り・姿勢素材のみなら空欄）",
    motionTags: "タグ（カンマ区切り）",
    motionNew: "新しいコピー",
    motionNewHelp: "現在の姿勢を保持します。新しい動作名を入力してください。",
    motionSave: "下書き保存",
    motionSaved:
      "下書きを保存しました。プレビューと確認後に有効にしてください。",
    motionLoad: "選択を読み込む",
    motionLoaded:
      "読み込みました。インポートは自動保存・有効化されません。確認後に下書きを保存してください。",
    motionChoose: "保存済みの動作を選択…",
    motionDraft: "下書き / 無効",
    motionEnabled: "確認済み / 有効",
    motionPreview: "現在の動作をプレビュー",
    motionPreviewHelp:
      "アバターと同じ再生処理です。手形・方向・貫通・意味を確認し、変更後は再保存してください。",
    motionEnable: "確認して翻訳に使用",
    motionDisable: "選択した動作を無効化",
    motionConfirm:
      "全動作をプレビューし、手形・方向・貫通・意味を確認しました。専門家による手話認証ではありません。有効にしますか？",
    motionEnabledHelp:
      "有効化しました。開いているアバターに自動反映し、新しく一致した文字に使用します。",
    motionDisabledHelp:
      "無効化しました。下書きを保持し、アバターの待機中の独自動作を停止します。",
    motionRefresh: "一覧更新",
    motionExport: "統一 JSON をダウンロード",
    motionExportCode: "コード出力（保存なし）",
    motionImport: "動作 JSON をインポート",
    motionImportFormat: "インポート形式と単位",
    motionFormat: "統一形式 · ラジアン / REST 差分",
    motionLegacyEditor: "旧エディター差分 · 度（姿勢オブジェクトのみ）",
    motionLegacyRecorder: "旧録画 frames.pose · 度",
    motionLegacyAbsolute: "旧エディター絶対角 · ラジアン",
    motionMigrate: "このページの旧ライブラリを移行",
    motionLegacyConfirm:
      "旧データにはモデル情報がありません。現在のモデルで正しい形式・単位である場合のみ続行し、変換後は各動作を確認してください。元データは削除しません。続行しますか？",
    motionMigrated:
      "{count} 件の下書きを移行しました。元データを保持し、未有効です。再実行するとコピーを作成します。",
    motionIgnored:
      "破損またはモデル不一致の {count} 件を除外しました。元データは保持します。",
    motionFailure: "未完了：{detail}",
    motionInvalidData: "動作形式またはパラメーターが無効：{detail}",
    motionModelNotReady: "モデルの読み込みが完了していません。",
    motionRigMismatch: "骨格または REST 姿勢が一致しないため、適用しません。",
    motionStorageUnavailable:
      "共有ストレージを利用できません。拡張機能のパネルから開いてください。",
    motionSelectFirst: "動作を保存または選択してください。",
    motionSaveFirst: "動作が変更されました。再保存とプレビューが必要です。",
    motionPreviewFirst: "有効化の前にプレビューしてください。",
    motionAliasConflict:
      "対応文字が空欄、または既存の動作と重複：{detail}。別の語句を指定してください。",
    motionFileTooLarge: "ファイルまたは項目数が上限を超えています（2 MiB）。",
    motionEditorSingleFrame:
      "エディターは単一姿勢専用です。複数フレームは録画ツールで開いてください。",
    motionFrameLimit: "240 フレームに達したため録画を停止しました。",
    motionFrameDuration: "フレーム時間（秒、0.05–10）",
    motionUpdateFrame: "選択フレームを更新",
    motionHelpRig:
      "Godette は標準 Humanoid ボーンと利用可能な指のボーンチェーンを使います。エディター、録画ツール、アバターは同じ profile と REST ポーズを共有します。",
    motionHelpAxes:
      "X/Y/Z はボーンのローカル軸で、固定の世界方向ではありません。出力は REST 差分ラジアン、録画ツールのスライダーは絶対ローカルラジアンです。全ボーンを同じ軸方向とみなさないでください。",
    motionHelpCreate:
      "単一ポーズはエディター、複数フレームは録画ツールで作ります。名前、照合テキスト、タグを入力して下書きを保存します。照合テキストが空なら素材として保存できます。既存の照合語は上書きできません。",
    motionHelpReview:
      "下書きを保存 → 現在の動作をプレビュー → 手形・方向・貫通・意味を確認 → 翻訳に有効化。コントロールパネルから照合語を入力して検証してください。この確認は手話の専門認証ではありません。",
    motionHelpFrames:
      "タイムラインのフレームを選択し、ボーンと時間を編集して「選択フレームを更新」を押します。新しい姿勢にはキーフレームを追加します。1 フレーム 0.05–10 秒、最大 240 フレーム、合計 120 秒。自動録画は 0.3 秒間隔です。",
    motionHelpUpdates:
      "両ツールとアバターは同じ拡張 ID・ブラウザープロファイルの保存領域を共有します。有効化・無効化でアバターと待ち行列を更新します。再保存すると承認を解除します。新しいコピーは元の動作を上書きしません。",
    motionHelpBackup:
      "統一 JSON をダウンロードしてバックアップします。エクスポートだけでは保存・有効化されません。インポートは新しい下書きとして再保存・確認が必要です。複数フレームは録画ツールで開きます。拡張の削除や ID 変更前にバックアップしてください。",
    motionHelpLegacy:
      "旧ライブラリの移行は sb_gestures を残し、再実行するとコピーを作ります。旧 JSON の度数・絶対ラジアン形式を明示してください。単位を推測せず、コードも実行しません。現在のモデル用データであることを確認し、必ずプレビューしてください。",
    motionHelpBinding:
      "ファイル上限は 2 MiB。不一致のボーン/REST、未知のボーン、不正な値は拒否します。これは GLB 全体やスキンの指紋ではありません。拡張パネルからツールを開いてください。localhost のページとは共有できません。更新後は拡張を再読込し、古いツールタブを開き直します。",
    motionHelpCollision:
      "該当する動作とフレームを特定し、正面と側面から肘・手首を確認します。その動作のみ修正して再確認し、全体の軸反転や一括角度変更を避けてください。",
    motionHelpCoverage:
      "一致した motionIds と未一致テキストを確認します。未収録の入力は現在の再生を中断しません。",
    motionHelpCatalog:
      "有効なカスタム動作数と不正な記録数を確認します。下書きは翻訳されません。",
    motionDurationInvalid: "時間は 0.05–10 秒にしてください。",
    motionLoadingFailed: "モデル読み込み失敗：{detail}",
    name: "日本語",
    title: "SignBridge — 手話翻訳",
    description: "動画の音声をリアルタイムで手話に翻訳、3Dアバターで表示",
    settings: "設定",
    avatar: "アバター",
    language: "言語",
    sourceLanguage: "動画の言語",
    targetSignLanguage: "手話の種類",
    avatarStyle: "アバタースタイル",
    avatarSize: "アバターサイズ",
    avatarPosition: "アバター位置",
    positionBottomRight: "右下",
    positionBottomLeft: "左下",
    positionTopRight: "右上",
    positionTopLeft: "左上",
    enableAutoDetect: "動画を自動検出",
    enableSubtitles: "字幕を表示",
    voiceVolume: "音声音量",
    speed: "手話の速度",
    about: "について",
    start: "翻訳開始",
    stop: "翻訳停止",
    loading: "読み込み中...",
    noVideo: "動画が見つかりません",
    error: "エラー",
    errorNoVideo: "ページに動画が見つかりません",
    ready: "準備完了",
    translating: "翻訳中...",
    unavailable: "このページでは利用できません",
    inputPlaceholder: "手話にするテキストを入力...",
    send: "送信",
    sent: "送信済み",
    audioOff: "動画音声：オフ",
    audioOn: "動画音声：オン",
    audioStopped: "停止中",
    audioListening: "認識中...",
    audioStarting: "音声を取得中...",
    audioUnavailable: "このページでは音声を取得できません",
    audioCaptureFailed: "音声の取得に失敗しました",
    audioCloudKeyRequired: "クラウド API Key を設定してください",
    audioPermissionRequired: "ASR 設定を保存して接続先を許可してください",
    audioLocalUnavailable: "先にローカル Whisper を導入してください",
    asrSettings: "音声認識設定",
    asrTitle: "動画音声認識",
    asrPurpose:
      "ローカル Whisper またはクラウド ASR で動画音声を手話動作に変換します。",
    asrProvider: "認識方式",
    asrLocal: "ローカル Whisper",
    asrCloud: "クラウド ASR",
    asrLocalSettings: "ローカル Whisper 設定",
    asrLocalPrivacy:
      "モデルと音声は拡張機能内で処理され、動画音声は認識サービスへ送信されません。",
    asrDeployLocal: "ローカル Whisper を導入",
    asrEndpoint: "サービス URL",
    asrModel: "モデル",
    asrModelTiny: "tiny（最速、約 75 MB）",
    asrModelBase: "base（バランス、約 150 MB）",
    asrModelSmall: "small（高精度、約 500 MB）",
    asrDeployHint:
      "クリックするとモデルを自動でダウンロードして保存します。Python やローカルサービスは不要です。",
    asrDeployRequired: "選択したモデルはまだ導入されていません。",
    asrRequestingModelPermission: "モデルのダウンロード権限を確認中...",
    asrDeploying: "モデルをダウンロードして初期化中：{progress}%",
    asrDeployReady: "ローカルモデル {model} の準備が完了しました。",
    asrDeployFailed: "ローカルモデルの導入に失敗しました",
    asrCloudSettings: "クラウド ASR 設定",
    asrCloudPrivacy:
      "動画音声は設定したサービスへ送信されます。プライバシーと料金を確認してください。",
    asrApiKey: "API Key",
    asrCommonSettings: "共通設定",
    asrLanguage: "認識言語",
    asrChunkSeconds: "音声チャンク",
    asrTest: "接続テスト",
    asrSave: "設定を保存",
    asrPermissionDenied: "このサービスへのネットワーク権限がありません。",
    asrSaved: "設定を保存しました。",
    asrInvalidConfig:
      "リモートURLにはHTTPSが必要です。HTTPはループバックのみ許可し、URLの認証情報は禁止します。",
    asrTesting: "認識サービスをテストしています...",
    asrTestPassed: "接続テストに成功しました。",
    asrTestFailed: "接続テストに失敗しました",
    poseEditor: "ポーズ編集",
    recorder: "録画ツール",
    help: "ヘルプ",
    tagline: "情報をアクセシブルに",
    auto: "自動検出",
    simplifiedChinese: "中国語（標準語）",
    footer: "SignBridge — 情報をアクセシブルに",
    signLanguageTypes: {
      csl: "中国手話 (CSL)",
      asl: "アメリカ手話 (ASL)",
      bsl: "イギリス手話 (BSL)",
      jsl: "日本手話 (JSL)",
      ksl: "韓国手話 (KSL)",
    },
    avatarStyles: {
      default: "デフォルト",
      friendly: "フレンドリー",
      professional: "プロフェッショナル",
      anime: "アニメ風",
    },
  },
};

const FALLBACK_LOCALE = "en";

let _currentLocale = null;

export function getLocale() {
  return _currentLocale || navigator.language || FALLBACK_LOCALE;
}

export function setLocale(locale) {
  _currentLocale = locale;
}

export function t(key, replacements = {}) {
  const locale = getLocale();
  // Try exact match, then language-only (e.g., 'zh' from 'zh-CN')
  let dict =
    LOCALES[locale] ||
    LOCALES[locale.split("-")[0]] ||
    LOCALES[FALLBACK_LOCALE];

  const keys = key.split(".");
  let value = dict;
  for (const k of keys) {
    if (value && typeof value === "object") value = value[k];
    else {
      value = undefined;
      break;
    }
  }

  if (value === undefined) {
    // Fallback chain
    dict = LOCALES[FALLBACK_LOCALE];
    value = dict;
    for (const k of keys) {
      if (value && typeof value === "object") value = value[k];
      else break;
    }
  }

  if (typeof value !== "string") return key;

  // Simple replacements
  return value.replace(/\{(\w+)\}/g, (_, k) => replacements[k] ?? `{${k}}`);
}

export function getSupportedLocales() {
  return Object.entries(LOCALES).map(([code, data]) => ({
    code,
    name: data.name,
  }));
}

export { LOCALES };
