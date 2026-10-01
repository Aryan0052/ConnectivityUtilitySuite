import serial
from typing import Optional


class ModbusRTUTransport:
    """
    Low-level Modbus RTU transport.

    Responsibilities:
    - Open / close serial port
    - Maintain COM port and baud rate
    - Send raw bytes
    - Receive raw bytes
    - Handle communication timeout
    - Provide Modbus RTU CRC calculation
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 9600,
        timeout: float = 2.0,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self._serial: Optional[serial.Serial] = None

    # ---------------------------------------------------------
    # CONNECTION
    # ---------------------------------------------------------

    def connect(
        self,
        port: Optional[str] = None,
        baudrate: Optional[int] = None,
    ) -> bool:
        """
        Open the RTU serial connection.
        """

        if port is not None:
            self.port = port

        if baudrate is not None:
            self.baudrate = baudrate

        if not self.port:
            raise ValueError("COM port is not specified")

        self.disconnect()

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )

            return self._serial.is_open

        except (serial.SerialException, OSError):
            self._serial = None
            return False

    def disconnect(self) -> None:
        """
        Close the RTU connection.
        """

        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            except Exception:
                pass

        self._serial = None

    # ---------------------------------------------------------
    # CONNECTION STATUS
    # ---------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """
        Return True when the serial connection is open.
        """

        return (
            self._serial is not None
            and self._serial.is_open
        )

    @property
    def connected_port(self) -> Optional[str]:
        return self.port if self.is_connected else None

    @property
    def connected_baudrate(self) -> Optional[int]:
        if not self.is_connected:
            return None

        return self._serial.baudrate

    # ---------------------------------------------------------
    # SERIAL SETTINGS
    # ---------------------------------------------------------

    def set_baudrate(self, baudrate: int) -> None:
        """
        Change baud rate of the currently connected port.
        """

        baudrate = int(baudrate)

        if baudrate <= 0:
            raise ValueError("Invalid baud rate")

        self.baudrate = baudrate

        if self.is_connected:
            self._serial.baudrate = baudrate
            self.reset_input_buffer()

    def set_timeout(self, timeout: float) -> None:
        """
        Change serial RX timeout.
        """

        if timeout < 0:
            raise ValueError("Timeout cannot be negative")

        self.timeout = float(timeout)

        if self.is_connected:
            self._serial.timeout = self.timeout

    # ---------------------------------------------------------
    # BUFFER MANAGEMENT
    # ---------------------------------------------------------

    def reset_input_buffer(self) -> None:
        """
        Clear any unread RX data.
        """

        if self.is_connected:
            self._serial.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        """
        Clear pending TX data.
        """

        if self.is_connected:
            self._serial.reset_output_buffer()

    @property
    def bytes_waiting(self) -> int:
        """
        Number of bytes currently waiting in RX buffer.
        """

        if not self.is_connected:
            return 0

        return self._serial.in_waiting

    # ---------------------------------------------------------
    # RAW TRANSMISSION
    # ---------------------------------------------------------

    def write(self, data: bytes) -> int:
        """
        Send raw bytes through RS-485.
        """

        if not self.is_connected:
            raise ConnectionError("Modbus RTU is not connected")

        if not isinstance(data, bytes):
            raise TypeError("RTU data must be bytes")

        written = self._serial.write(data)
        self._serial.flush()

        return written

    # ---------------------------------------------------------
    # RAW RECEPTION
    # ---------------------------------------------------------

    def read(self, size: int = 0) -> bytes:
        """
        Read raw bytes.

        If size is 0, read all currently available bytes.
        """

        if not self.is_connected:
            raise ConnectionError("Modbus RTU is not connected")

        if size <= 0:
            size = self._serial.in_waiting

        if size <= 0:
            return b""

        return self._serial.read(size)

    def read_available(self) -> bytes:
        """
        Read all bytes currently available.
        """

        return self.read()

    # ---------------------------------------------------------
    # CRC
    # ---------------------------------------------------------

    @staticmethod
    def calculate_crc(data: bytes) -> bytes:
        """
        Calculate Modbus RTU CRC-16.

        Returns CRC in Modbus little-endian format.
        """

        crc = 0xFFFF

        for byte in data:
            crc ^= byte

            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1

        return crc.to_bytes(2, byteorder="little")

    @classmethod
    def append_crc(cls, data: bytes) -> bytes:
        """
        Append Modbus RTU CRC to a request.
        """

        return data + cls.calculate_crc(data)

    @classmethod
    def validate_crc(cls, frame: bytes) -> bool:
        """
        Validate CRC of a complete Modbus RTU frame.
        """

        if len(frame) < 3:
            return False

        received_crc = frame[-2:]
        calculated_crc = cls.calculate_crc(frame[:-2])

        return received_crc == calculated_crc