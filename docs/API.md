# HTTP API

## Проверка сервера

### GET /health

Возвращает статус, количество самолётов и статистику реестра областей:

- `status`
- `aircraft`
- `areas.registered_areas`
- `areas.merged_areas`
- `areas.requests_total`
- `areas.batches_total`
- `areas.batch_window_seconds`
- `areas.active_ttl_seconds`
- `now`

### GET /aircraft

Возвращает общий кеш самолётов для диагностики.

## Совместимый маршрут ESP32

### GET /v2/lat/{latitude}/lon/{longitude}/dist/{distance_nm}

Пример:

```text
http://SERVER:8765/v2/lat/54.91/lon/82.33/dist/50
```

Ограничения: широта -90..90, долгота -180..180, радиус больше 0 и не более 500 морских миль.

Поля ответа:
- `ac` — массив самолётов в зоне;
- `msg` — текст статуса;
- `now`, `ctime` — время ответа в миллисекундах Unix;
- `total` — число самолётов;
- `ptime` — сохранённое поле совместимости.

Элементы `ac` включают `fr24_id`, `lat`, `lon`, `seen`, `seen_pos`; `flight` и `track` добавляются при наличии.

## Важное поведение

Запрос регистрирует область для следующего цикла FR24. Ответ HTTP не ждёт нового запроса FR24: он формируется из текущего общего кеша. Поэтому сразу после подключения нового радара его первая выдача может быть пустой или неполной до завершения очередного цикла коллектора.

## Совместимость с Flight Radar D Clock 1.1.135

Прошивка `Flight_Radar_D_Clock_1_1_135` запрашивает маршрут `/v2/lat/{lat}/lon/{lon}/dist/{distance_nm}` и разбирает массив `ac`.

Обязательные поля ответа:
- Верхний уровень: `ac` (массив), `msg` (строка), `now` и `ctime` (Unix milliseconds), `total` (целое), `ptime` (число).
- Каждый самолёт: `fr24_id` (строка), `lat` и `lon` (числа), `seen` и `seen_pos` (секунды).

Дополнительные поля, которые сервер теперь декодирует, когда они присутствуют в исходном LiveFeed:
- `flight` — позывной из Feed.field_11;
- `track` — курс из Feed.field_4;
- `on_ground` — bool из Feed.field_10;
- `altitude_ft` и `speed_kt` — исходные значения Feed.field_5 и Feed.field_6, в футах и узлах;
- `hex` — ICAO HEX из ExtraFlightInfo.field_14 (не вычисляется из `fr24_id`);
- `aircraft_type`, `registration`, `flight_number`, `origin`, `destination` — поля ExtraFlightInfo, если FR24 их передал.

Числовые enum-поля `status`, `icon` и `source` сохраняются как коды; сервер не превращает их в придуманные текстовые подписи. Данные ExtraFlightInfo могут отсутствовать в обычной записи и присутствовать в selected flight. Коллектор объединяет оба набора по внутреннему ID FR24, а кеш обновляет только атрибуты, реально полученные в protobuf.

Поля вроде `airline_name`, `origin_name`, `destination_name` и `status_text` не формируются: для них пока нет подтверждённого источника в декодере. Отсутствующие значения остаются отсутствующими.
