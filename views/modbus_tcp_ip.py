"""Modbus TCP (IP) - third connection type of the Multi Device page.

A device of this type is addressed by its IP address only:
    * no Device ID (slave id) in the Add New Device form - every request carries Unit ID UNIT_ID
    * no subnet mask
    * TCP port is always TCP_PORT
    * many devices may use the same IP address (e.g. the DI, DO and AI parts of one Ethernet I/O module);
      they differ only in function code / start address / length

Everything that is special about this connection type lives in this file. The Multi Device page only
calls the helpers below; on the wire a request is an ordinary Modbus TCP request (MBAP + PDU), so it is
sent by the same Modbus TCP transport as the "Modbus TCP" connection type (modbus_tcp.py, unchanged).

A device made with this type is stored with  link = LINK_KEY  so it only runs while this connection type
is selected (and a "Modbus TCP" device only runs with "Modbus TCP").
"""
import ipaddress

MODE_NAME = "Modbus TCP (IP)"   # text in the Connection Type drop-down
LINK_KEY = "tcp_ip"             # device["link"] of devices made with this connection type
TCP_PORT = 502                  # fixed port
UNIT_ID = 1                     # Unit ID sent in every request (the device has no Device ID)

HINT = ("Modbus TCP (IP): set only the IP address of each device in 'Add New Device'. "
        f"Port {TCP_PORT}, Unit ID {UNIT_ID}. DI, DO, AI ... of one module can share the same IP.")
READY_TEXT = (f"{MODE_NAME} ready. Each device connects to its own IP address (port {TCP_PORT}) when polled. "
              "Add devices (IP address), then press Run All.")


def is_mode(connection_text):
    """True when the Connection Type drop-down shows this connection type."""
    return str(connection_text or "").strip() == MODE_NAME


def is_device(device):
    """True for a device that was made with this connection type."""
    return bool(device) and device.get("link") == LINK_KEY


def check_ip(text):
    """(host, None) for a valid IPv4 address, else (None, reason)."""
    host = str(text or "").strip()
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return None, f"'{host}' is not a valid IPv4 address."
    return host, None


def device_fields(host):
    """The connection fields stored in a device of this type."""
    return {"host": host, "tcp_port": TCP_PORT, "subnet": "", "unit": UNIT_ID, "link": LINK_KEY}


def same_reading(devices, device, skip_key=None):
    """True when another reading device of this type already reads exactly the same thing
    (same IP, function code, start address and length) - that would only be a copy."""
    if device.get("mode") == "write":
        return False
    wanted = (device.get("host"), int(device.get("function") or 0), int(device.get("address") or 0),
              int(device.get("count") or 0))
    for key, other in devices.items():
        if key == skip_key or other.get("mode") == "write" or not is_device(other):
            continue
        if (other.get("host"), int(other.get("function") or 0), int(other.get("address") or 0),
                int(other.get("count") or 0)) == wanted:
            return True
    return False


def default_name(host):
    return f"Device {host}"


def id_text(device):
    """Short address text (device table / terminal)."""
    return str(device.get("host") or "--")


def id_line(device):
    """Address lines of the device card."""
    return f"IP Address   : {device.get('host') or '--'}"