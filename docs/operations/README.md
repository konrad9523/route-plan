# 协作与操作文档

这里集中放团队如何协作、如何归档资料的说明。首次参与项目时，先读协作手册；实际创建 Issue 或 Pull Request 时使用下方模板。

| 内容 | 文件位置 | 用途 |
|---|---|---|
| GitHub 团队协作入门与项目使用规范 | [GitHub团队协作入门与项目使用规范.md](GitHub团队协作入门与项目使用规范.md) | 建仓、成员个人工作区与公共区、命令行流程、分支、PR 审查和安全约定。 |
| 团队任务 Issue 模板 | [task.md](../../.github/ISSUE_TEMPLATE/task.md) | 记录负责人、目标、验收标准、共享交付位置和依赖。 |
| Pull Request 模板 | [PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md) | 记录变更目的、影响范围、测试证据和合并检查。 |
| 项目变更日志 | [CHANGELOG.md](../../CHANGELOG.md) | 汇总合并到公共项目的版本变化。 |
| 个人工作区忽略规则 | [.gitignore](../../.gitignore) | 防止本机 `个人工作区/` 和现有 A3 临时区被意外提交。 |

Issue/PR 模板的源文件必须留在 `.github/`，变更日志留在仓库根目录；GitHub 会从约定位置读取模板。这里提供统一导航，不复制模板内容，避免产生两个需要同步的版本。详见 [GitHub 模板官方说明](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates)。
