# oss-issue-scout

[![PyPI](https://img.shields.io/pypi/v/oss-issue-scout.svg)](https://pypi.org/project/oss-issue-scout/)

发现值得贡献的开源 issues

[English README](README.en.md)

当前版本会调用 GitHub API 搜索 open issues，并根据项目活跃度、issue 活跃度、评论数量、标签等信号做一个简单评分
它主要面向初中级开发者，用来快速筛出更可能适合贡献的 issue

## 功能

- 搜索 GitHub open issues，并支持用户选择预设
- 支持按语言、标签、stars、更新时间过滤
- 默认跳过已有关联 PR 的 issue
- 默认只推荐未指派的 issue
- 默认过滤 stars 少于 100 的 repo
- 支持 `table`、`markdown`、`json` 输出
- 不依赖第三方包

## 使用

```powershell
pip install oss-issue-scout
oss-issue-scout search --language python --label "good first issue" --limit 5
```

## 参数

```text
--language            仓库主要语言，例如 python
--stars-min           仓库最低 stars，默认至少 100
--label               issue 标签，例如 "good first issue"
--updated-days        当前 issue 最近多少天内更新过
--repo-updated-days   issue 所在 repo 最近多少天内有 issue 活动
--limit               返回数量，默认 10
--preset              使用预设搜索 issue，可选 default、junior、intermediate、senior
--format              输出格式：table、markdown、json
```

示例：

```powershell
oss-issue-scout search --language python
oss-issue-scout search --language python --label "help wanted" --stars-min 500 --limit 10
oss-issue-scout search --language python --format json
oss-issue-scout search --language "C++" --label "good first issue" --repo-updated-days 7
oss-issue-scout search --language python --preset intermediate --limit 20
```

## 推荐规则

当前评分比较简单，主要参考：

- repo stars：中等活跃项目加分，超大型项目可能扣分
- issue 更新时间：近期更新加分，长期未更新扣分
- repo issue 活动：近期有 issue 活动加分
- beginner 标签：当前 issue 有 `good first issue` / `help wanted`，且 repo 中至少有 3 个同类 open issues 时加分
- 评论数量：评论少加分，讨论过长扣分

搜索阶段会直接排除：

- closed issues
- archived repos
- 已 linked PR 的 issues
- 已指派 assignee 的 issues
- stars 少于 100 的 repos

搜索会使用用户选择的预设；如果未选择，则使用 `default` 预设。

## 测试

```powershell
python -m unittest discover
```

测试使用 mock 数据，不会请求真实 GitHub API

## 后续

现在项目使用的人还比较少，如果你觉得它对你有帮助，欢迎点一个 ⭐。达到 16+ ⭐ 后会开启 Discussions

如果有改进建议或使用问题，可以在 issues 中提出

后续会逐步进行版本迭代，继续优化推荐质量和使用体验

## 贡献者

<a href="https://github.com/Yong-yuan-X/oss-issue-scout/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Yong-yuan-X/oss-issue-scout" alt="Contributors" />
</a>
