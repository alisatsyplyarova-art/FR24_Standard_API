import struct

from grpc_web import decode_grpc_web_body
from protobuf_parser import iter_fields


FLIGHT_DETAILS_URL = (
    "https://data-feed.flightradar24.com/"
    "fr24.feed.api.v1.Feed/FlightDetails"
)


class FlightNotFoundError(Exception):
    """FR24 не нашёл рейс."""


class FlightDetailsError(Exception):
    """Ошибка ответа FlightDetails."""


class FlightDetailsClient:
    def __init__(self, upstream, headers):
        self.upstream = upstream
        self.headers = headers

    def get_icao_address(self, flight_id):
        try:
            flight_id = int(flight_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FlightDetailsError("Некорректный flight_id") from exc

        if not 0 <= flight_id <= 0xFFFFFFFF:
            raise FlightDetailsError("flight_id вне диапазона uint32")

        # fixed32 flight_id = field 1; verbose = field 3.
        protobuf_request = (
            b"\x0d"
            + struct.pack("<I", flight_id)
            + b"\x18\x01"
        )
        body = (
            b"\x00"
            + len(protobuf_request).to_bytes(4, "big")
            + protobuf_request
        )

        response = self.upstream.post(
            FLIGHT_DETAILS_URL,
            data=body,
            headers=self.headers,
        )

        grpc_status = None
        grpc_message = ""

        # Сначала проверяем gRPC-заголовки HTTP-ответа.
        for key, value in response.headers.items():
            key = key.lower()
            if key == "grpc-status":
                grpc_status = str(value).strip()
            elif key == "grpc-message":
                grpc_message = str(value).strip()

        # Затем читаем gRPC-Web trailer.
        try:
            frames = decode_grpc_web_body(response.content)
        except Exception as exc:
            raise FlightDetailsError(
                f"Не удалось декодировать gRPC-Web: {exc}"
            ) from exc

        data_frames = []

        for frame in frames:
            if frame.is_trailer:
                trailer = frame.payload.decode(
                    "ascii", errors="replace"
                )
                for line in trailer.replace("\r", "").split("\n"):
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if key == "grpc-status":
                        grpc_status = value
                    elif key == "grpc-message":
                        grpc_message = value

            elif frame.is_data:
                if frame.is_compressed:
                    raise FlightDetailsError(
                        "Сжатый gRPC-Web ответ не поддерживается"
                    )
                data_frames.append(frame.payload)

        if grpc_status == "5":
            raise FlightNotFoundError(
                grpc_message or f"Рейс {flight_id} не найден"
            )

        if grpc_status != "0":
            raise FlightDetailsError(
                f"Неуспешный gRPC status: {grpc_status!r}; "
                f"{grpc_message}"
            )

        if not data_frames:
            raise FlightDetailsError(
                "gRPC status=0, но данные ответа отсутствуют"
            )

        # FlightDetailsResponse.aircraft_info = field 1 (LEN).
        for payload in data_frames:
            try:
                response_fields = iter_fields(payload)

                for field in response_fields:
                    if field.number != 1 or field.wire_type != 2:
                        continue

                    # AircraftInfo.icao_address = field 1 (VARINT).
                    for aircraft_field in iter_fields(field.value):
                        if (
                            aircraft_field.number == 1
                            and aircraft_field.wire_type == 0
                        ):
                            icao = int(aircraft_field.value)

                            if 1 <= icao <= 0xFFFFFF:
                                return icao

            except Exception as exc:
                raise FlightDetailsError(
                    f"Ошибка разбора protobuf: {exc}"
                ) from exc

        raise FlightDetailsError(
            "В ответе FlightDetails отсутствует корректный ICAO"
        )