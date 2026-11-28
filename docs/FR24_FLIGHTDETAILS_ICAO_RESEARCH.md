# FR24 FlightDetails — исследование получения ICAO

**Дата:** 28.11.2026  
**Проект:** `C:\FR24_Standard_API`  
**Статус:** отдельный RPC проверен успешно; интеграция в основной сборщик ещё не выполнена.

## 1. Итог исследования

Обычные записи LiveFeed, получаемые текущим декодером, не содержат ICAO address. Поэтому `icao_address` и `icao_hex` в API `/aircraft` остаются `null`. Это не ошибка HEX-конвертации: в обычной записи нет исходного значения.

Проверен отдельный метод FR24 `FlightDetails`, который принимает внутренний FR24 flight ID и возвращает `AircraftInfo`, включая `icao_address`.

Успешный контрольный пример:
- Callsign: `KAL053`
- FR24 ID: `1120075720`
- ICAO decimal: `7456053`
- ICAO hex: `71C535`
- HTTP status: `200`
- gRPC trailer: `grpc-status: 0`

Старый ID `1120058628` вернул `grpc-status: 5`, `grpc-message: Flight not found!`. ID может устареть; для теста нужен свежий ID из LiveFeed.

## 2. Найденные места в проекте

- `feed_decoder.py`, около строк 228–231: пытается получить `icao_address` из `ExtraFlightInfo`, поле 14; в обычных записях поле отсутствует.
- `model.py`, около строк 92–93: модель уже содержит `icao_address` и `icao_hex`.
- `aircraft_cache.py`, около строк 72–73: оба поля присутствуют в начальной записи кеша.
- `aircraft_cache.py`, `update()`: переносит поля из декодированной записи только если значение не `None`. Следовательно, последующий ICAO можно добавить отдельно, и следующий LiveFeed с `None` не должен его затереть.
- `aircraft_cache.py`, `snapshot()`: отдаёт оба поля наружу.
- `api_server.py`, около строк 134–144: API уже включает ICAO и `hex`, если он задан.
- `main.py`: общий `requests.Session`, HAR-заголовки, `UpstreamClient`, основной цикл LiveFeed и `CACHE.update(feeds)`.
- `grpc_web.py`: `decode_grpc_web_body()` и разбор фреймов.
- `protobuf_parser.py`: `iter_fields(data)`; поля содержат `number`, `wire_type`, `value`, `raw_value`.
- `tools/test_flight_details.py`: диагностический proof-of-concept, не production-клиент.

## 3. RPC и формат запроса

URL:

`https://data-feed.flightradar24.com/fr24.feed.api.v1.Feed/FlightDetails`

Content-Type ответа: `application/grpc-web+proto`.

Схема запроса из `_flight_details.proto`:

```proto
message FlightDetailsRequest {
    fixed32 flight_id = 1;
    _common.RestrictionVisibility restriction_mode = 2;
    bool verbose = 3;
}
```

В успешном тесте заданы `flight_id` и `verbose=true`; `restriction_mode` не передавался:

```python
protobuf = b"\x0d" + struct.pack("<I", flight_id) + b"\x18\x01"
```

Расшифровка:
- `0x0D` — поле 1, wire type 5 (`fixed32`);
- следующие 4 байта — `flight_id`, little-endian;
- `0x18` — поле 3, wire type 0 (`varint`);
- `0x01` — `verbose=true`.

gRPC-Web data frame:

```python
body = b"\x00" + len(protobuf).to_bytes(4, "big") + protobuf
```

`0x00` — data frame без compression; следующие 4 байта — длина protobuf payload в big-endian; далее payload.

## 4. Заголовки и HAR

Диагностический скрипт читает `www.flightradar24.com.har`, выбирает POST LiveFeed и копирует только разрешённые заголовки:

```python
ALLOWED = {
    "content-type", "x-grpc-web", "x-user-agent", "fr24-device-id",
    "fr24-platform", "origin", "referer", "user-agent", "accept",
}
```

Успешный запрос был выполнен без Cookie и Authorization. Не копировать в production произвольные заголовки из HAR и не логировать секретные значения. Если метод начнёт требовать авторизацию, корректно обработать отказ; не пытаться обходить ограничения.

## 5. Успешный результат диагностического скрипта

Файл: `tools/test_flight_details.py`  
Тестовый `FLIGHT_ID = 1120075720`.

```text
Flight ID: 1120075720
Sending one FlightDetails request...
HTTP status: 200
Content-Type: application/grpc-web+proto
Response bytes: 2882
Frame 0: flag=0x00, bytes=2857
ICAO decimal: 7456053
ICAO hex: 71C535
Frame 1: flag=0x80, bytes=15
Trailer: grpc-status:0
```

HTTP 200 сам по себе не означает успех RPC. Успех подтверждается trailer `grpc-status: 0`.

## 6. Как декодировать ответ

Схема ответа:

```proto
message FlightDetailsResponse {
    _common.AircraftInfo aircraft_info = 1;
    _common.ScheduleInfo schedule_info = 2;
    _common.FlightProgress flight_progress = 3;
    _common.ExtendedFlightInfo flight_info = 4;
    _common.FlightPlan flight_plan = 5;
    repeated _common.TrailPoint flight_trail_list = 6;
    _common.PositionBuffer position_buffer = 7;
}
```

В `_common.proto`: `AircraftInfo.icao_address` — `uint32`, поле 1.

Путь декодирования:
1. `decode_grpc_web_body(response.content)` разбирает gRPC-Web frames.
2. Найти data frame с флагом `0x00`; compressed frame пока пропускать/обрабатывать отдельно.
3. `iter_fields(payload)` разбирает `FlightDetailsResponse`.
4. Найти внешнее поле 1 с wire type 2 — вложенный `AircraftInfo`.
5. Внутри `AircraftInfo` найти поле 1 с wire type 0 — varint ICAO.
6. Проверить `0 <= icao_address <= 0xFFFFFF`.
7. Сформировать `icao_hex = f"{icao_address:06X}"`.
8. Разобрать trailer frame `0x80` и проверить `grpc-status`.

Пример логики (перед внедрением сверить точное имя байтового атрибута в `iter_fields`; wire type 2 может хранить bytes в `raw_value`):

```python
for outer in iter_fields(data_payload):
    if outer.number == 1 and outer.wire_type == 2:
        aircraft_info = outer.raw_value
        for field in iter_fields(aircraft_info):
            if field.number == 1 and field.wire_type == 0:
                icao_address = field.value
                icao_hex = f"{icao_address:06X}"
```

Trailer содержит текстовые пары, например `grpc-status:0` или `grpc-message:Flight not found!`. Не считать пустое тело успехом.

## 7. Архитектура и безопасная интеграция

Текущий `main.py` использует один `requests.Session()` для LiveFeed. Основной цикл после декодирования делает `CACHE.update(feeds)`. Не менять алгоритм LiveFeed и не встраивать FlightDetails в декодер обычных записей.

Рекомендуется отдельный модуль `flight_details_client.py` или `icao_enricher.py`:
1. Получить актуальный `CACHE.snapshot()`.
2. Выбрать самолёты с пустым `icao_address`.
3. Исключить ID, недавно проверенные или уже находящиеся в очереди.
4. Приоритизировать активные/воздушные самолёты.
5. Выполнять ограниченное число запросов последовательно через общий Session.
6. Разобрать data frame и trailer; успех — только `grpc-status == 0` и валидный ICAO.
7. Записать результат в кеш отдельным потокобезопасным методом, например `CACHE.set_icao(id, decimal, hex)`, под существующим `RLock`.
8. API `/aircraft` уже отдаёт эти поля; формат API менять не нужно.

Не делать запрос на каждый самолёт в каждом 10-секундном цикле. Текущий `upstream_interval_seconds=0.25` относится к LiveFeed и не является рекомендацией для FlightDetails.

Начальные проектные значения кеширования (не официальные лимиты FR24):
- успешный результат: кешировать по flight ID, например 24 часа;
- `grpc-status: 5` / NOT_FOUND: отрицательный TTL 5–15 минут;
- сетевые ошибки/5xx: ограниченный backoff;
- HTTP 429: увеличить паузу, не повторять немедленно;
- HTTP 401/403: прекратить enrichment и сообщить об отказе;
- malformed protobuf/неизвестный trailer: логировать, не сохранять фиктивные данные.

Кеш должен иметь TTL/ограничение размера. NOT_FOUND нельзя хранить бессрочно.

## 8. Обработка статусов

| Результат | Значение | Действие |
|---|---|---|
| HTTP 200 + `grpc-status: 0` + ICAO | Успех | Сохранить decimal и HEX |
| `grpc-status: 5` | Flight not found | Отрицательный TTL |
| HTTP 401/403 | Доступ запрещён | Не обходить; остановить enrichment |
| HTTP 429 | Rate limit | Увеличить паузу |
| HTTP 5xx / network error | Временная ошибка | Ограниченный backoff |
| Пустой body/нет корректного trailer | Неполный ответ | Диагностическая ошибка |
| ICAO вне 24-битного диапазона | Некорректное значение | Не сохранять |

## 9. Что пока НЕ сделано

На дату документа:
- `FlightDetails` успешно проверен отдельным скриптом;
- ICAO `71C535` для KAL053 подтверждён;
- автоматического вызова из `main.py` нет;
- `CACHE.set_icao()` не добавлен;
- rate limiter, очередь и TTL lookup cache не реализованы;
- интеграционные тесты не добавлены.

## 10. Следующий порядок работ

1. Прочитать полностью `tools/test_flight_details.py`, `grpc_web.py`, `protobuf_parser.py`, `upstream_client.py`.
2. Проверить точные поля `GrpcWebFrame` и `iter_fields`.
3. Написать unit-тесты request encoding, ICAO extraction, trailer success/NOT_FOUND.
4. Создать отдельный FlightDetails client.
5. Добавить `CACHE.set_icao()` с `RLock`.
6. Добавить ограниченную очередь, rate limit и положительный/отрицательный TTL.
7. Подключить enrichment после `CACHE.update(feeds)` в `main.py`.
8. Проверить `/aircraft`: KAL053 должен вернуть `icao_address=7456053`, `icao_hex="71C535"`.
9. Убедиться, что последующие LiveFeed updates не затирают заполненный ICAO.

**Контрольный пример:** FR24 ID `1120075720`, callsign `KAL053`, ICAO decimal `7456053`, HEX `71C535`, gRPC status `0`. ID исторический и может перестать находиться.

---
Этот файл — исследовательская документация и план. Он не означает, что production-интеграция уже выполнена.
