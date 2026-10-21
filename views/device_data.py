"""Device data model for the Mini SCADA scanner.

The scanner turns every valid Modbus response into a DeviceReading.
Readings go to the UI now and, in the database phase, to a non-blocking
database queue (see DeviceReading.to_records for the future record shape).
"""
import struct
from dataclasses import dataclass, field
from datetime import datetime

QUALITY_GOOD = "GOOD"
QUALITY_BAD = "BAD"

# Register map used for the normal poll of each device type.
#   DI: digital_input_view.py  _run_tx_rx_cycle   -> FC01, address 0x0000, quantity 0x0010
#   DO: digital_output_view.py handle_do_refresh  -> FC01, address 0x0000, quantity 0x0010
#       Response: [slave, 01, 02, DATA1, DATA2, CRC]; DATA1 bit0..7 = ch1..8,
#       DATA2 bit0..7 = ch9..16; 1 = ON.
#   AI: analog_input_test_mode_view.py RUN -> FC04, address 0x0000, quantity 0x0010
#       (16 registers). Response 37 bytes: [slave, 04, 0x20, 8 x float32 big-endian
#       (CH1..CH8, 4 bytes each), CRC]. The value unit (mA / V / mV) depends on the
#       channel I/P type, read separately with FC03 address 0 quantity 8.
#   AO: no register map yet; the previous placeholder read is kept and flagged
#       "verified": False until it is defined.
DEVICE_PROFILES = {
    "DI": {"function": 1, "address": 0, "count": 16, "verified": True},
    "DO": {"function": 1, "address": 0, "count": 16, "verified": True},
    "AI": {"function": 4, "address": 0, "count": 16, "verified": True},
    "AO": {"function": 3, "address": 0, "count": 1, "verified": False},
    # MFT (Multi Function Transducer): MFT.jsx / ModbusTestPanel default read layout - FC03,
    # address 0, 80 registers = 40 FLOAT32 values (measurements.js MEASUREMENTS), word order
    # CD AB (= LSRF, low register first). The reply is read in pages of 20 registers
    # (readRegisters chunk=20) because the module only answers the first ~70 registers of one long read.
    "MFT": {"function": 3, "address": 0, "count": 80, "verified": True,
            "data_format": "float32", "word_order": "LSRF", "chunk": 20},
}

# The 40 parameters of the MFT, in register order (2 registers each): (name, unit).
MFT_PARAMS = (
    ("IA", "A"), ("IB", "A"), ("IC", "A"), ("IN", "A"),
    ("AVrms", "V"), ("BVrms", "V"), ("CVrms", "V"),
    ("FreqA", "Hz"), ("FreqB", "Hz"), ("FreqC", "Hz"),
    ("VA_VB", "deg"), ("VB_VC", "deg"), ("VA_VC", "deg"),
    ("IA_IB", "deg"), ("IB_IC", "deg"), ("IA_IC", "deg"),
    ("VA_IA", "deg"), ("VB_IB", "deg"), ("VC_IC", "deg"),
    ("P_A", "W"), ("P_B", "W"), ("P_C", "W"),
    ("Q_A", "var"), ("Q_B", "var"), ("Q_C", "var"),
    ("S_A", "VA"), ("S_B", "VA"), ("S_C", "VA"),
    ("PF_A", ""), ("PF_B", ""), ("PF_C", ""),
    ("VAB", "V"), ("VBC", "V"), ("VCA", "V"),
    ("VTHD_A", "%"), ("VTHD_B", "%"), ("VTHD_C", "%"),
    ("ITHD_A", "%"), ("ITHD_B", "%"), ("ITHD_C", "%"),
)


def read_chunk(device):
    """Registers per request for devices that must be read in pages (MFT), else 0 = one request."""
    return int(DEVICE_PROFILES.get(device.get("kind"), {}).get("chunk", 0) or 0)

# AI input-type register values (FC03, address 0, 8 registers = CH1..CH8), from
# analog_input_view.py / analog_input_test_mode_view.py.
AI_INPUT_TYPES = {
    0: "0-50mV", 1: "0-100mV", 2: "0-250mV", 3: "0-5V", 4: "0-10V",
    5: "4-20mA", 6: "0-20mA", 7: "-250mV to +250mV", 8: "-10V to +10V",
}
AI_CONFIG_READ = {"function": 3, "address": 0, "count": 8}


def ai_unit(input_type):
    """'mA' / 'mV' / 'V' for an AI input-type name, '' if unknown."""
    text = str(input_type)
    if "mA" in text:
        return "mA"
    if "mV" in text:
        return "mV"
    if "V" in text:
        return "V"
    return ""


_TYPE_MARKERS = (
    ("(DI)", "DI"), ("Digital Input", "DI"),
    ("(DO)", "DO"), ("Digital Output", "DO"),
    ("(AI)", "AI"), ("Analog Input", "AI"),
    ("(AO)", "AO"), ("Analog Output", "AO"),
    ("(MFT)", "MFT"), ("Transducer", "MFT"),
)


def device_kind(type_text):
    """'DI' / 'DO' / 'AI' / 'AO' / 'MFT' from the device type text, else None."""
    for marker, kind in _TYPE_MARKERS:
        if marker in str(type_text):
            return kind
    return None


@dataclass
class DeviceReading:
    timestamp: datetime
    device_id: int
    slave_id: int
    device_type: str
    function: int
    address: int
    channels: list = field(default_factory=list)  # [(channel_name, value), ...]
    quality: str = QUALITY_GOOD
    raw_response: str = ""
    units: list = field(default_factory=list)  # per channel, "" when unknown
    registers: list = field(default_factory=list)  # raw 16-bit register words (MFT register view)

    def to_records(self):
        """One flat record per channel (shape for the future database layer)."""
        return [
            {
                "timestamp": self.timestamp,
                "device_id": self.device_id,
                "slave_id": self.slave_id,
                "device_type": self.device_type,
                "channel": channel,
                "value": value,
                "unit": self.units[index] if index < len(self.units) else "",
                "quality": self.quality,
                "raw_response": self.raw_response,
            }
            for index, (channel, value) in enumerate(self.channels)
        ]


DATA_FORMATS = {            # how holding / input registers are shown (like Modbus Poll)
    "raw16": "UInt16 - unsigned (1 reg)",
    "int16": "Int16 - signed (1 reg)",
    "hex16": "Hex16 (1 reg)",
    "float32": "Float32 (2 regs)",
    "int32": "Int32 - signed (2 regs)",
    "uint32": "UInt32 - unsigned (2 regs)",
    "hex32": "Hex32 (2 regs)",
}
WIDE_FORMATS = ("float32", "int32", "uint32", "hex32")   # 2 registers per channel -> LSRF / MSRF applies
WORD_ORDERS = {             # order of the two 16-bit registers inside a 32-bit value
    "MSRF": "MSRF - high register first",
    "LSRF": "LSRF - low register first",
}


def decode_32bit(first, second, fmt, order):
    """Two consecutive registers -> one value. MSRF: first register is the high word
    (big-endian, the Modbus default); LSRF: first register is the low word (word-swapped)."""
    first, second = int(first) & 0xFFFF, int(second) & 0xFFFF
    high, low = (first, second) if order != "LSRF" else (second, first)
    raw = struct.pack(">HH", high, low)
    if fmt == "float32":
        return round(struct.unpack(">f", raw)[0], 3)
    if fmt == "int32":
        return struct.unpack(">i", raw)[0]
    return struct.unpack(">I", raw)[0]          # uint32 / hex32 (shown as hex by the display layer)


def format_value(value, fmt):
    """Text shown for one register value in the given data format."""
    if fmt == "hex16":
        return f"0x{int(value) & 0xFFFF:04X}"
    if fmt == "hex32":
        return f"0x{int(value) & 0xFFFFFFFF:08X}"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else f"{value:.4g}"
    return str(value)


# Set True to bring back the Hex/Float/Int + LSRF/MSRF output formats (form + live cards).
ENABLE_FORMATS = True


def effective_format(device):
    """Data format of a register device. AI input registers (FC04) default to Float32."""
    if device.get("kind") == "MFT":         # the MFT register map is always Float32 (word order is configurable)
        return "float32"
    if not ENABLE_FORMATS:
        return "raw16"
    fmt = device.get("data_format")
    if fmt in DATA_FORMATS:
        return fmt
    if device.get("kind") == "MFT":
        return "float32"
    return "float32" if device.get("kind") == "AI" and int(device.get("function", 0)) == 4 else "raw16"


def process_response(device, response, raw_response, timestamp):
    """Convert a valid pymodbus response into a DeviceReading.

    DI/DO: one 0/1 value per channel. AI/AO: raw register values (scaling is
    added once the live-value register map is defined). Raises ValueError if
    the response does not contain the requested number of items.
    """
    kind = device.get("kind")
    function = int(device.get("function", 0))
    count = int(device.get("count", 1))
    prefix = kind or "CH"
    fmt = effective_format(device) if function in (3, 4) else "raw16"
    if fmt in WIDE_FORMATS:
        registers = [int(reg) for reg in list(getattr(response, "registers", None) or [])[:count]]
        if len(registers) < count:
            raise ValueError(f"expected {count} registers, received {len(registers)}")
        # 2 registers per channel; MSRF = high word first (default), LSRF = low word first.
        order = "LSRF" if kind == "MFT" else (device.get("word_order") or "MSRF")   # MFT is always CD AB (LSRF)
        items = [decode_32bit(registers[i], registers[i + 1], fmt, order) for i in range(0, count - 1, 2)]
        if kind == "MFT":                       # named parameters with units instead of MFT1..MFTn
            names = [MFT_PARAMS[i][0] if i < len(MFT_PARAMS) else f"P{i + 1}" for i in range(len(items))]
            units = [MFT_PARAMS[i][1] if i < len(MFT_PARAMS) else "" for i in range(len(items))]
            return DeviceReading(
                timestamp=timestamp, device_id=device["slave_id"], slave_id=device["slave_id"],
                device_type=device.get("type", ""), function=function, address=int(device.get("address", 0)),
                channels=list(zip(names, items)), quality=QUALITY_GOOD, raw_response=raw_response, units=units,
                registers=list(registers))
        return DeviceReading(
            timestamp=timestamp,
            device_id=device["slave_id"],
            slave_id=device["slave_id"],
            device_type=device.get("type", ""),
            function=function,
            address=int(device.get("address", 0)),
            channels=[(f"{prefix}{index + 1}", value) for index, value in enumerate(items)],
            quality=QUALITY_GOOD,
            raw_response=raw_response,
        )
    if function in (1, 2):
        items = [int(bool(bit)) for bit in list(getattr(response, "bits", None) or [])[:count]]
    else:
        items = [int(reg) for reg in list(getattr(response, "registers", None) or [])[:count]]
    if len(items) < count:
        raise ValueError(f"expected {count} values, received {len(items)}")
    if fmt == "int16":
        items = [value - 0x10000 if value >= 0x8000 else value for value in items]
    return DeviceReading(
        timestamp=timestamp,
        device_id=device["slave_id"],
        slave_id=device["slave_id"],
        device_type=device.get("type", ""),
        function=function,
        address=int(device.get("address", 0)),
        channels=[(f"{prefix}{index + 1}", value) for index, value in enumerate(items)],
        quality=QUALITY_GOOD,
        raw_response=raw_response,
    )


# ---------------------------------------------------------------------- #
# Read / write function codes offered in the Live tab (Modbus-tool style)
# ---------------------------------------------------------------------- #
READ_FUNCTIONS = {
    1: "01 - READ COILS",
    2: "02 - READ DISCRETE INPUTS",
    3: "03 - READ HOLDING REGISTERS",
    4: "04 - READ INPUT REGISTERS",
}
WRITE_FUNCTIONS = {
    5: "05 - WRITE SINGLE COIL",
    6: "06 - WRITE SINGLE REGISTER",
    15: "15 - WRITE MULTIPLE COILS",
    16: "16 - WRITE MULTIPLE REGISTERS",
}
ALL_FUNCTIONS = {**READ_FUNCTIONS, **WRITE_FUNCTIONS}
MAX_WRITE_POINTS = 64   # tiles shown on a write device card


def is_write_function(function):
    return int(function) in WRITE_FUNCTIONS


WRITE_DATA_TYPES = ("UInt16", "Int16", "Hex16", "UInt32", "Float32")
MAX_READ_BITS = 2000
MAX_READ_REGS = 125


def max_count(function):
    """Largest quantity allowed in one read request."""
    if int(function) in WRITE_FUNCTIONS:
        return MAX_WRITE_POINTS
    return MAX_READ_BITS if int(function) in (1, 2) else MAX_READ_REGS


def _split(text):
    return [part for part in str(text).replace(";", ",").replace("\n", ",").replace(" ", ",").split(",") if part]


def _to_bit(token):
    low = token.strip().lower()
    if low in ("1", "on", "true", "t", "high"):
        return True
    if low in ("0", "off", "false", "f", "low"):
        return False
    raise ValueError(f"'{token}' is not a valid coil value (use ON/OFF or 1/0)")


def _to_int(token, base_hint=10):
    low = token.strip().lower()
    try:
        if low.startswith("0x"):
            return int(low, 16)
        return int(low, base_hint)
    except ValueError:
        raise ValueError(f"'{token}' is not a valid number") from None


def parse_write_values(function, text, data_type="UInt16"):
    """Parse the Write box. Returns a list of bools (FC05/15) or of 16-bit
    register values (FC06/16). Raises ValueError with a readable message."""
    function = int(function)
    tokens = _split(text)
    if not tokens:
        raise ValueError("Enter a value to write")
    if function == 5:
        if len(tokens) != 1:
            raise ValueError("FC05 writes exactly one coil (ON / OFF)")
        return [_to_bit(tokens[0])]
    if function == 15:
        if len(tokens) > 1968:
            raise ValueError("FC15 writes at most 1968 coils")
        return [_to_bit(token) for token in tokens]
    if function not in (6, 16):
        raise ValueError(f"Function {function} is not a write function")
    if function == 6 and len(tokens) != 1:
        raise ValueError("FC06 writes exactly one register")
    regs = []
    for token in tokens:
        if data_type == "Float32":
            try:
                regs.extend(struct.unpack(">HH", struct.pack(">f", float(token))))
            except (ValueError, OverflowError):
                raise ValueError(f"'{token}' is not a valid float") from None
        elif data_type == "UInt32":
            value = _to_int(token)
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{token} is outside 0 .. 4294967295")
            regs.extend((value >> 16, value & 0xFFFF))
        elif data_type == "Int16":
            value = _to_int(token)
            if not -32768 <= value <= 32767:
                raise ValueError(f"{token} is outside -32768 .. 32767")
            regs.append(value & 0xFFFF)
        elif data_type == "Hex16":
            value = _to_int(token if token.lower().startswith("0x") else "0x" + token)
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"{token} is outside 0x0000 .. 0xFFFF")
            regs.append(value)
        else:
            value = _to_int(token)
            if not 0 <= value <= 65535:
                raise ValueError(f"{token} is outside 0 .. 65535")
            regs.append(value)
    if function == 6 and len(regs) != 1:
        raise ValueError("FC06 writes one 16-bit register; use FC16 for 32-bit / float values")
    if len(regs) > 123:
        raise ValueError("FC16 writes at most 123 registers")
    return regs