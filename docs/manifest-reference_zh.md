# 镜像清单参考

`src/<family>/image.yml` 是镜像族的版本化发行契约。路径和 glob 模式均相对于仓库根目录，
未定义字段会被拒绝。

## 共享安装脚本

`vendor/image-kit/scripts/` 下的脚本按职责划分，仅保留一层子目录：

| 目录 | 职责 |
| --- | --- |
| `system/` | 系统配置、用户、SSH、工作目录和软件包镜像源。 |
| `python/` | Python 环境配置和软件包安装。 |
| `dev/` | 开发工具、编译器、构建工具和 Shell 配置。 |
| `libraries/` | 第三方 C++ 库。 |
| `integrations/` | 平台和应用集成，包括 Ascend、ROS 2、llama.cpp 和 WSLg。 |

平台专用脚本保留名称前缀，例如 `python/cuda-pip-packages.sh` 和
`python/ascend-pip-packages.sh`，不再增加平台目录层级。
目录名称不决定执行顺序：各 Dockerfile 继续显式安排独立的 `COPY + RUN` 步骤，
消费这些脚本的清单在 `inputs` 中逐一登记完整路径。
目前没有镜像使用的脚本仍予以保留，供后续使用。

## 镜像族字段

| 字段 | 类型 | 契约 |
| --- | --- | --- |
| `schema_version` | 整数 | 必须为 `1`；未来不兼容格式需增加版本。 |
| `name` | 字符串 | 小写 kebab-case，并且必须等于 `<family>`。 |
| `description` | 字符串 | 非空、面向用户的镜像族简介。 |
| `dockerfile` | 路径 | 仓库内已存在的 Dockerfile。 |
| `context` | 路径 | 仓库内已存在的构建上下文。 |
| `platforms` | 列表 | 只允许一个平台：`linux/amd64` 或 `linux/arm64`；内部依赖的平台必须相同。 |
| `inputs` | 列表 | 已存在的路径或 glob；变更时重建该族全部变体。 |
| `publish` | 布尔值 | 是否允许从 `main` 发布选中的变体。 |
| `variants` | 列表 | 一个或多个变体定义。 |

## 变体字段

| 字段 | 类型 | 契约 |
| --- | --- | --- |
| `id` | 字符串 | 浮动标签名；小写分段可用 `.`、`_`、`-`，禁止 `latest`。 |
| `base.image` | 字符串 | 带明确版本标签的外部镜像；禁止 `latest` 和 `master`。 |
| `base.digest` | 字符串或 null | 该键必填。`sha256:` 值用于固定基础镜像；`null` 或 YAML 空值表示按 `base.image` 标签跟踪。 |
| `build_args` | 映射 | 传给对应 Dockerfile `ARG` 声明的任意非秘密标量值；疑似秘密的键会被拒绝。 |
| `mirror` | 枚举 | `upstream` 或显式选择的 `aliyun`。 |
| `runtime.ssh.mode` | 枚举 | 可选的共享能力配置：`disabled`、`key-only` 或 `password`；声明后渲染为 `SSH_MODE`。 |
| `dependencies` | 列表 | 以 BuildKit 命名上下文暴露的内部目标。 |
| `tests` | 列表 | 一个或多个已存在的仓库相对冒烟测试脚本。 |

每个依赖包含 `family`、`variant` 和 `context`。同一消费变体中的 context 名不能重复，且
必须对应 Dockerfile 的命名上下文：

```yaml
dependencies:
  - context: internal_base
    family: base
    variant: ubuntu-24.04
```

```dockerfile
FROM internal_base AS development
```

Buildx Bake 会把 `internal_base` 解析为 `target:<generated-base-target>`，因此 PR 的内部依赖
不会读取 Registry 中的旧镜像。

对于外部基础镜像，有 digest 时会把 `BASE_IMAGE` 生成为 `image:tag@sha256:...`；值为 `null`
时则生成为 `image:tag`。YAML 的 `digest: null` 与 `digest:` 等价，但完全省略该键是非法的，
从而要求清单明确表达可复现性选择。开发镜像使用 `digest: null` 接收同一明确标签下发布的
更新；需要固定基础镜像时仍可使用 `sha256`。生成的 Bake 目标通过 `pull: true` 检查更新。
同一个 Git 提交的两次构建可能不同，因此 CI 为每个构建批次分配独立的不可变发布标签。
基础镜像仍必须使用明确版本标签，且仍禁止 `latest` 和 `master`。

`build_args` 是镜像专用构建选项的扩展点，不需要修改 Python 解析器。Bake 生成前，值会统一
转换为字符串。因此接收布尔选项的脚本必须自行归一化，例如 YAML 的 `true` 可能变为 `True`；
`${NAME}` 这类环境变量表达式不会被插值，而会保留为字面字符串。schema 仍禁止在
`build_args` 之外添加未知字段。

`mirror` 与自由构建参数不同：规划器会校验该枚举并把它渲染为 `PACKAGE_MIRROR`。Dockerfile
把这个值传给最终镜像源能力，由该脚本维护支持值：`upstream` 保持基础镜像源不变，`aliyun`
在所有软件安装完成后重写最终保留的 apt 和 pip 配置。运行时不会探测镜像源。

`runtime.ssh.mode` 是有类型的运行时策略，不是自由构建参数。每个变体都必须显式选择，避免
新增变体时无意继承密码认证。规划器会把它转换为内部 `SSH_MODE` 构建参数；Dockerfile 和
入口脚本只从 `DEFAULT_USER` 推导唯一允许的 SSH 账号，不再提供独立登录用户选择器。

## 完整结构

```yaml
schema_version: 1
name: example
description: Example development image
dockerfile: src/example/Dockerfile
context: .
platforms: [linux/amd64]
inputs:
  - src/example/**
  - vendor/image-kit/scripts/dev/example-tool.sh
publish: true
variants:
  - id: ubuntu-24.04
    base:
      image: ubuntu:24.04
      digest: sha256:<64位小写十六进制字符>
    build_args:
      DEFAULT_USER: developer
      DEFAULT_UID: 1000
      DEFAULT_GID: 1000
      WORKSPACE_DIR: /workspace
      TOOL_VERSION: "1.2.3"
    mirror: upstream
    runtime:
      ssh:
        mode: disabled
    dependencies: []
    tests:
      - src/example/tests/smoke.sh
```

如需跟踪明确标签，请保留该键并显式设为 null（也可以让 YAML 值留空）：

```yaml
base:
  image: ubuntu:24.04
  digest: null
```

JSON Schema 负责结构校验；`images validate` 还会校验路径、目录与名称一致性、重复变体、
疑似秘密的构建参数、`DEFAULT_USER` 契约、依赖目标、重复 context、冒烟测试、DAG 环以及双语
文档。`DEFAULT_USER=root` 时必须省略 `DEFAULT_UID` 和 `DEFAULT_GID`；其他合法 Linux 用户名
必须同时提供这两个数值字段。

## 包内 schema 与消费端策略

权威 schema 随包提供，位于 `image_kit/schemas/image.schema.json`，消费仓库不需要本地
`schemas/` 目录。`mirror` 和 `runtime` 是可选的共享能力字段；省略时不注入
`PACKAGE_MIRROR` 或 `SSH_MODE`。镜像账号约束、必填运行配置、双语文档和发布权限由消费
仓库负责。当前版本支持 family/variant v1 契约，每个镜像族使用一个原生平台，不自动解释
其他 manifest 格式。
