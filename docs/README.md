# 黑客松展示页

## 当前公开下载：1.0.6（2026-10-27）

当前默认分支为 `codex/t08-avatar-demo`，不再是下文历史记录中的 main。Pages 若使用分支发布，选择当前默认分支的 `/docs`。下载入口现使用版本化 T08 + 83 条动作公开包，JSON、授权范围和复现步骤见[发布记录](public-motion-release-20261027.md)。旧 ZIP 与日期记录保留，不能替代当前版本。

含动作包使用 `cd signbridge && npm ci && npm run build:motion`；再用 `npm run package:motion -- --build dist --output /absolute/new/demo.zip` 生成确定性 ZIP、SHA-256 和逐文件清单。不要把普通词库构建当作含动作发布包，也不要从 local-data 自动复制后续私有库。

> 2026-10-19更新：当前构建配置、词边界和语义禁播行为以[审计整改说明](audit-remediation-20261019.md)为准；下文按日期保留历史记录。普通构建不再自动读取本地T08／拟合动作。

## 手语模型训练工程总报告

完整数据准备、重建、试修、训练、评估、失败和复跑入口见[手语训练全过程总报告](training-master-report.md)。该报告登记9份本地可核验研究权重及1轮尚未下载的远端训练；模型、视频和证据快照留在本地 `local-data/training-master-report-20261010-v1/`，其中 `index.html` 提供全文阅读、证据检索和调用命令，`RESUME-CONTEXT.md` 供后续接手。报告区分研究动作编码与正式文字到手语生成，并校正历史比较口径。

2026-10-10 新增教学资料的95个视频文件已完成来源清点和标注参考交付，详见[教学视频学习与手部参考](sign-tutorial-reference.md)。本地查阅页为 `local-data/tutorial-hand-reference-20261010-v2/review.html`，与既有训练结果分开记录。

本目录是 SignBridge 的静态演示网页，用 GitHub Pages 从 `main` 分支的 `/docs` 目录发布。配置 Pages 后的公开地址：<https://feifei9126.github.io/signbridge/>。

页面提供实际操作录屏、功能说明和预构建 Chrome 扩展下载。它自身不是扩展运行环境；实时字幕、标签页音频捕获和 3D 浮窗需要先在 Chrome 中加载扩展。

## 本地预览

在仓库根目录运行 `python3 -m http.server 8000 --directory docs`，打开 <http://localhost:8000/>。网站不需要 npm 或前端构建。

## 更新演示视频与下载包

原始视频来自用户提供的素材文件夹；为方便网页播放，已经转换为 H.264/AAC，分辨率为 1280 × 720。重新转换的例子：

```bash
ffmpeg -i /path/to/source.mp4 -vf 'scale=-2:720' -c:v libx264 -preset veryfast -crf 29 -pix_fmt yuv420p -c:a aac -b:a 80k -movflags +faststart docs/assets/signbridge-demo.mp4
```

扩展源码更新后，重新构建并替换网页下载包，保持包内 `manifest.json` 在 ZIP 根目录：

```bash
cd signbridge
npm ci
npm run build
cd dist
zip -FS -qr ../../docs/assets/signbridge-chrome-extension.zip . -x '*.DS_Store'
```

页面素材与包可公开下载。上传新素材前确认有公开展示和分发权限；录屏中若有个人隐私需先编辑。若不方便公开 ZIP，移除下载按钮并改为仓库构建说明。

## 首次发布

将本次提交推送到 GitHub 后，在仓库 Settings → Pages 中选择 Deploy from a branch、`main` 分支与 `/docs` 目录并保存。等待 GitHub 的 Pages 构建完成，再检查页面、视频和 ZIP 的公网访问。预期地址不表示已经发布成功。

## 离线演示

可以直接打开本目录的 `index.html`；页面样式、脚本、截图、视频和扩展包均在本地，不依赖外部字体或 JavaScript CDN。GitHub 链接和扩展首次下载 Whisper 模型仍需要网络。

本次扩展包由源码提交 `8510c788ebdfb1e7f4932f900ebf597e80219cbf` 构建（2026-09-27）；演示站点变更不改变扩展运行代码。

## 2026-10-18 语义研究版发布

主页新增语义研究版下载区。完整工具包可在本机重新训练并运行受限中文角色解析，另提供轻量客户端和SHA256清单；详见 [研究版使用说明](research-demo.md)。这不是在线中国手语翻译服务，不含原始视频、完整动作或预训练权重。原有动作播放包保持原样。

- [2026-10-19 功能精简（本地1.0.4）](feature-simplification-20261019.md)：普通弹窗、统一设置与研究工作台。
- [2026-10-19 现有资源优化（本地1.0.5）](existing-resources-optimization-20261019.md)：作用域对照、旧视频候选单元和稳定性基准。
