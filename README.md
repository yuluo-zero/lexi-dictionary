# 划词词典 · Lexi Dictionary

一个轻量、干净、**划词即查**的 Windows 中英词典。

选中文字 → 出现小标志 → 点开才查；不点，它不会打扰你。

![宣传片封面](docs/media/cover.png)

[▶ 45 秒宣传片](docs/media/lexi_promo.mp4) · [B站](https://www.bilibili.com/video/BV1iP4V6wEwc)

## 功能

- **划词即查**：全局划词，只在选中文字后出现小标志
- **多来源**：ECDICT、WordNet、CC-CEDICT 离线；有道、柯林斯、Merriam-Webster、Datamuse 在线
- **中英 / 英英 / 整句翻译**
- **生词本 + FSRS-6**：忘记 / 模糊 / 记得 / 简单，按记忆状态安排复习
- **悬浮球**：快捷搜索、待复习角标、贴边收起
- **查询历史**：可勾选删除，也可一键清空
- **数据本地**：生词、历史、设置都在本机；支持备份 / 恢复
- **来源可选**：ECDICT / WordNet / 柯林斯 / 韦氏 / 有道；支持并列对照

## 截图

| 查词 | 多来源 |
| --- | --- |
| ![查词](docs/screenshots/search.png) | ![多来源](docs/screenshots/dictionaries.png) |

| FSRS 复习 | 快捷搜索 |
| --- | --- |
| ![复习](docs/screenshots/review.png) | ![快捷搜索](docs/screenshots/quick-search.png) |

## 下载（普通用户）

Windows 10/11 64 位，解压即用，不需要装 Python：

**[下载最新便携版](https://github.com/yuluo-zero/lexi-dictionary/releases/latest)**

解压后双击：

```
start.cmd
```

不想看到命令行窗口，双击 `start.vbs`。

- 数据全部在解压目录的 `data/` 里
- 删除文件夹即卸载
- 不包含 API Key、个人设置或用户数据
- 便携包约 193 MB

## 运行（源码）

需要 **Windows 10/11**、**Python 3.12+**。

```powershell
git clone https://github.com/yuluo-zero/lexi-dictionary.git
cd lexi-dictionary

py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python main.py
```

## 离线词典

仓库**不包含**词典数据库（体积大，且各自有许可证）。首次运行前，把以下文件放进 `downloads/`：

| 文件 | 来源 |
| --- | --- |
| `ecdict.csv` | [ECDICT](https://github.com/skywind3000/ECDICT) |
| `cedict.txt.gz` | [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) |
| `wordnet.zip` | [Princeton WordNet](https://wordnet.princeton.edu/)（NLTK 语料包格式） |

然后构建：

```powershell
python tools/build_dicts.py data\dict
```

生成：

```
data/dict/ecdict.db
data/dict/cedict.db
data/dict/wordnet.db
```

没有离线库时，在线查询仍可使用，但启动会提示离线词典缺失。

## 在线词典 / API Key

- 有道：公开接口，无需 Key
- 柯林斯：经有道公开接口读取
- **Merriam-Webster**：需要自己申请免费 Key  
  <https://dictionaryapi.com/>  
  在应用「设置 → 词典来源」里填 Collegiate / Learner's Key
- 翻译：MyMemory / Google / DeepL（DeepL 需要 Key）

> API Key 只保存在本机 `data/settings.json`，不会上传仓库。  
> 免费版韦氏额度约 1000 次/天/Key，仅非商业使用。

## 技术栈

- Python 3.12 + PySide6
- SQLite（ECDICT / CC-CEDICT / WordNet / 生词本）
- 全局低层鼠标/键盘钩子 + 剪贴板保护
- FSRS-6（vendored `app/vendor/fsrs`，MIT）
- 原创合成宣传片 BGM

## 数据与许可

- 代码：[MIT](LICENSE)
- FSRS：MIT，见 `app/vendor/fsrs/LICENSE`
- ECDICT：MIT
- WordNet：Princeton WordNet License
- CC-CEDICT：CC BY-SA 4.0
- 有道 / 柯林斯 / Merriam-Webster：在线接口，遵循各自服务条款
- 词典数据库不随仓库分发；请自行下载并遵守对应许可证

## 说明

这是一个个人向的轻量词典项目，不是牛津/剑桥/韦氏官方产品，也不替代它们的完整授权版本。

