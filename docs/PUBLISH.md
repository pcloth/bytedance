# 发布 bytedance 1.0.0

## 发布状态

`bytedance 1.0.0` 已于 2026-10-24 发布到 [PyPI](https://pypi.org/project/bytedance/1.0.0/)。已通过 PyPI JSON API 核对版本、Python >=3.6 要求及两个发行文件，SHA-256 均与下表一致。

```bash
pip install 'bytedance==1.0.0'
# 按需安装共享凭证缓存、RSA/AES 能力
pip install 'bytedance[redis,crypto]==1.0.0'
```

## 发布前检查

2026-10-24 已核对：

- wheel 和源码包中的全部 SDK Python 文件、`contracts.json` 与当前源码一致。
- 包名为 `bytedance`，版本为 `1.0.0`，要求 Python >=3.6，Redis 和加密依赖为可选扩展。
- 修复后的 wheel 已在 Python 3.6、3.8、3.12 分别通过 55 项离线测试，详见 [验证记录](VALIDATION.md)。
- 本次修正 PyPI README 标题下划线长度后重新构建，两个文件均通过 Twine 7.0.0 的 `check --strict`。重建后的 wheel 在临时目录安装后通过 55 项离线测试，SDK 运行源码与此前验证版本一致。

本次已发布以下两个文件：

| 文件 | SHA-256 |
| --- | --- |
| `dist/bytedance-1.0.0-py3-none-any.whl` | `f09522ac66754117667e3bbb57f7950398089d34fe938237f522c5484f0ba2b4` |
| `dist/bytedance-1.0.0.tar.gz` | `66b9ad47ff327f91ecb402e2258a41df2185e98cb69ef43370964e57c7871f3a` |

## 检查并上传

以下保留本次发布所用命令供参考。`1.0.0` 已发布，后续发布应更新版本号、重新构建并核对文件名与哈希。

在项目根目录执行，使用独立发布环境；发布工具使用现代 Python，SDK 的最低 Python 版本保持不变。

```bash
python3 -m venv /tmp/bytedance-release-tools
/tmp/bytedance-release-tools/bin/python -m pip install twine
/tmp/bytedance-release-tools/bin/python -m twine check --strict \
  dist/bytedance-1.0.0-py3-none-any.whl dist/bytedance-1.0.0.tar.gz
```

使用有 `bytedance` 项目上传权限的 PyPI API token。以下命令会在终端提示输入 token，输入不会回显；不要把 token 写入源码、命令参数或提交记录。

```bash
/tmp/bytedance-release-tools/bin/python -m twine upload \
  --repository-url https://upload.pypi.org/legacy/ \
  --username __token__ \
  dist/bytedance-1.0.0-py3-none-any.whl dist/bytedance-1.0.0.tar.gz
```

## 上传后确认

已核对 [PyPI 1.0.0 页面](https://pypi.org/project/bytedance/1.0.0/) 对应的两个文件和 SHA-256。以下命令可在新的虚拟环境从 PyPI 安装并检查导入，避免本地源码影响结果；本次文档更新未执行该安装验证：

```bash
python3 -m venv /tmp/bytedance-pypi-smoke
/tmp/bytedance-pypi-smoke/bin/python -m pip install \
  --index-url https://pypi.org/simple 'bytedance[crypto]==1.0.0'
(cd /tmp && /tmp/bytedance-pypi-smoke/bin/python -c \
  'import bytedance; assert bytedance.__version__ == "1.0.0"; print(bytedance.__file__)')
```

发布流程参考 [PyPA 上传说明](https://packaging.python.org/en/latest/tutorials/packaging-projects/#uploading-the-distribution-archives)。
