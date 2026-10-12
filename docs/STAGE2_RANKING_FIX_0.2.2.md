# Semantic ranking fix — 0.2.2-alpha

Дата проверки: 7 октября 2026, Windows, NVIDIA GeForce RTX 5090.

## Исправление

Hybrid-ранжирование для индексов с реальными эмбеддингами теперь использует
семантическое сходство как основной сигнал. Лексические, структурные и
filename-сигналы остаются вспомогательными. Для lexical-only индексов прежние
веса сохранены.

Регрессионный случай: запрос `создание картинки моделью Qwen` должен ставить
`qwen_generation.json` выше `qwen_edit.json`, даже если длинная справочная
заметка edit-workflow содержит общие слова `Qwen` и `image`.

## Проверка

- 23 теста прошли (`23 passed`).
- EmbeddingGemma 2: ревизия `914f7f89142e33e77833254d9c9b90c3cef7303b`.
- Backend: RTX 5090, CUDA 13.0, BF16, 256D.
- Реальный индекс: 4 workflow, 231 chunk/vector.
- Все шесть контрольных запросов вернули ожидаемый первый файл:
  - редактирование Qwen → `qwen_edit.json`;
  - создание Qwen → `qwen_generation.json`;
  - нейросетевой апскейл → `clarity_upscale.json`;
  - Qwen Image 2512 → `qwen_generation.json`;
  - tiled upscale → `clarity_upscale.json`;
  - upscale model → `upscale_by_model.json`.

Пересоздавать существующий 256D-индекс после этого изменения не требуется:
изменена только формула ранжирования, а не формат или содержимое векторов.
