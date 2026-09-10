# Mixed corpus sources

The expanded benchmark combines three source groups:

1. `documents.json`: ten small, controlled Agent/RAG reference documents authored for this project.
2. `technical/*.{md,mdx}`: a 38-document snapshot of the Chinese documentation from the bundled BotMux project. BotMux is MIT licensed; see `botmux/LICENSE`.
3. `public_domain/*.txt`: 60,000-character excerpts of Chinese public-domain novels obtained from Project Gutenberg:
   - 《西游记》, ebook 23962: https://www.gutenberg.org/ebooks/23962
   - 《红楼梦》, ebook 24264: https://www.gutenberg.org/ebooks/24264
   - 《儒林外史》, ebook 24032: https://www.gutenberg.org/ebooks/24032

The Gutenberg headers and license boilerplate are excluded from indexed excerpts. The novels are used only as cross-domain retrieval noise. The technical BotMux documents are harder near-domain distractors.
