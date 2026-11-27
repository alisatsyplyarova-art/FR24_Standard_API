# Независимые серверы и проекты для работы с данными о воздушных судах

> Реестр открытo найденных независимых проектов, серверов и клиентских реализаций, изученных при развитии FR24 Standard API. Официальный FR24 API намеренно исключён по требованию владельца проекта.
>
> **Назначение реестра:** зафиксировать, что именно делает каждый проект, откуда получает данные, какой интерфейс предоставляет и что из него применимо к нашей архитектуре. Наличие проекта в списке не означает, что его код используется у нас или что он проверен в эксплуатации.

Дата фиксации: 27.11.2026.

## 1. Краткая классификация

| Проект | Тип | Источник / протокол | Интерфейс | Практическая ценность |
|---|---|---|---|---|
| [igolaizola/fr24](https://github.com/igolaizola/fr24) | Go-клиент и CLI | FR24 LiveFeed, gRPC-Web, protobuf | CLI / библиотека | Высокая: независимая protobuf-схема |
| [grega/flight-finder](https://github.com/grega/flight-finder) | Flask API для устройств | FlightRadarAPI, не наш protobuf LiveFeed | REST/JSON | Очень высокая: компактный API для ESP32 |
| [t7spotter/liveflights](https://github.com/t7spotter/liveflights) | Flask REST-приложение | HTTP endpoints FR24 | REST/JSON | Высокая: пример REST-обёртки |
| [huntrw6/airspace](https://github.com/huntrw6/airspace) | Self-hosted Docker PWA | FR24 HTTP JSON feed и clickhandler | API для web UI | Высокая: архитектура опроса, лимиты, HTTP 429 |
| [AlexandrErohin/home-assistant-flightradar24](https://github.com/AlexandrErohin/home-assistant-flightradar24) | Home Assistant integration | FlightRadarAPI / HTTP источники | сущности Home Assistant | Средняя: атрибуты, история, интеграция |
| [Snr1s3/FlightsASL](https://github.com/Snr1s3/FlightsASL) | FastAPI + PostgreSQL | библиотека-клиент FR24 | REST/OpenAPI | Средняя: хранение и API расписаний |
| [mitchtech/flight-exporter](https://github.com/mitchtech/flight-exporter) | Prometheus exporter | данные о рейсах через FR24-клиент | /metrics | Средняя: мониторинг и метрики |
| [SInsanali/skywatch](https://github.com/SInsanali/skywatch) | Self-hosted FastAPI/Leaflet | ADS-B Exchange, airplanes.live, OpenFlights и др.; не FR24 | web UI / API | Низкая для FR24; полезен как пример ADS-B приложения |
| [Ethos6/free-flight-api](https://github.com/Ethos6/free-flight-api) | Self-hosted агрегирующий API | ADS-B источники; не FR24 LiveFeed | API | Низкая для нашего FR24 адаптера |
| [AndrewCTF/velocity](https://github.com/AndrewCTF/velocity) | Архив/сервис отслеживания | публичные источники авиационных/морских данных; не подтверждён наш FR24 протокол | web/API проект | Низкая; не использовать как источник protobuf mapping |
| [MaciejZiel/contrail](https://github.com/MaciejZiel/contrail) | Авиационный проект | ADSB.lol, не FR24 | приложение/API проекта | Низкая для FR24 интеграции |
| [FlightRadar24 Home Assistant ecosystem](https://github.com/AlexandrErohin/home-assistant-flightradar24) | Экосистема интеграции | сторонняя FlightRadarAPI библиотека | Home Assistant | Дублирует отдельную запись выше; сохранено как ориентир по интеграции |

## 2. Подробные карточки

### 2.1. igolaizola/fr24 — независимая реализация LiveFeed

Репозиторий: https://github.com/igolaizola/fr24

Go-клиент/CLI для получения данных FR24. В проекте присутствуют protobuf-файлы `pkg/proto/_common.proto` и `pkg/proto/_live_feed.proto`, описывающие общие сообщения и контейнер LiveFeed.

**Что полезно нам:**
- сверка структуры `Feed` и `FeedResponse`;
- номера и типы полей корневого Feed;
- различие обычного списка рейсов и selected flight list;
- поля Stats и server time;
- enum-значения и вложенные сообщения.

**Ограничения:** это не готовый REST-сервер для ESP32. Схема — независимое открытое описание протокола, а не официальная спецификация FR24. Её необходимо проверять на обезличенных реальных payload.

### 2.2. grega/flight-finder — API для маломощных устройств

Репозиторий: https://github.com/grega/flight-finder

Flask API, ориентированный на Wi-Fi/малоресурсные устройства. В описании проекта присутствуют маршруты:
- `/health`;
- `/closest-flight`;
- `/flights-in-radius`.

В выдаче предусмотрены координаты, высота, скорость, вертикальная скорость, регистрация, ICAO 24-bit и маршрут. Данные получает через библиотеку FlightRadarAPI, а не через наш gRPC-Web/protobuf декодер.

**Что полезно нам:**
- компактный контракт для микроконтроллера;
- отдельные операции «ближайший самолёт» и «самолёты в радиусе»;
- health endpoint;
- ограничение объёма JSON и выдача только нужных полей.

**Что не переносить автоматически:** конкретный upstream-клиент и его способы получения данных. Наш источник — собственный LiveFeed collector; контракт следует реализовать поверх нашего кэша.

### 2.3. t7spotter/liveflights — Flask REST/JSON

Репозиторий: https://github.com/t7spotter/liveflights

Flask-приложение, формирующее REST/JSON поверх HTTP endpoints FR24. Это пример того, как отделить получение данных от JSON интерфейса.

**Что полезно нам:** разделение upstream-опроса и downstream REST API, простая JSON-нормализация.

**Ограничение:** не принимает наш бинарный LiveFeed protobuf и не является прямой заменой текущему декодеру.

### 2.4. huntrw6/airspace — self-hosted PWA

Репозиторий: https://github.com/huntrw6/airspace

Docker-разворачиваемое приложение с картой, профилями воздушных зон и уведомлениями. Backend использует FR24 HTTP JSON feed и clickhandler; в проекте предусмотрены ограничения detail-запросов и обработка HTTP 429.

**Что полезно нам:**
- бюджетирование частоты upstream-запросов;
- аккуратная обработка HTTP 429 и ошибок upstream;
- разделение фонового сборщика и API для клиентов;
- контейнеризация и эксплуатационная структура self-hosted сервиса.

**Ограничение:** это полноценное приложение, а не чистый адаптер gRPC-Web LiveFeed.

### 2.5. AlexandrErohin/home-assistant-flightradar24

Репозиторий: https://github.com/AlexandrErohin/home-assistant-flightradar24

Интеграция Home Assistant, использующая стороннюю библиотеку FlightRadarAPI и HTTP-источники.

**Что полезно нам:** модель атрибутов воздушного судна, история, обновление сущностей и интеграция с автоматизацией.

**Ограничение:** не является реализацией нашего protobuf декодера и не доказывает доступность каждого поля в LiveFeed.

### 2.6. Snr1s3/FlightsASL

Репозиторий: https://github.com/Snr1s3/FlightsASL

FastAPI + PostgreSQL проект для хранения аэропортов и расписаний рейсов. Есть Swagger/OpenAPI и API для поиска/сохранения расписаний. Использует клиентскую библиотеку FR24.

**Что полезно нам:** структура FastAPI/OpenAPI, хранение справочных данных и расписаний.

**Ограничение:** не потоковый LiveFeed сервер и не замена нашему текущему API.

### 2.7. mitchtech/flight-exporter

Репозиторий: https://github.com/mitchtech/flight-exporter

Docker Prometheus exporter, публикующий метрики `/metrics` по воздушным судам в заданном радиусе.

**Что полезно нам:** мониторинг числа бортов, возраста данных, ошибок и состояния сборщика через Prometheus.

**Ограничение:** формат Prometheus metrics не подходит как основной JSON контракт ESP32.

### 2.8. SInsanali/skywatch

Репозиторий: https://github.com/SInsanali/skywatch

Self-hosted FastAPI/Leaflet приложение. Использует ADS-B источники, включая airplanes.live / ADS-B Exchange / OpenFlights, а не FR24 LiveFeed.

**Что полезно нам:** интерфейс карты, структура self-hosted авиационного приложения и альтернативные ADS-B источники.

**Ограничение:** не использовать как подтверждение структуры FR24 protobuf или как источник FR24 данных.

### 2.9. Ethos6/free-flight-api

Репозиторий: https://github.com/Ethos6/free-flight-api

Проект из экосистемы self-hosted flight API, агрегирующий ADS-B источники. Не является сервером FR24 LiveFeed.

**Что полезно нам:** общие идеи унифицированного API над несколькими ADS-B источниками, если в будущем будет принято решение о мульти-источниковом режиме.

**Ограничение:** не использовать для FR24 protobuf mapping.

### 2.10. AndrewCTF/velocity

Репозиторий: https://github.com/AndrewCTF/velocity

Проект архивирования/отслеживания объектов авиационной и морской тематики. В рамках текущего исследования не подтверждено, что он использует FR24 LiveFeed или совместимый протокол.

**Статус:** зафиксирован как найденный смежный проект, но не рекомендован как основа текущего FR24 сервера.

### 2.11. MaciejZiel/contrail

Репозиторий: https://github.com/MaciejZiel/contrail

Авиационный проект, использующий ADSB.lol, а не FR24 LiveFeed.

**Что полезно нам:** возможные идеи для альтернативного ADS-B источника и визуализации.

**Ограничение:** не является FR24 сервером.

## 3. Что из найденного применяем в FR24 Standard API

| Направление | Референс | Решение для нашего проекта |
|---|---|---|
| protobuf LiveFeed | igolaizola/fr24 | Сверять Feed/FeedResponse и enum; не считать схему официальной |
| API для ESP32 | grega/flight-finder | Ориентир для компактных /closest-flight и radius endpoints; внедрять только после согласования API-контракта |
| REST-обёртка | t7spotter/liveflights | Разделять upstream сбор и downstream JSON |
| Устойчивость upstream | huntrw6/airspace | Учитывать HTTP 429, ограничивать detail-запросы и частоту опроса |
| Интеграция/атрибуты | Home Assistant integration | Использовать как дополнительный ориентир по нормализации атрибутов |
| Расписания и хранение | FlightsASL | Рассматривать при появлении задачи на историческое хранение/расписания |
| Метрики | flight-exporter | Рассматривать для будущего мониторинга сервера |
| Карта и альтернативные источники | skywatch, free-flight-api, velocity, contrail | Только как смежные проекты, не как источник FR24 протокола |

На момент фиксации в нашей реализации уже применены/учтены:
- независимая сверка protobuf Feed и FeedResponse по igolaizola/fr24;
- разбор обычных и selected flight записей;
- перенос source stats и server time в состояние сервера;
- декодирование EMSAvailability;
- сохранение компактного JSON API для ESP32.

Это перечисление описывает изменения текущей рабочей ветки, но не означает, что все поля проверены на живом потоке. Unit tests добавлены, однако до отдельного запуска тестового набора их успешное прохождение не заявляется.

## 4. Что не следует смешивать

1. **FR24 LiveFeed protobuf** — бинарный протокол, который разбирает наш текущий сервер.
2. **FR24 HTTP JSON endpoints / FlightRadarAPI library** — другой способ получения данных, используемый рядом найденных проектов.
3. **ADS-B источники** (airplanes.live, ADSB.lol, ADS-B Exchange и другие) — самостоятельные источники и схемы.
4. **REST/JSON API проектов** — выходной интерфейс конкретного приложения; его наличие не означает, что проект получает данные тем же способом, что и мы.

Нельзя переносить номера protobuf полей из одного источника или проекта без проверки. Нельзя подменять внутренний FR24 ID адресом ICAO. Не следует копировать чужие HAR, cookies, токены, сессионные заголовки или необезличенные захваты.

## 5. Рекомендуемый порядок дальнейшего использования

1. Сначала завершить проверку protobuf mapping на обезличенных реальных payload.
2. Затем зафиксировать стабильный JSON schema нашего API и решить несовпадение `hex` / `icao_hex`.
3. После этого сравнить API контракт с flight-finder и решить, нужны ли отдельные endpoints для ближайшего борта и радиуса.
4. Отдельно добавить устойчивость upstream: backoff, HTTP 429, таймауты, метрики и возраст последнего успешного обновления.
5. Историческую БД и альтернативные ADS-B источники не добавлять без отдельной задачи.

## 6. Статус и ограничения исследования

- Официальный FR24 API не рассматривался.
- Проекты перечислены как найденные открытые репозитории, а не как проверенные production-сервера.
- Указанные функции и технологии зафиксированы по результатам просмотра доступных описаний/репозиториев; перед заимствованием кода требуется повторная проверка актуального состояния upstream.
- Ни один из перечисленных сторонних серверов не был развёрнут и не проходил интеграционные испытания с нашей ESP32 прошивкой в рамках этого исследования.
- Код сторонних проектов целиком не копировался.
