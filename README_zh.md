# image-kit

为独立维护的镜像仓库提供共享安装能力与容器资源。

English documentation: [README.md](README.md)

## 内容

| 路径 | 职责 |
| --- | --- |
| `scripts/system/` | 系统配置、用户、SSH、工作目录和软件源。 |
| `scripts/dev/` | 构建工具、编译器、开发 shell 和 pre-commit。 |
| `scripts/python/` | Python 配置及彼此独立的 CUDA/Ascend 软件包安装器。 |
| `scripts/libraries/` | 第三方 C++ 库。 |
| `scripts/integrations/` | Ascend、ROS 2、llama.cpp 和 WSLg 集成。 |
| `assets/` | 入口脚本、公共 Python 开发依赖和配置。 |
| `tests/` | 不执行安装的参数检查与 Ascend 依赖检查回归测试。 |

镜像清单、Dockerfile、镜像专用依赖、冒烟测试、构建规划器、schema 和发布策略由消费仓库
维护。此次初始抽取保留 ruicx/images 现有能力行为，尚未合并 Luciole 的专有差异。

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

在 Linux 或 Git Bash 中运行：

```bash
bash tests/install-arguments.sh
bash tests/ascend-pip-check.sh
mapfile -t shell_files < <(git ls-files '*.sh')
shellcheck "${shell_files[@]}"
shfmt -d -i 4 -ci "${shell_files[@]}"
```

这些检查不安装软件，也不构建镜像。消费仓库还需执行自己的清单校验、原生镜像构建和冒烟
测试。抽取过程中保留能力行为，不兼容修改需单独审阅。

## 贡献

脚本按能力分类，注释使用英文，保留显式参数校验，两个 README 同步更新。提交标题使用
`Feat`、`BugFix`、`Refactor` 或 `Doc`，后接冒号和摘要；空行后以编号列表描述修改。
