"""Several links at the same time on the Multi Device page.

Every device belongs to ONE link (device["link"]):

    "rtu"      Modbus RTU on the COM port of Communication Settings (serial bus)
    "gateway"  Modbus TCP through the gateway IP / port of Communication Settings (Device ID = Unit ID)
    "tcp_ip"   Modbus TCP (IP): the device's own IP address (modbus_tcp_ip.py)

ScannerGroup runs one ModbusScanner per connected link and looks like one scanner to the page: the page calls
add_device / set_enabled / request_write ... as before and the group passes each call to the scanner of the
device's link. So the RS-485 bus keeps its one-transaction-at-a-time behaviour and its frames, and a slow TCP
device can never hold up the serial bus (or the other way round). Every scanner's events reach the page through
the group's own `event` signal.
"""
from PySide6.QtCore import QObject, Signal

LINKS = ("rtu", "gateway", "tcp_ip")
LINK_NAMES = {"rtu": "Modbus RTU", "gateway": "Modbus TCP", "tcp_ip": "Modbus TCP (IP)"}
LINK_SHORT = {"rtu": "RTU", "gateway": "TCP", "tcp_ip": "IP"}
TYPE_TO_LINK = {"Modbus RTU": "rtu", "Modbus TCP": "gateway", "Modbus TCP (IP)": "tcp_ip"}


def link_of(device, default="rtu"):
    """The link a device runs on (devices saved by older versions have no "link": IP devices are recognised
    by their own IP address, the rest gets `default`)."""
    link = (device or {}).get("link")
    if link in LINKS:
        return link
    if (device or {}).get("host"):
        return "tcp_ip"
    return default


class ScannerGroup(QObject):
    event = Signal(object)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanners = {}            # link -> ModbusScanner
        self._key_link = {}            # device key (slave_id) -> link
        self._finished = set()

    # ------------------------------------------------------------ links
    def add_link(self, link, scanner):
        self._scanners[link] = scanner
        scanner.event.connect(self._relay)
        scanner.finished.connect(self._child_finished)

    def links(self):
        return set(self._scanners)

    def has_link(self, link):
        return link in self._scanners

    def scanner(self, link):
        return self._scanners.get(link)

    def _relay(self, event):
        self.event.emit(event)

    def _child_finished(self):
        self._finished.add(self.sender())
        if all(not s.isRunning() for s in self._scanners.values()):
            self.finished.emit()

    # ------------------------------------------------------------ same calls as ModbusScanner
    def _for_key(self, key):
        return self._scanners.get(self._key_link.get(key))

    def add_device(self, device):
        link = link_of(device)
        scanner = self._scanners.get(link)
        if scanner is None:
            return False                              # that link is not connected
        self._key_link[device["slave_id"]] = link
        scanner.add_device(device)
        return True

    def remove_device(self, key):
        link = self._key_link.pop(key, None)
        scanner = self._scanners.get(link)
        if scanner is not None:
            scanner.remove_device(key)

    def update_device(self, key, device):
        old = self._key_link.get(key)
        new = link_of(device)
        if old == new and self._scanners.get(new) is not None:
            self._key_link.pop(key, None)
            self._key_link[device["slave_id"]] = new
            self._scanners[new].update_device(key, device)
            return
        self.remove_device(key)                       # the device moved to another link
        self.add_device(device)

    def set_enabled(self, key, enabled):
        scanner = self._for_key(key)
        if scanner is not None:
            scanner.set_enabled(key, enabled)

    def poll_now(self, key):
        scanner = self._for_key(key)
        if scanner is not None:
            scanner.poll_now(key)

    def request_write(self, request):
        scanner = self._scanners.get(request.get("link")) or self._for_key(request.get("slave_id"))
        if scanner is None:
            return False
        scanner.request_write(request)
        return True

    def set_cycle_polling(self, *args, **kwargs):
        for scanner in self._scanners.values():
            scanner.set_cycle_polling(*args, **kwargs)

    def add_reading_sink(self, sink):
        for scanner in self._scanners.values():
            scanner.add_reading_sink(sink)

    # ------------------------------------------------------------ thread control
    def start(self):
        for scanner in self._scanners.values():
            scanner.start()

    def request_stop(self):
        for scanner in self._scanners.values():
            scanner.request_stop()

    def isRunning(self):
        return any(scanner.isRunning() for scanner in self._scanners.values())

    def wait(self, ms):
        for scanner in self._scanners.values():
            scanner.wait(ms)

    def deleteLater(self):
        for scanner in self._scanners.values():
            scanner.deleteLater()
        super().deleteLater()
