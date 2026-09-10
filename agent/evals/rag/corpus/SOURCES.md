# Mixed corpus sources

扩展语料由三个部分组成：

1. `documents.json`：本项目编写的 10 篇 Agent/RAG 目标资料，用于定义相关文档。
2. `technical/*.{md,mdx}`：从仓库内 MIT 许可的 BotMux 中文文档快照中选取 8 篇，覆盖快速开始、Dashboard、群聊、Web Terminal、语音、Zmx、Tmux 和卡片。这部分保留少量同领域近邻干扰，而不让整个语料都集中在 Agent/RAG。
3. `public_domain/*.txt`：Project Gutenberg 公版文本的固定 35,000 字符节选，覆盖多个领域：

| 领域 | 书目 | Ebook |
|---|---|---|
| 文学 | 《西游记》 | https://www.gutenberg.org/ebooks/23962 |
| 文学 | 《红楼梦》 | https://www.gutenberg.org/ebooks/24264 |
| 文学 | 《儒林外史》 | https://www.gutenberg.org/ebooks/24032 |
| 历史 | 《史记》 | https://www.gutenberg.org/ebooks/24226 |
| 地理/游记 | 《徐霞客游记》 | https://www.gutenberg.org/ebooks/23876 |
| 哲学 | 《道德经》 | https://www.gutenberg.org/ebooks/7337 |
| 军事 | 《孙子兵法》 | https://www.gutenberg.org/ebooks/23864 |
| 工艺技术 | 《天工开物》 | https://www.gutenberg.org/ebooks/25273 |
| 诗歌 | 《李太白集》 | https://www.gutenberg.org/ebooks/24060 |
| 生物学 | *On the Origin of Species* | https://www.gutenberg.org/ebooks/1228 |
| 经济学 | *An Inquiry into the Nature and Causes of the Wealth of Nations* | https://www.gutenberg.org/ebooks/3300 |

小说和其他公版文本只作为跨领域检索噪声。下载时去除了 Project Gutenberg 头部，并截取固定长度，使基线可重复。评测不把这些噪声文档标记为相关文档。
