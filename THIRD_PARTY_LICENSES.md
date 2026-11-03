# 第三方许可证 / Third-Party Licenses

本项目的**代码**使用 MIT License，见根目录 `LICENSE`。

便携包还包含第三方词典数据和运行时库。它们**不会**因为本项目使用 MIT 而变成 MIT；以下许可证分别适用。

## 一览

| 内容 | 许可证 | 完整文本 |
| --- | --- | --- |
| 本项目代码 | MIT | `LICENSE` |
| ECDICT | MIT | `LICENSES/ECDICT-MIT.txt` |
| WordNet 3.0 | Princeton WordNet License | `LICENSES/WORDNET-3.0.txt` |
| CC-CEDICT | CC BY-SA 4.0 | `LICENSES/CC-BY-SA-4.0.txt` |
| PySide6 / Qt | LGPL-3.0 | `LICENSES/LGPL-3.0.txt`、`LICENSES/PYSIDE6-QT-NOTICE.txt` |
| Python 运行时 | PSF License | `LICENSES/PYTHON-PSF.txt` |
| FSRS (py-fsrs) | MIT | `LICENSES/FSRS-MIT.txt` |

## ECDICT

- 项目：https://github.com/skywind3000/ECDICT
- 版权：Copyright (c) 2025 Linwei
- 许可证：MIT
- 修改说明：原始 CSV 被导入为 SQLite 数据库 `ecdict.db`；词条内容未改写。

## WordNet 3.0

- 项目：https://wordnet.princeton.edu/
- 版权：WordNet 3.0 Copyright 2006 by Princeton University. All rights reserved.
- 许可证：Princeton WordNet License
- 修改说明：原始 WordNet 数据被转换为 SQLite 数据库 `wordnet.db`。
- 完整声明必须随所有副本分发，见 `LICENSES/WORDNET-3.0.txt`。

## CC-CEDICT

- 项目：https://www.mdbg.net/chinese/dictionary?page=cc-cedict
- 版权：CC-CEDICT © MDBG contributors
- 许可证：Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
- 许可证：https://creativecommons.org/licenses/by-sa/4.0/
- 修改说明：原始 CEDICT 文本被转换为 SQLite 数据库 `cedict.db`。
- 该数据库及其修改按 CC BY-SA 4.0 共享；本项目代码仍为 MIT。
- 完整法律文本见 `LICENSES/CC-BY-SA-4.0.txt`。

## PySide6 / Qt

- 项目：https://www.qt.io/qt-for-python
- 版权：The Qt Company Ltd. and contributors
- 许可证：LGPL-3.0（本项目使用）
- 完整 LGPL 文本：`LICENSES/LGPL-3.0.txt`
- 说明：`runtime/Lib/site-packages/PySide6/` 下的库为独立文件，可被替换；应用源码随包提供。
- 详见 `LICENSES/PYSIDE6-QT-NOTICE.txt`。

## Python

- 项目：https://www.python.org/
- 许可证：Python Software Foundation License
- 完整文本：`LICENSES/PYTHON-PSF.txt`

## FSRS

- 项目：https://github.com/open-spaced-repetition/py-fsrs
- 许可证：MIT
- 完整文本：`LICENSES/FSRS-MIT.txt`

## 在线词典服务

有道、柯林斯、Merriam-Webster、Datamuse 通过在线接口访问，**不随包分发其词典数据**。使用时需遵守各自服务条款。本包不包含任何 API Key。

## 宣传片音乐

宣传片 BGM 为本项目原创合成，不使用第三方采样。
