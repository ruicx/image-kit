# image-kit

为独立镜像仓库提供清单驱动的容器构建工具、共享安装能力与资源。

English documentation: [README.md](README.md)

## 内容

| 路径 | 职责 |
| --- | --- |
| `src/image_kit/` | 清单校验、依赖图、变更规划、Bake 生成、测试执行和注册表操作。 |
| `src/image_kit/schemas/` | 随 Python 包分发的版本化清单 schema。 |
| `scripts/system/` | 系统配置、用户、SSH、工作目录和软件源。 |
| `scripts/dev/` | 构建工具、编译器、开发 shell 和 pre-commit。 |
| `scripts/python/` | Python 配置及彼此独立的 CUDA/Ascend 软件包安装器。 |
| `scripts/libraries/` | 第三方 C++ 库。 |
| `scripts/integrations/` | Ascend、ROS 2、llama.cpp 和 WSLg 集成。 |
| `assets/` | 入口脚本、公共 Python 开发依赖和配置。 |
| `tests/` | Python 引擎测试、不执行安装的参数检查及依赖检查回归测试。 |

镜像清单、Dockerfile、软件选择、账号/文档检查和 CI 权限由消费者维护。image-kit 0.2
使用同一份 v2 schema、仓库模型和 CLI，支持单变体、多变体及原生多平台镜像。YAML `name`
决定发布包名，不要求与目录名相同。构建标签记录 variant、源码 SHA 和工作流批次；正式版本从
已验证发布收据提升，不重新构建。详见英文[清单契约](docs/manifest-reference.md)、
[CLI 参考](docs/cli-reference.md)和 [v2 迁移说明](docs/migration-v2.md)。

## 安装与运行

要求 uv、Python 3.11+、Git；镜像操作还需 Docker Buildx。目前未发布到 PyPI，从 image-kit
工作副本运行：

```bash
uv sync --locked --extra dev
uv run images --root /path/to/image-repository validate
uv run images --root /path/to/image-repository plan --all --output build-plan.json
```

`uv run image-kit` 和 `uv run python -m image_kit` 与 `uv run images` 使用同一 CLI。清单位于选定消费仓库根目录
下的 `src/<family>/image.yml`。参见[清单参考](docs/manifest-reference.md)和
[CLI 参考](docs/cli-reference.md)。校验覆盖构建契约、路径和 DAG，消费端文档与账号策略
单独检查。可选的 `mirror` 和 `runtime` 配置用于集成共享脚本，其他镜像可以同时省略二者。

消费端默认值在自己的 `pyproject.toml` 中声明，例如：

```toml
[tool.image-kit]
registry = "ghcr.io"
source-repository = "example/images"
rebuild-inputs = [".gitmodules", "vendor/image-kit", "tools/**"]
shell-inputs = ["vendor/image-kit/tests/*.sh"]
```

注册表默认为 `ghcr.io`，相关命令可通过 `--registry` 覆盖。通过 `--github-cache` 显式启用 Actions 缓存，本地构建省略该选项。`.dockerignore`、`pyproject.toml`、`uv.lock` 和 `.github/workflows/**` 始终触发重建；
`rebuild-inputs` 添加消费端路径。shell 校验覆盖清单输入、冒烟脚本及 `shell-inputs`。
组件不假定特定子模块路径。uv 消费端声明 `image-kit` 依赖，并在 `[tool.uv.sources]` 中配置
可编辑路径，再运行 `uv sync`。本项目与消费仓库分别保留自己的 `uv.lock`；CI 使用
`uv sync --locked`，Python 类型检查统一使用 ty。

## 消费固定版本组件

```bash
git submodule add https://github.com/ruicx/image-kit.git vendor/image-kit
git -C vendor/image-kit checkout <reviewed-component-commit>
```

在消费仓库提交子模块引用。已有工作副本运行 `git submodule update --init --recursive`
初始化，新克隆可使用 `--recurse-submodules`。CI 不自动跟随组件分支。公共修改需先在本仓库
提交并推送，再更新消费仓库引用；各消费仓库可独立升级。

使用消费仓库根目录作为 Docker 构建上下文，显式复制每个公共输入，并保留相邻的能力层：

```dockerfile
COPY --chmod=0755 vendor/image-kit/scripts/dev/cmake.sh /tmp/scripts/cmake.sh
RUN /tmp/scripts/cmake.sh --version "${CMAKE_VERSION}" --sha256 "${CMAKE_SHA256}"
```

在消费仓库清单的 `inputs` 中声明相同文件。参数化脚本使用 GNU `getopt` 选项，提供
`--help`，错误用法返回 64。消费仓库显式选择版本、基础镜像、账号、SSH 模式、软件源和能力
执行顺序。凭据通过运行时秘密文件挂载。滚动开发 shell 工具及任何 checksum 例外均需在每个
消费镜像族中获得明确批准，并记录在双语文档中。

## 验证

同步开发依赖后，在当前仓库安装 Git 提交检查，并可手动检查全部文件：

```bash
uv sync --locked --extra dev
uv run --no-sync pre-commit install
uv run --no-sync pre-commit run --all-files
```

这些检查包括基础文件检查、Ruff 自动修复与格式化，以及整个项目的 ty 类型检查。Ruff 和 ty 使用项目锁定的开发环境；首次运行基础 hooks 需要网络。消费仓库跳过 `vendor/`，image-kit 的 hooks 在组件仓库中单独安装和运行。

在 Linux 或 Git Bash 中运行：

```bash
uv sync --locked --extra dev
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check
bash tests/install-arguments.sh
bash tests/ascend-pip-check.sh
mapfile -t shell_files < <(git ls-files '*.sh')
shellcheck "${shell_files[@]}"
shfmt -d -i 4 -ci "${shell_files[@]}"
```

这些测试不安装容器软件，也不构建镜像。消费仓库还需执行自己的清单校验、原生镜像构建和冒烟
测试。抽取过程中保留能力行为，不兼容修改需单独审阅。

## 贡献

Agent 与维护者请先阅读 [AGENTS.md](AGENTS.md)，了解组件职责、uv/ty 检查、兼容性要求及
消费仓库的职责边界。

脚本按能力分类，注释使用英文，保留显式参数校验，两个 README 同步更新。提交标题使用
`Feat`、`BugFix`、`Refactor` 或 `Doc`，后接冒号和摘要；空行后以编号列表描述修改。

## 系统能力参数

`system.sh --timezone <zone> --upgrade <true|false>` 配置系统，升级默认为 `false`，由消费仓库显式启用。`true`/`false` 不区分大小写。`dev-tools.sh` 提供通用用户切换及权限工具 `gosu` 和 `sudo`；Landscape 工具由消费仓库自行选择。
