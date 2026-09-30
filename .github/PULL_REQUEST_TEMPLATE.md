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
<summary><b>发 PR 前必须检查整个分支</b>（点开看命令与原因）</summary>

`git diff --cached` 只比较"暂存区 vs HEAD"，**它回答不了"这个 PR 要合入什么"**。
内容一旦提交、暂存区为空，它可能毫无输出——即使分支上带着草稿提交。

**正确做法：比较分支与上游基线（注意三点号）**

```powershell
git fetch upstream
git diff --name-status upstream/main...HEAD   # 这次要合入哪些文件
git log --oneline upstream/main..HEAD         # 分支带了哪些提交
git diff --check upstream/main...HEAD         # 尾随空格等低级问题
git diff upstream/main...HEAD                 # 逐行内容
```

**为什么必须这样查**（真实反例）：
第一次提交误加了 `member_workspaces/A3/`，第二次提交是正常代码。
两次提交之后查暂存区——**清单是空的**，但草稿仍在分支差异里，会一起进 PR。

> `.gitignore` **不能**把已提交的文件从 PR 中排除——它只影响未跟踪文件。

**如果已经带进来了**：不要用 `git rm --cached` 掩盖（文件仍留在分支历史里）。
正确做法是从 `upstream/main` 重建一条干净分支，只挑该交付的文件（见管理原则 §2.4.1）。

### 怎么确认没带进 `member_workspaces/`

```powershell
git diff --name-only upstream/main...HEAD | Select-String "member_workspaces|个人工作区"
#    应无输出
```

</details>

