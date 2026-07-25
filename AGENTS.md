# SignBridge 项目 AI 编程指南

## 仓库布局
- `signbridge/` — 浏览器插件主项目
  - `src/` — 源代码（avatar/, background/, content/, i18n/, popup/, utils/）
  - `dist/` — 构建输出（不提交）
  - `scripts/` — 构建脚本
  - `node_modules/` — 依赖（不提交）

## 构建和测试命令
- 构建：`cd signbridge && npm run build`
- 持续构建：`cd signbridge && npm run dev`
- Lint 检查：`cd signbridge && npm run lint`
- 格式检查：`cd signbridge && npx prettier --check src/`
- 完整验证：`cd signbridge && npm run build && npm run lint && npx prettier --check src/`

## 完成定义
一个任务完成，当且仅当以下全部通过：
1. `npm run build` 退出码为 0
2. 涉及改动的文件 `npm run lint` 退出码为 0
3. 涉及改动的文件 `npx prettier --check src/` 退出码为 0
4. 新功能或 bug 修复包含对应测试
5. 用户可见改动更新了文档
6. 改动已提交，提交信息格式：`type(scope): description`

## 代码规范
- 使用 ES Module（import/export），不使用 CommonJS
- Three.js 用于 3D 渲染，通过 iframe 隔离 DOM
- 遵循 Manifest V3 扩展规范，权限声明最小化
- 所有 UI 字符串通过 `src/i18n/locales.js` 管理，不硬编码
- 文件命名使用 kebab-case
- 新增 Three.js 模型/纹理用完后必须调用 `.dispose()` 释放 GPU 内存
- 动画循环退出的同时调用 `cancelAnimationFrame()`

## 构建发布注意事项
- `dist/` 和 `node_modules/` 不提交到 Git，确认 .gitignore 已覆盖
- `scripts/build.mjs` 中从 `node_modules/three` 复制文件时，同步修改 import 路径为相对路径（`from 'three'` → `from '../../three.module.js'`）

## 手语数据扩展规范
- 使用项目工具函数 `deg()` `frame()` `seq()` 添加新词汇，不手动构造对象
- 词汇 ID 前缀：`csl_`（中国手语）、`asl_`（美国手语）
- `duration` 以秒为单位，默认 `0.3`
- `tags` 标注分类（greeting, question, daily...）
- 新增词汇后验证构建通过

## 国际化规范
- 键名使用 camelCase，按功能模块分组（avatar, popup, background...）
- 新增语言先在 `LOCALES` 注册所有翻译键值对

## 遇到阻碍时
- 同一个错误连续出现 3 次：停下来，附完整报错和上下文再报告
- 依赖缺失：先检查 `package.json`，再执行 `npm install`
- 绝对不要：删除其他模块代码来消除报错、`npm audit fix --force`、在 `src/` 外创建入口文件

## 代码审查清单
- [ ] 新增 UI 字符串是否已在 `i18n/locales.js` 注册
- [ ] Three.js 资源是否正确 dispose
- [ ] 权限声明是否最小化
- [ ] `npm run lint` 通过
- [ ] 所有测试通过

## 多代理角色
- `explorer` — 探索架构和代码逻辑
- `reviewer` — 审查安全性和正确性
- `docs-researcher` — API 文档和发布说明验证
