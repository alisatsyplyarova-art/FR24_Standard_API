## Unreleased

### Added
- Testable upstream HTTP client with bounded retries and pacing.
- Stable-key round-robin behavior when the active area list changes.
- Flight Radar D Clock 1.1.132 response-contract tests and compatibility notes.
- Concurrent API load probe for 10, 50, and 100 clients.
- Configurable cap on FR24 areas processed per collector cycle (default 20).
- Fair round-robin scheduling so deferred geographic areas are serviced in subsequent cycles.
- Configurable minimum delay between upstream requests (default 250 ms).
- Configurable request timeout and exponential retry for transient network/HTTP failures.
- Unit tests for bounded scheduling and fairness.

### Changed
- Capture saving is now read once from the loaded configuration rather than re-reading the JSON file for every FR24 response.

# История изменений

## Unreleased — multi-area-cache-5s

- Многозонная регистрация запросов от ESP32.
- Сбор запросов в окне 5 секунд.
- Объединение пересекающихся областей; удалённые зоны остаются отдельными.
- Общий кеш самолётов и индивидуальная фильтрация ответа.
- 5-секундный кеш одинаковых HTTP-ответов.
- Расширенная статистика в `/health`.
- Документация по архитектуре, API, эксплуатации, разделению компонентов и дорожная карта.

> Изменения находятся в отдельной ветке. Нагрузочное тестирование и проверка на реальном HAR ещё обязательны.
