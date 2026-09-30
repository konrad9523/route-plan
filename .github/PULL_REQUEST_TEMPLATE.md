## 改动目的

这次改动解决什么问题，为什么需要？

## 改动内容

- 涉及角色/模块：
- 关键文件或接口：
- 对其他模块的影响：

## 验证方式

- [ ] 已运行相关测试或基准
- 命令与结果：
- 性能改动注明数据规模、查询集、环境和基线

## 变更记录

- [ ] 已在 `CHANGELOG.md` 的 `Unreleased` 下增加或更新条目
- 日志条目或不需要记录的理由：
- 关联 Issue（建议使用 `Closes #编号`）：

## 合并前检查

- [ ] 已检查 `git diff` 和 `git diff --cached`，没有混入无关改动
- [ ] 没有提交密钥、个人信息、未经许可的数据或大体积临时文件
- [ ] **本分支没有包含 `member_workspaces/`**（它是 Fork 里的阶段留痕区，不进共享仓库）
- [ ] 没有把 `个人工作区/` 中的个人草稿作为公共交付物；共享学习资料已整理到 `docs/learning/`
- [ ] 每个提交只做一件事（说明里没有出现"和/顺便/也/以及"式的并列）
- [ ] 修复 bug 的改动带上了**在修复前会失败的测试**
- [ ] 若改变数据契约、字段、单位或方向约定，已通知上下游成员
- [ ] 已请求至少一位非作者组员审查

<details>
<summary>怎么确认没带进 <code>member_workspaces/</code>（点开）</summary>

`.gitignore` **不能**把已提交的文件从 PR 中排除——它只影响未跟踪文件。
所以必须在**建分支时**就分开（见管理原则 §2.4.1）：

```powershell
# 交付分支必须从 upstream/main 建，而不是从 workspace/<成员> 建
git fetch upstream
git switch -c feature/<成员>-<任务> upstream/main

# 推 PR 之前再看一眼文件清单
git diff --cached --stat | Select-String "member_workspaces|个人工作区"
#    应无输出

# 若整个 PR 的文件清单：
git diff --name-only upstream/main...HEAD
```

如果已经带进来了：**不要**用 `git rm --cached` 掩盖（文件仍在分支历史里）。
正确做法是从 `upstream/main` 重建一条干净分支，只挑该交付的文件。

</details>

