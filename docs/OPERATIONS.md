# Установка и эксплуатация (Windows)

## Требования

- Windows 10/11 или Windows Server 2019+.
- Python 3.11+.
- Доступ к FR24 LiveFeed, действительный локальный HAR-файл.
- Сетевой доступ ESP32 к TCP-порту 8765.

## Установка

В PowerShell:

```powershell
cd C:\FR24_Standard_API
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item radar_config.example.json radar_config.json
```

Заполните `radar_config.json` начальными координатами и радиусом в километрах. Параметры защиты FR24-запросов:\n\n- `max_areas_per_cycle`: максимум областей за один цикл (по умолчанию 20); остальные обслуживаются в следующих циклах по кругу.\n- `upstream_interval_seconds`: минимальная пауза между запросами к FR24 (по умолчанию 0,25 с).\n- `max_retries`: число повторов временных ошибок (по умолчанию 2).\n- `retry_backoff_seconds`: начальная задержка повторов, увеличивается экспоненциально.\n- `request_timeout_seconds`: таймаут одного запроса.\n- `active_area_ttl_seconds`: время жизни активной зоны. Поместите собственный `www.flightradar24.com.har` в корень проекта. Не отправляйте HAR в GitHub и не пересылайте его посторонним.

## Запуск

```powershell
cd C:\FR24_Standard_API
.\venv\Scripts\Activate.ps1
python main.py
```

API слушает `0.0.0.0:8765`. Разрешите входящие подключения TCP/8765 только из доверенной локальной сети.

## Проверка

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8765/v2/lat/54.91/lon/82.33/dist/50 | ConvertTo-Json -Depth 6
```

В `/health` следите за `registered_areas`, `merged_areas`, `requests_total` и `batches_total`. В `logs\collector.log` видны отдельные FR24-запросы по областям.

## Безопасность и резервное копирование

- Не коммитьте HAR, `radar_config.json`, cookies, токены и логи.
- Храните HAR и конфигурацию в защищённом локальном резервном копировании.
- Не публикуйте API в интернет без авторизации и TLS.
- Условия использования FR24 могут ограничивать кэширование и дальнейшую раздачу данных; проверьте разрешённый сценарий до публичного запуска.

## Откат

Для возврата к прежней логике переключитесь на исходную ветку `feature/esp32-dynamic-radar-area`. Новая логика находится отдельно в `feature/multi-area-cache-5s`.
