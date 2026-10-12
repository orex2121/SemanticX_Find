# Этап 2 — Retrieval 0.2.1-alpha, 7 октября 2026

Filename retrieval теперь независимо проверяет части имени/пути, включая фрагменты внутри токена (`take12` → `shot-take123.json`). Этот режим не вызывает текстовые эмбеддинги. Неизвестные режимы ранжирования отклоняются. CLI получил `--ranking filename|lexical|semantic|hybrid_no_structure|hybrid`.

Фильтры узла и модели понимают `%` и `_` буквально, без неявного SQL wildcard. Визуальная индексация без vision provider отклоняется до изменения БД, в том числе до rebuild.

## Проверки

**22 passed**, logs/stage2-tests.log. Проверены все desktop/core сценарии первого этапа и новые случаи filename substring, буквальных фильтров, конфигурации vision и раздельного кэша PNG. В тесте кэша используются специально простые векторы; это тест механики, не качества модели.

## Сравнение режимов

Воспроизведение: `python scripts/compare_ranking.py`. Полный отчёт docs/ranking-comparison-lexical.json, лог logs/stage2-benchmark.log. Тестовый каталог и индекс оставлены в checkpoint_tmp/ranking-lexical, чтобы можно было изучить точные данные.

4 публичных ComfyUI workflow, 231 структурная запись, 6 размеченных запросов EN/RU. Файлы переименованы case_*.json. Повторный проход: 4 skipped, 0 processed, 0 errors.

| Режим | MRR | Recall@5 |
|---|---:|---:|
| Filename | 0 | 0 |
| Lexical | 1 | 1 |
| Hybrid без structure | 1 | 1 |
| Hybrid | 1 | 1 |
| Semantic | Не запускался | Нет локальных весов |

Это маленький smoke benchmark. Он подтверждает поиск без подсказок в именах, но не доказывает преимущество hybrid или семантической модели: lexical справляется с теми же запросами. Нужны более разнообразный corpus, сложные запросы и отрицательные примеры. В коде предусмотрен `--gemma --dimension 256/768` с уже проверенными локальными весами, без их автоматической загрузки.

## Следующие этапы

1. Повторно загрузить и проверить checkpoint Gemma; выполнить реальные CPU tests 256/768, OCR, offline и download/resume/cancel. Сохранять веса отдельным пакетом сразу после загрузки.
2. Собрать Windows launcher/runtime; сохранить binaries/manifest, затем реальные Windows/RTX 5090 acceptance tests. Linux offscreen не заменяет эту проверку.
3. Продолжить согласование с ТЗ: tokenizer-aware chunks, ANN/большие каталоги, фоновые очереди, просмотр каталогов без JSON, полная локализация ошибок и руководства EN/RU.
