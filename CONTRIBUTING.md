# 贡献指南

感谢你改进 SignBridge。项目欢迎代码、手语动作、站点适配、测试、文档和无障碍体验反馈。

## 开始开发

```bash
git clone https://github.com/feifei9126/signbridge.git
cd signbridge/signbridge
npm install
npm run build
```

在 `chrome://extensions` 开启开发者模式，加载 `signbridge/dist/`。修改源码后运行 `npm run build` 并重新加载扩展。

## 提交改动

1. 先创建 Issue 描述问题、复现步骤或拟新增词条。
2. 从最新 `main` 创建分支。
3. 只修改解决该问题需要的文件。
4. 为行为变化添加或更新测试。
5. 运行 `npm run verify`。
6. 提交 Pull Request，并填写验证结果和截图。

提交信息使用：

```text
type(scope): description
```

常用类型包括 `feat`、`fix`、`docs`、`test`、`refactor` 和 `chore`。

## 贡献手语动作

请先阅读[动作制作指南](docs/gesture-authoring.md)。动作 Pull Request 至少应包含：

- 唯一 `csl_` ID、gloss、匹配文本和标签。
- 手形、位置、朝向、运动等元数据。
- 使用姿势编辑器或录制器导出的 REST 增量动作。
- 正面与侧面的验证截图。
- 动作参考和授权说明。
- 对词典数量、动作格式或匹配行为的测试。

禁止提交未经授权的视频、模型、纹理、音频或由受限素材直接提取的动作资产。

## 代码要求

- 使用 ES Module，不引入 CommonJS。
- UI 文案通过 `src/i18n/locales.js` 管理。
- Manifest V3 权限保持最小化。
- Three.js 几何体、材质和纹理必须释放。
- 动画循环退出时必须调用 `cancelAnimationFrame()`。
- 不直接修改 `dist/`，它由构建生成且不会提交。

## 报告 Bug

请提供网站地址或最小复现页、Chrome 版本、操作步骤、预期与实际结果、以 `[SB]` 开头的控制台日志，以及不含敏感信息的截图。不要在 Issue 中粘贴 API Key、Token 或私人视频内容。

## 行为与审核

手语准确性相关改动需要专业使用者或可靠参考进行复核。维护者可能要求拆分过大的 Pull Request，或补充动作侧面截图和回归测试。
