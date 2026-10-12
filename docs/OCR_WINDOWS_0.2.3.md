# OCR and screenshot search — 0.2.3-alpha

Дата проверки: 7 октября 2026, Windows.

## Конфигурация

- RapidOCR 3.9.2
- ONNX Runtime 1.30.0
- PP-OCRv4 mobile detector
- orientation classifier
- Cyrillic PP-OCRv3 mobile recognizer

Модели загружаются в `models/rapidocr`, записываются в manifest с SHA-256 и
проверяются перед каждым созданием OCR engine. Обработка выполняется локально.

Кириллический recognizer выбран вместо китайского профиля по умолчанию: он
значительно лучше распознаёт русские подписи интерфейса и сохраняет поддержку
латинских имён ComfyUI nodes.

## Реальная проверка

На пользовательском скриншоте SemanticX Find OCR извлёк русские подписи,
`qwen_generation.json`, `Qwen-Image-2512`, `LoraLoaderModelOnly` и
`UNETLoader`. Поиск без текстового запроса, только с прикреплённым скриншотом,
вернул первым `qwen_generation.json`.

OCR является query-side функцией и не меняет формат индекса. Для включения OCR
пересоздавать существующий 256D-индекс не требуется.
