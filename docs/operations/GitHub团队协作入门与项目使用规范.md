# GitHub 团队协作入门与项目使用规范

适用于五人导航系统项目的仓库建立、日常命令行协作、代码审查与变更追溯。更新日期：2026-09-27。

本手册的目标是让每个人都能从自己的电脑安全地同步项目，并让进入主分支的每项改动都能回答四个问题：谁改的、为什么改、改了什么、怎样验证。团队采用“任务 Issue → 独立分支 → 本地 Commit → Pull Request 审查 → 合并 main → 更新 CHANGELOG”的闭环。

## 先理解 GitHub 协作里的几个东西

Git 是每个人电脑上的版本管理工具；GitHub 是托管远程仓库、讨论和审查变更的网站。仓库 Repository 保存代码和提交历史。GitHub Project 是可选的任务看板，不是代码仓库。五个人需要共用一个 Repository；是否再建 Project 看板，可以随后决定。

| 名词 | 可以先这样理解 | 这个项目里怎么用 |
|---|---|---|
| `main` | 团队认可的稳定版本 | 禁止日常直接提交；只接收审查通过的 Pull Request。 |
| Issue | 一张带编号的任务卡或问题单 | 记录目标、负责人、验收条件、依赖和讨论。 |
| Branch | 从当前版本分出的独立工作线 | 每个任务单独建分支，例如 `feature/a3-ch-query`。 |
| Commit | 一次有说明的本地版本快照 | 小步保存；提交信息说明这次快照做了什么。 |
| Pull Request（PR） | 请求把分支合入 `main` 的审查单 | 展示代码差异、测试证据、讨论和批准记录。 |
| `CHANGELOG.md` | 给人阅读的项目变更摘要 | 每个合并的 PR 更新，记录功能、影响和验证。 |

Commit、PR 和 Issue 共同形成证据链：Commit 说明代码改动，PR 说明改动原因和审查过程，Issue 说明任务从哪里来，CHANGELOG 帮助组员快速了解版本变化。

## 推荐的五人协作方式

建议先由一位成员创建并拥有仓库，再邀请另外四位成员。每个人使用自己的 GitHub 账号，禁止共用账号或把密码、访问令牌发到群里。项目有长期维护或课程要求时，可以再考虑转到团队 Organization；初次使用时个人仓库步骤更少。

一项任务由一名成员负责，一个任务使用一个短期分支。其他成员通过 PR 审查，不要两个人同时在同一个分支上随意改动。每次任务开始前先在 Issue 中确认目标、验收标准和相关接口。

本项目的角色标签建议使用 `A1 数据`、`A2 算法`、`A3 性能`、`A4 交互`、`A5 验证`。跨模块任务要在 Issue 和 PR 中写明影响的角色，并提前通知接口提供者和使用者。A3 重点涉及 SearchTrace、CH、性能实验和 API；图数据/CSR、路径算法正确性、可视化消费和公平验证分别需要与 A1、A2、A4、A5 对齐。

## 个人工作区与公共区的边界

仓库里的目录按**功能**划分，不按成员姓名划分。成员通过自己的本地工作区保存个人草稿，通过 Git 分支和 Pull Request 把准备共享的成果送入公共目录。不要建立 `A1代码/`、`A2代码/` 这样的正式代码目录；成员换人或角色调整时，代码目录不应跟着重排。

### 每位成员的本机个人工作区

每位组员克隆仓库后，在自己的项目根目录建立 `个人工作区/<成员代号>/`。这个目录由 `.gitignore` 排除，不会推送到 GitHub；适合存放收到后尚未分类的文件、个人学习草稿、代码实验、报告草稿和临时结果。建议每个人沿用同一套子目录：

```text
个人工作区/
├── A1/
│   ├── 00_收件箱/
│   ├── 01_学习草稿/
│   ├── 02_代码实验/
│   ├── 03_报告草稿/
│   ├── 04_文档草稿/
│   ├── 05_交付候选/
│   └── 99_归档/
├── A2/
├── A3/
├── A4/
└── A5/
```

每位成员只需创建自己的子目录，不要把整个 `个人工作区` 上传或提交。它是本机草稿区，不是版本控制或备份：需要留痕、供队友审查的代码仍应在仓库正式目录的个人分支上修改。当前仓库已有的 `A3_临时工作区/` 仍被忽略；其中已有资料不在本次迁移，A3 可暂时继续使用，确认内容和路径后再自行迁入统一目录。

### 公共区：仓库中其余被跟踪的内容

公共区中的内容默认供全组阅读和维护。当前项目建议沿用这些唯一归档位置：

| 内容 | 公共归档位置 | 规则 |
|---|---|---|
| 经过整理、全组可复用的学习资料 | `docs/learning/` | 学习资料只设这一个正式汇总区；个人原始笔记留在个人区，整理后通过 PR 汇入，不按成员重复建目录。 |
| 项目目标、分工、设计决策和正式报告 | `docs/project/` | 记录组内确认的结论；草稿先放个人区。 |
| 接口、代码现状和开发说明 | `docs/development/` | 与实现同步；跨模块变更在 PR 中说明上下游。 |
| 测试方法与可复现验证结果 | `docs/validation/`、`tests/` | 共享结论应给出命令、数据版本和环境；临时日志不提交。 |
| 可复用源代码 | `path_planning/`、`api/`、`web/` 等功能目录 | 从个人实验转为公共实现时，移入正确的功能模块，再走分支和 PR。 |
| 外部项目索引 | `docs/references/` | 维护链接、版本和学习目的；下载的第三方源码仍留在被忽略的本机目录。 |

**学习资料集中，但个人学习过程不必全部公开。** 组员先在自己的 `01_学习草稿/` 学习；确认对全组有用后，把经过核对、能独立阅读的版本提交到 `docs/learning/`。个人代码实验同理：可复用的实现进入功能代码目录，报告草稿进入正式报告目录，临时文件和个人信息留在本机。

### 区分“个人草稿”和“个人开发分支”

`个人工作区/` 是 Git 忽略的本机文件夹；它的内容既不会推送，也不会自动备份。Git 分支则是开发公共项目的隔离工作线：在 `feature/<成员或模块>-<任务>` 等分支上修改仓库正式文件，推送后队友可见，再用 PR 审查并合并。不要把一个人的所有正式代码长期放在 `A3/` 这样的成员目录里。

GitHub 仓库权限是仓库级别，不是文件夹级别。个人工作区留在本机，才能与公共仓库内容分开；一旦文件提交到同一个远程仓库，获得该仓库访问权的成员通常就能读取它。若某些材料确实只能给个别人看，应放在独立且权限受控的仓库或合规存储中，不要依赖文件夹名称保密。

### 可以复用到其他小组项目的默认规则

新项目可以复制本节的模式，只替换成员代号、功能模块名和共享资料路径：

1. 本机草稿放 `个人工作区/<成员代号>/`，统一写进 `.gitignore`；不提交个人临时文件。
2. 共享仓库按功能分目录；代码、最终文档、学习资料分别有唯一归档位置。
3. 每项共享任务先建 Issue，写负责人、目标、验收条件、相关模块和最终文件位置。
4. 每位负责人从 `main` 新建任务分支，只把经过选择的变更带入公共目录，再开 PR。
5. 至少一位非作者组员审查；代码变更给出测试证据；需要复用的资料通过 PR 归档到统一学习区。
6. 角色/文件负责人稳定且成员 GitHub 用户名确认后，再考虑用 `CODEOWNERS` 自动请求模块审查；前期用 Issue Assignee、角色标签和 PR Reviewer 即可。

本方案参考 OSRM、GraphHopper 和 Valhalla：GraphHopper 将 `core`、`map-matching`、`navigation`、`web-api` 等按功能分开，贡献指南要求一个 PR 聚焦一个问题并带测试；OSRM 的贡献指南记录了禁止直接推送到主分支、API 变更先讨论并经 PR 审查的做法；Valhalla 鼓励较大的功能先开 Issue 讨论、提交测试，并提醒首次审查后不要强推。共同规律是**按功能组织共享代码，按 Issue/分支/PR 分配和审查工作**，而不是把每个人的正式代码长期放在成员姓名目录中。链接见文末参考资料。

### 先决定仓库公开还是私有

GitHub 的访问权限和分支保护能力取决于仓库可见性与账号方案。官方文档当前说明：GitHub Free 的公开仓库可使用分支保护规则或 Rulesets；私有仓库启用这些规则需要 GitHub Pro、Team 或 Enterprise。个人 Free 账号可以邀请不限数量的私有仓库协作者，但“能邀请协作者”不等于“能强制要求 PR 审批”。

| 方案 | 适用条件 | 是否能强制保护 `main` |
|---|---|---|
| Free + Public | 已确认代码、课件、数据来源和许可证都允许公开 | 可以配置 PR、审批、禁止强推等规则。公开后任何人都可能看到仓库内容。 |
| Free + Private | 需要先限制项目可见范围，且暂时不升级 | 可邀请组员、使用 PR 留痕；但不能依靠分支保护规则强制阻止直接推送，必须承认这是流程约定而非技术拦截。 |
| Pro/Team/Enterprise + Private | 内容不能公开，同时需要强制审查规则 | 可以对私有仓库设置分支规则。 |

不要为了免费强制保护而在未审核数据和课件许可时贸然公开。先检查课程资料授权、地图数据许可、API 密钥和个人信息，再由组内确认可见性。GitHub 规则可用性会变化，设置前可复核[Rulesets 官方说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)。

## 在 GitHub 建立共享仓库

下面按“当前电脑已有本地项目、尚未配置 GitHub 远程仓库”的情况写。不要在 GitHub 新仓库里先创建 README、`.gitignore` 或 License，否则远程会多出本地没有的初始提交，第一次同步更容易冲突。

### 第一步 每位成员准备账号

1. 每位组员分别注册或登录自己的 GitHub 账号。
2. 记录每位成员准确的 GitHub 用户名，不要只记昵称。
3. 开启双重验证；不要在聊天、Issue、PR 或代码里粘贴密码、Personal Access Token 或 API 密钥。
4. 确认哪些数据和资料可以上传到所选可见性的仓库。

### 第二步 创建空仓库

1. 登录 GitHub，点击右上角 `+`，选择 `New repository`，也可访问 [新建仓库页面](https://github.com/new)。
2. `Owner` 选择负责维护仓库的个人账号或团队 Organization。
3. 仓库名使用简短英文，例如 `route-plan`；描述可以写 `GIS navigation and route planning course project`。
4. 选择刚才讨论好的 `Private` 或 `Public`。
5. 如果这是要连接现有本地仓库的空远程端，README、`.gitignore`、License 选项都不要勾选。
6. 点击 `Create repository`。记下仓库地址，形式类似 `https://github.com/OWNER/route-plan.git`。

如果误选了 README 等初始化选项，不要用 `git push --force` 覆盖远端；先停止同步，由仓库负责人决定是重新建空仓库，还是按 GitHub 提示合并两个初始历史。

### 第三步 邀请四名组员

仓库创建者在仓库主页进入 `Settings`，在左侧 `Access` 区域打开 `Collaborators`，点击 `Add people`，搜索并选中每位组员的 GitHub 用户名，再发送邀请。每位组员必须登录自己的账号接受邀请后，才能访问仓库。仓库 owner 保存唯一的管理权限，不向所有人共享 owner 账号。

个人仓库的 collaborator 通常可以写入仓库，所以“大家自觉不动 main”不够稳妥。能使用分支规则时，应尽快把 `main` 设为必须经过 PR 的保护分支。

### 第四步 给 `main` 设置规则

**执行时机：先完成下一节的首次推送，确认远端已经出现 `main` 后，再回来启用本节规则。** 空仓库没有可提交 PR 的 `main`，过早启用“必须通过 PR”可能拦住创建主分支的首次推送。首次推送前可以先看好设置项，但不要先激活规则。

在仓库主页依次打开 `Settings` → 左侧 `Rules` 或 `Code and automation` 下的 `Rulesets` → `New ruleset` → `New branch ruleset`。不同账号界面文字可能略有差异，关键是新建针对默认分支的 Branch ruleset。

建议设置如下：

1. 名称填写 `Protect main`，Enforcement status 选择 `Active`。
2. `Target branches` 添加 `Include default branch`，确认默认分支是 `main`。
3. 开启 `Require a pull request before merging`。
4. 要求至少 `1` 个 Approval。五人小组中，批准者必须是作者以外的组员。
5. 开启 `Dismiss stale approvals when new commits are pushed`，避免批准后又追加未审核的改动。
6. 开启 `Require conversation resolution before merging`，确保审查意见有处理结果。
7. 开启 `Block force pushes`，并禁止删除受保护分支。
8. 不设置 Bypass 人员，避免日常工作绕过规则。仓库管理员仍应遵守同一流程。
9. 如果还没有 GitHub Actions 测试流程，暂时不要添加必需的 Status checks；否则 PR 可能永远处于不能合并状态。测试流程上线后再把实际生成的检查项设为必需。
10. 点 `Create ruleset` 后回到 Rulesets 页面确认规则为 Active，目标覆盖 `main`。

如界面没有 Rulesets/Branch protection，先核对账号方案与仓库可见性。GitHub 当前方案说明见[可用规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)和[创建 Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)。

### 第五步 可选建立 GitHub Project 看板

Repository 保存代码，GitHub Project 看板负责看任务。先在仓库 `Issues` 中建 Issue，再把 Issue 放入 Project；不要用一个没有链接 Issue 的看板卡片代替代码审查。

1. 登录 GitHub，打开个人头像菜单中的 `Your projects` / 个人主页 `Projects`，点击 `New project`。
2. 选择 `Board`，项目名写 `导航系统开发`，创建空看板或导入仓库的 Issues。
3. 使用状态 `Backlog`、`Ready`、`In progress`、`In review`、`Done`。
4. 添加 `Role` 字段（A1 到 A5）、`Priority` 字段和负责人 `Assignee`。
5. 让每项开发工作都能对应到 Issue；PR 合并后关闭 Issue，并将看板卡片移到 `Done`。

GitHub Project 的入口可能因个人仓库或 Organization 略有不同，可按[创建 Project 官方步骤](https://docs.github.com/en/issues/planning-and-tracking-with-projects/creating-projects/creating-a-project)操作。

## 把当前本地项目连接到 GitHub

### 先审核本地内容

在 PowerShell 中进入现有项目目录：

```powershell
Set-Location -LiteralPath 'D:\pycharm\projects\route_plan'
git status --short --branch
git log --oneline --decorate -10
git ls-files
git diff
```

`git status` 用来查尚未提交的修改；`git log` 查看已经提交的历史；`git ls-files` 查看 Git 已经跟踪的文件；`git diff` 查看未暂存的改动。第一次推送前，还要检查已提交历史里有没有不应共享的文件、密钥或大体积数据。删掉工作区里的文件，并不会从过去的提交中自动抹掉它。

**针对当前电脑的特别提醒（2026-09-27）**：本地 `main` 还没有远程仓库，工作区已有修改和删除项；其中第 1 次课 PPT 当前显示为“已删除”，但它仍存在于本地最新提交历史中。若此时创建公开仓库并直接推送 `main`，未提交的删除不会随 `git push` 上传，远程仍会收到已提交历史里的 PPT。先确认该课件是否允许共享，再决定如何处理。即使之后提交了删除，旧提交里的文件内容仍在 Git 历史里；若它不允许上传，应在首次分享前准备一份经过授权审核的干净发布历史，不能只靠“删文件再提交”。已经共享的 `main` 不要自行强推重写历史。当前未提交的 `.gitignore` 修改、其他删除和未跟踪文件也要逐项审核，不能直接用 `git add .` 一把提交。

本次还新增了本手册、根目录 `CHANGELOG.md` 和 `.github/PULL_REQUEST_TEMPLATE.md`。它们同样是尚未提交的本地变更；与已有改动分开检查、选择后，再决定是否一起推送。

### 配置本机提交身份

每位成员在自己的电脑上配置一次姓名和邮箱。Git 用它标注是谁创建了 Commit；邮箱应使用 GitHub 已验证的邮箱，或在 GitHub 邮箱隐私设置中提供的 noreply 地址。

```powershell
git config --global user.name "你的姓名或组内署名"
git config --global user.email "你的 GitHub 已验证邮箱"
git config --global --get user.name
git config --global --get user.email
```

不要在不同成员电脑上共用同一身份设置。否则提交记录会显示错人，追溯失真。

### 为本地仓库配置远程地址并首次推送

确认仓库内容和可见性后，仓库负责人在本地执行：

```powershell
git remote -v
git remote add origin https://github.com/OWNER/route-plan.git
git remote -v
git push -u origin main
```

把 `OWNER/route-plan` 换成刚创建的真实仓库地址。`origin` 是远程仓库的惯用名字；`-u` 让本地 `main` 记住对应的远端分支。Git Credential Manager 可能会打开浏览器要求登录 GitHub；使用自己的账号完成登录，不要把密码或令牌直接写进命令。

`git push` 只上传已经 Commit 的提交，不会自动上传未提交的工作区修改，也不会自动把未跟踪文件加入历史。推送后打开 GitHub 仓库主页，核对文件列表、默认分支和可见性。

如果 `git remote -v` 已经显示 `origin`，先看它是否确实指向本组仓库；不要重复执行 `git remote add origin`。如果提示 `remote origin already exists`，先用 `git remote -v` 核实，不要随意删除或替换远端地址。

## 每位组员第一次在本地开始工作

### 安装 Git 并配置账号身份

1. 从 [Git for Windows 官网](https://git-scm.com/install/windows)安装 Git。安装器初学者可先保留默认选项。
2. 安装完成后重新打开 PowerShell，运行 `git --version`。看到版本号表示命令行已可用。
3. 按上一节配置自己的 `user.name` 和 `user.email`。
4. 使用 HTTPS 克隆时，按提示通过浏览器完成 Git Credential Manager 登录。不要在 Git 命令里填 GitHub 网站密码。

GitHub 官方建议 HTTPS 用户用 GitHub CLI 或 Git Credential Manager 保存凭据，详见[凭据缓存说明](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)。本组先统一使用 HTTPS，避免每个人第一次配置 SSH 密钥时卡住。

### 克隆共享仓库

组员接受仓库邀请后，在希望放置项目的父目录打开 PowerShell：

```powershell
Set-Location -LiteralPath 'D:\pycharm\projects'
git clone https://github.com/OWNER/route-plan.git
Set-Location -LiteralPath 'D:\pycharm\projects\route-plan'
git status --short --branch
```

`git clone` 会下载当前项目及其提交历史，并自动设置远端 `origin`。每位成员克隆一次即可；以后用 `git pull` 同步，不要反复下载 ZIP 覆盖自己的工作目录。已有同名目录时不要直接覆盖，先选新的目录名或备份确认。

## 每项任务的标准命令行流程

以下命令假设默认分支叫 `main`，并且当前改动已经保存或提交。每次开始新任务都从最新 `main` 创建新分支。

### 1 开始前同步主分支

```powershell
git status --short --branch
git switch main
git pull --ff-only origin main
git switch -c feature/a3-ch-query
```

把 `feature/a3-ch-query` 换成自己的任务分支名。`git pull --ff-only` 只允许安全快进，不会悄悄制造一个合并提交。如果 `git status` 显示有未提交改动，不要先切分支或拉取；先确认并保存这些改动，避免把上一个任务混进来。

### 2 修改并检查代码差异

按 Issue 中的验收条件修改代码。完成一小批逻辑后，先看改了什么：

```powershell
git status --short
git diff --check
git diff
```

`git diff --check` 会检查常见空白错误；`git diff` 显示尚未暂存的具体差异。运行与改动相关的单元测试、示例或基准，把实际命令和结果记下来。性能改动还要记录数据规模、固定查询集和运行环境，不能只写“感觉更快”。

### 3 只暂存本任务的文件

不要习惯性运行 `git add .`。逐个写出确认过的路径：

```powershell
git add path\to\changed_file.py
git add path\to\test_file.py
git status --short
git diff --cached --stat
git diff --cached
```

`git add` 是把文件放入“下一次提交的候选清单”，不是提交本身。提交前必须检查 `git diff --cached`；如果不该提交某个文件，可先用 `git restore --staged -- path\to\file` 将它从候选清单移出，文件内容仍保留在本地。

删除文件也要有意识地确认：`git status` 显示 `D` 后，检查文件是否确实应该从项目中删除，再把这个删除加入提交。不要把别人尚未确认的代码或数据删除顺手带进自己的提交。

### 4 用清楚的 Commit 保存改动

一次 Commit 尽量对应一个完整、可说明的逻辑变更。推荐格式：

```text
类型(模块): 动词开头的简短说明
```

| 类型 | 何时使用 | 示例 |
|---|---|---|
| `feat` | 新增功能 | `feat(a3/ch): add shortcut unpacking` |
| `fix` | 修复错误 | `fix(a2/search): handle unreachable target` |
| `perf` | 性能改进 | `perf(a3/ch): reduce query allocations` |
| `refactor` | 不改变外部行为的结构整理 | `refactor(a1/graph): simplify edge loader` |
| `test` | 测试和基准 | `test(a5): add fixed directed graph cases` |
| `docs` | 文档 | `docs(team): add GitHub workflow` |

然后提交：

```powershell
git commit -m "perf(a3/ch): reduce query allocations"
git log -1 --oneline
```

Commit 信息写“做了什么”，PR 描述写“为什么做、影响什么、如何验证”。不要使用 `update`、`fix bug`、`最终版` 这种无法追溯的描述。

### 5 推送任务分支

第一次推送此分支：

```powershell
git push -u origin feature/a3-ch-query
```

同一分支之后有新 Commit 时：

```powershell
git push
```

这会把你的分支发到 GitHub，不会直接改动受保护的 `main`。

### 6 在 GitHub 建立 Pull Request

1. 打开仓库，点 `Compare & pull request`；若没有提示，进入 `Pull requests` → `New pull request`。
2. `base` 选 `main`，`compare` 选自己的任务分支。
3. 标题说明角色和改动，例如 `[A3][CH] 记录固定查询集下的查询耗时`。
4. 按 PR 模板写明目的、关键改动、验证命令和结果、接口/数据影响、风险和回滚方式。
5. 如果有 Issue，使用 `Closes #编号` 关联它。
6. 请求一位非作者组员审查；涉及跨组接口时，也请求接口提供者确认。
7. 等待审查意见，修改后仍推送到同一分支；PR 会自动更新。
8. 所有必须的审批、检查和讨论完成后，由有权限的组员通过 GitHub 页面合并。建议仓库只启用 `Squash and merge`，让主分支历史保持容易阅读。
9. PR 合并后，在本地更新 `main`；GitHub 页面可以删除已经合并的远程分支。

Pull Request 的 Files changed 页面是审查核心：每位 Reviewer 都要检查代码差异是否对应 PR 描述、测试是否覆盖验收条件、接口是否兼容，而不是只点 Approve。

### 7 合并后准备下一项任务

```powershell
git switch main
git pull --ff-only origin main
git status --short --branch
```

确认本地 `main` 已同步后，再用新的 Issue 和新分支开始下一项任务。不要继续在已合并的旧分支上累积下一件事。

## Issue PR 与变更日志的记录要求

### Issue 记录要做什么

每个功能、缺陷或数据接口变更都先建 Issue。点击仓库 `Issues` → `New issue`，选择“团队任务”模板。至少写清楚：目标和背景、负责人、所属角色、涉及模块、验收条件、最终共享交付位置、依赖的其他成员/数据、是否影响接口或数据格式。暂时不能做的讨论可以继续留在 Issue，不要散落在口头聊天里。

### PR 记录实际改了什么

每个 PR 应能独立读懂。写清楚改动前的问题、改动后的行为、为何这样设计、修改的文件/接口、运行过的测试、测试输出或结果文件、未解决的限制。不要把多个无关任务塞进一个 PR。合并前由非作者审核。

### 变更日志记录组员关心的版本变化

仓库根目录的 `CHANGELOG.md` 是共享的变更日志。每个合并的 PR 都要在 `Unreleased` 下加入或更新一条；在 PR 合并前，PR 作者负责修改，Reviewer 检查。只改拼写或纯格式且不影响其他成员的变动，可以在 PR 中解释为什么不新增日志。

每条日志包括日期、角色/模块、具体行为变化、目的、测试证据，以及接口兼容性或数据迁移影响。可以按下面的格式写：

```markdown
## Unreleased

### Added
- 2026-09-27 [A3][CH] 增加固定查询集基准输出；目的：比较 CH 与 Dijkstra 的查询性能；验证：`python -m unittest discover -s tests -v`；接口影响：无；Issue/PR：#12 / #18。

### Changed
- （有相关改动时填写）

### Fixed
- （有相关改动时填写）
```

不要只写“优化性能”。如果是性能改动，注明基线、同一数据/查询集下的测量结果、预处理时间与查询时间是否分开统计。合并 PR 后，Git commit、PR 审查记录、Issue 和 `CHANGELOG.md` 会分别保留代码、审查、任务和简明结果。

## 代码审查和合并规则

- `main` 只接受经过 PR 的修改；任何人都不在 `main` 上直接编辑或推送。
- 作者不能批准自己的 PR。至少一名非作者组员确认后再合并。
- 审查要检查代码逻辑、测试证据、文件删除、外部接口、单位/坐标约定、异常处理和日志条目。
- Reviewer 提出问题时，作者在 PR 对应讨论里回答；修代码并推送后，再请求 Reviewer 复查。没有处理或解释的讨论不能直接忽略。
- 接口字段、单位、图方向、返回结构或数据契约变化，必须在 PR 中标注影响范围并通知上下游角色。
- 小 PR 更容易看懂。一个 PR 尽量聚焦一个 Issue；确实要拆分时，在 Issue 里记录先后关系。
- 已启用分支保护时，以 GitHub 显示的 required checks 为准。没有稳定自动化测试前，不要凭空设置一个永远不会出现的检查项。

## 文件数据和密钥安全

1. 不提交 `.env`、密码、Token、API Key、个人访问令牌和含凭据的配置文件。放进本机环境变量或被 `.gitignore` 忽略的本地配置，并提供不含秘密的示例配置。
2. 不把地图数据、课件、下载数据或第三方项目直接上传前，先确认授权、许可证、体积和课程要求。优先提交下载/处理脚本、数据字段说明和小型可公开样例。
3. `.gitignore` 只能阻止未跟踪文件进入 Git；它不能从历史中清除已提交的秘密或大文件。若密钥已经推送，先立即撤销/轮换密钥，再通知仓库负责人处理历史。
4. 提交前检查 `git status` 和 `git diff --cached`。路径里出现个人目录、缓存、临时工作区或大文件时，停下来核实。
5. 临时测试结果放到本机忽略目录；要共享结果时，提交可复现脚本、小型汇总和数据来源，不要把无法解释的二进制结果扔进仓库。

## 常见问题处理

### 提示 `git` 不是命令

Git 未安装，或安装后终端没有重新打开。安装 Git for Windows，关闭并重开 PowerShell，再运行 `git --version`。

### 提示 `not a git repository`

当前 PowerShell 目录不在项目仓库中。先 `Set-Location -LiteralPath '你的本地项目路径'`，再运行 Git 命令。

### 推送提示 `non-fast-forward` 或远端有新提交

不要加 `--force`。先保存本地改动，再获取并合并最新 `main`：

```powershell
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git switch feature/a3-ch-query
git merge main
```

如果出现冲突，先运行 `git status` 看冲突文件。打开文件，逐段比较双方改动，处理 `<<<<<<<`、`=======`、`>>>>>>>` 标记并运行相关测试，再 `git add` 已解决文件并完成合并提交。如果不确定哪边正确，停止并找双方成员一起看；不要盲目保留一侧。尚未完成冲突处理时可以 `git merge --abort` 回到合并前状态。

### 想撤回已经合入 `main` 的错误修改

不要重写大家共用的历史。先用 `git log --oneline` 找到对应提交，再通过新的 PR 使用 `git revert <提交号>` 生成反向提交。这样撤回本身也有记录，队友的本地历史不会被强制改写。

### 想丢弃尚未提交的本地修改

`git restore -- path\to\file` 会丢弃该文件未提交的工作区修改；这类操作可能无法恢复。只有确认该内容不需要时才运行。若只是取消暂存，用 `git restore --staged -- path\to\file`，它不会删除文件内容。

### 误把 Token 或密钥推上 GitHub

立即撤销或轮换泄露的凭据，通知仓库负责人和相关服务管理员。只删掉文件或新增一次提交并不能让历史中的秘密消失；不要自行用强推改写共享历史。

## 明确禁止的操作

- 不在受保护的 `main` 上直接修改、Commit 或 Push。
- 不对共享分支运行 `git push --force` 或 `git push --force-with-lease`。
- 不运行 `git reset --hard`、`git clean -fd` 或 `git checkout .` 来“试着修好”；这些命令可能直接丢掉文件。
- 不用 `git add .` 代替检查，不提交未经确认的删除、课件、缓存、大数据、密钥或其他成员的临时文件。
- 不修改其他角色负责的接口而不通知他们；不把未经验证的结果写成“已通过”。
- 不把 GitHub 密码、令牌或个人 API Key 发到 Issue、PR、代码、日志或组群里。

## 常用命令速查

| 目的 | 命令 |
|---|---|
| 查看当前分支和改动 | `git status --short --branch` |
| 查看本地提交 | `git log --oneline --decorate -10` |
| 更新 `main` | `git switch main` 然后 `git pull --ff-only origin main` |
| 新建任务分支 | `git switch -c feature/a3-short-description` |
| 查看未暂存差异 | `git diff` |
| 暂存指定文件 | `git add path\to\file` |
| 查看即将提交的差异 | `git diff --cached` |
| 创建提交 | `git commit -m "perf(a3/ch): explain the change"` |
| 首次推送分支 | `git push -u origin feature/a3-short-description` |
| 后续推送 | `git push` |
| 从暂存区移出但保留文件 | `git restore --staged -- path\to\file` |
| 安全撤回已合入提交 | `git revert <commit-id>`，通过 PR 合并 |

## 官方操作资料

- [创建 GitHub 仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)
- [邀请个人仓库协作者](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)
- [分支 Rulesets 的方案与可用规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [为仓库创建 Ruleset](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
- [GitHub 凭据缓存](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)
- [创建 Pull Request 模板](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository)
- [Git for Windows 安装](https://git-scm.com/install/windows)
- [创建 GitHub Project 看板](https://docs.github.com/en/issues/planning-and-tracking-with-projects/creating-projects/creating-a-project)
- [GitHub Issues 与 Projects 协作规划](https://docs.github.com/en/issues/tracking-your-work-with-issues/learning-about-issues/planning-and-tracking-work-for-your-team-or-project)
- [GitHub CODEOWNERS 文件与路径审查](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [GitHub 仓库访问权限](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository)
- [GraphHopper 代码仓库](https://github.com/graphhopper/graphhopper) 与 [贡献指南](https://github.com/graphhopper/graphhopper/blob/master/CONTRIBUTING.md)
- [OSRM 贡献指南](https://github.com/Project-OSRM/osrm-backend/blob/master/CONTRIBUTING.md)
- [Valhalla 贡献指南](https://github.com/valhalla/valhalla/blob/master/CONTRIBUTING.md)

GitHub 的界面和方案功能可能更新；当某个按钮名称变化时，以链接中的官方文档和仓库当前 `Settings` 页面为准。规则设置后，先检查 Ruleset 确实 Active 并覆盖 `main`，不要仅凭团队口头约定认为分支已经受保护。
