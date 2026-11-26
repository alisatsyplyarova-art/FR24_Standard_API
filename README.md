# FR24 Standard API

Локальный сборщик данных Flightradar24 LiveFeed с HTTP API.

## Возможности

- Опрос FR24 каждые 10 секунд.
- Декодирование protobuf / gRPC-Web.
- Кэширование координат воздушных судов.
- Удаление устаревших позиций.
- HTTP API на порту 8765.
- Фильтрация по расстоянию в морских милях (NM).

## Требования

- Windows 10 / Windows Server 2019 или новее.
- Python 3.11 или новее.
- requests 2.31.0 или новее.
- Собственный HAR-файл FR24 LiveFeed.

## Установка

    git clone https://github.com/alisatsyplyarova-art/FR24_Standard_API.git
    cd FR24_Standard_API
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt

## Настройка

Создайте radar_config.json на основе radar_config.example.json. Укажите latitude, longitude и radius_km. Подготовьте собственный www.flightradar24.com.har.

HAR-файл не публикуйте: он может содержать идентификаторы устройства и данные сессии.

## Запуск

    python main.py

## API

- GET /health — состояние сервера.
- GET /aircraft — все воздушные суда.
- GET /v2/lat/{latitude}/lon/{longitude}/dist/{distance} — фильтрация по расстоянию в NM.

fr24_id — внутренний идентификатор FR24, не ICAO HEX.

## Безопасность

Не публикуйте HAR, cookies, токены, локальную конфигурацию, логи и виртуальное окружение.

Лицензия пока не определена.

Автор: alisatsyplyarova-art
