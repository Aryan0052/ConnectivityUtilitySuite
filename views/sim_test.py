"""Simulated RS-485 bus test for the Mini SCADA scanner (offscreen Qt)."""
import os, sys, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "/home/claude/app")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop, QElapsedTimer
import multi_device_view as mdv

OFFLINE = {3}
EXCEPTION = {5}

class Resp:
    def __init__(self, fc, count, err=False):
        self.function_code = fc | (0x80 if err else 0)
        self._err = err
        self.bits = ([True, False, True, True, False, False, False, False] * 4)[:((count + 7) // 8) * 8]
        self.registers = [1234] * count
    def isError(self): return self._err
    def encode(self): return bytes([2]) if self._err else bytes([1, 0x0D])

class FakeBus:
    instances = []
    def __init__(self, **kw):
        # pymodbus 3.15.0 reads the RX wait from comm_params.timeout_connect
        self.comm_params = type("CommParams", (), {})()
        self.comm_params.timeout_connect = kw.get("timeout", 1)
        self.busy = threading.Lock()
        self.violations = 0
        self.log = []          # (start, end, slave, ok)
        self.closed = False
        self.socket = None
        FakeBus.instances.append(self)
    def connect(self): return True
    def close(self): self.closed = True
    def _do(self, fc, address, count, device_id):
        if not self.busy.acquire(blocking=False):
            self.violations += 1
            raise RuntimeError("BUS COLLISION")
        start = time.monotonic()
        try:
            if self.closed: raise ConnectionError("port closed")
            if device_id in OFFLINE:
                time.sleep(self.comm_params.timeout_connect)
                self.log.append((start, time.monotonic(), device_id, False))
                raise Exception("Modbus Error: [Input/Output] No response received after 0 retries")
            time.sleep(0.03)
            if device_id in EXCEPTION:
                self.log.append((start, time.monotonic(), device_id, False))
                return Resp(fc, count, err=True)
            self.log.append((start, time.monotonic(), device_id, True))
            return Resp(fc, count)
        finally:
            self.busy.release()
    def read_coils(self, address, count=1, device_id=None): return self._do(1, address, count, device_id)
    def read_discrete_inputs(self, address, count=1, device_id=None): return self._do(2, address, count, device_id)
    def read_holding_registers(self, address, count=1, device_id=None): return self._do(3, address, count, device_id)
    def read_input_registers(self, address, count=1, device_id=None): return self._do(4, address, count, device_id)

mdv.ModbusSerialClient = FakeBus
app = QApplication([])
view = mdv.MultiDeviceView()
view.resize(1600, 900); view.show()
view.com_port.addItem("COM6"); view.com_port.setCurrentText("COM6")

# GUI responsiveness probe
gaps = []; et = QElapsedTimer(); et.start(); last = [0]
def probe():
    now = et.elapsed(); gaps.append(now - last[0]); last[0] = now
p = QTimer(); p.timeout.connect(probe); p.start(10)

def pump(sec):
    loop = QEventLoop(); QTimer.singleShot(int(sec * 1000), loop.quit); loop.exec()

def add(name, sid, typ, poll, scan, timeout, retries):
    view.device_name_input.setText(name); view.slave_input.setValue(sid)
    view.device_type_input.setCurrentText(typ); view.poll_input.setValue(poll)
    view.add_scan_display.setValue(scan); view.add_timeout_display.setValue(timeout); view.add_retry_display.setValue(retries)
    view._manual_add_device()

add("DI-Panel-1", 1, "Digital Input (DI)", 500, 1500, 300, 3)
add("DO-Panel-1", 2, "Digital Output (DO)", 500, 1500, 300, 3)
add("AI-Panel-1", 3, "Analog Input (AI)", 500, 1500, 300, 3)
add("AO-Panel-1", 4, "Analog Output (AO)", 1000, 1500, 300, 3)
add("EXC-Panel", 5, "Analog Output (AO)", 1000, 2000, 300, 1)

results = {}
def check(name, cond, info=""):
    results[name] = bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

view._connect(); bus = FakeBus.instances[-1]
check("connected, devices NOT POLLED before run", all(d["status"] == "NOT_POLLED" for d in view._devices.values()))
view._run_all()
pump(6.0)
dev = view._devices
log = list(bus.log)

check("no simultaneous transactions", bus.violations == 0, f"violations={bus.violations}")
ovl = any(log[i+1][0] < log[i][1] for i in range(len(log)-1))
check("transactions strictly sequential (no overlap)", not ovl)

# Slave 3: initial + 3 retries, then OFFLINE, then recoveries every scan rate
s3 = [e for e in log if e[2] == 3]
check("slave 3 OFFLINE", dev[3]["status"] == "OFFLINE", dev[3]["status"])
term = view.terminal.toPlainText()
check("retry log 1/3..3/3 present", all(f"Retry {i}/3 (Slave 3)" in term for i in (1, 2, 3)))
check("4 attempts before OFFLINE (1 + 3 retries)", "marked OFFLINE after 4 failed attempt(s)" in term)
rec = s3[4:]
gaps_rec = [round((rec[i+1][0] - rec[i][1]) * 1000) for i in range(len(rec) - 1)]
first_gap = round((rec[0][0] - s3[3][1]) * 1000) if rec else None
check("recovery interval ~= Scan Rate 1500 ms", rec and all(1495 <= g <= 1600 for g in [first_gap] + gaps_rec), f"first={first_gap} later={gaps_rec}")
check("terminal shows 'Recovery TX ->'", "Recovery TX ->" in term)

# Healthy devices kept polling at Poll Rate (start to start)
def intervals(sid):
    st = [e[0] for e in log if e[2] == sid]
    return [round((st[i+1] - st[i]) * 1000) for i in range(len(st) - 1)]
for sid, rate in ((1, 500), (2, 500), (4, 1000)):
    iv = intervals(sid)
    check(f"slave {sid} polled at ~{rate} ms while slave 3 failing", iv and min(iv) >= rate - 2 and max(iv) <= rate + 380 and dev[sid]["status"] == "ONLINE",
          f"n={len(iv)+1} min={min(iv)} max={max(iv)} avg={sum(iv)//len(iv)}")

# Exception response -> communication failure -> retry -> OFFLINE
check("exception responses go retry -> OFFLINE (retries=1)", dev[5]["status"] == "OFFLINE" and "Retry 1/1 (Slave 5)" in term and "after 2 failed attempt(s)" in term)
check("exception counted as error + rx", dev[5]["stats"]["errors"] >= 2 and dev[5]["stats"]["rx"] == dev[5]["stats"]["errors"])

# Stats consistency vs bus log
pump(0.5)
log = list(bus.log)
for sid in dev:
    n = len([e for e in log if e[2] == sid])
    st = dev[sid]["stats"]
    ok = st["tx"] in (n, n + 1) and st["successful"] == len([e for e in log if e[2] == sid and e[3]])
    if not ok: print("   ", sid, st, n)
    results.setdefault("per-device tx/success match bus", True)
    results["per-device tx/success match bus"] &= ok
print(("PASS " if results["per-device tx/success match bus"] else "FAIL ") + "per-device tx/success match bus")
tot = {k: sum(d["stats"][k] for d in dev.values()) for k in ("tx","rx","successful","timeouts","retries","errors")}
check("overall stats = sum of device stats", all(view._stats[k] == tot[k] for k in tot), str(tot))
check("timeouts == failed attempts of slave 3", dev[3]["stats"]["timeouts"] == len([e for e in log if e[2] == 3]))
check("retries counted = 3 (slave 3)", dev[3]["stats"]["retries"] == 3)

# Recovery -> ONLINE -> normal polling
OFFLINE.clear()
pump(3.5)
check("slave 3 recovered to ONLINE", dev[3]["status"] == "ONLINE" and dev[3]["retry_count"] == 0)
check("terminal shows recovery message", "Slave 3 recovered. Resuming normal polling." in view.terminal.toPlainText())
t_rec = [e for e in bus.log if e[2] == 3 and e[3]]
# an AI device makes one extra I/P-type read right after it recovers: ignore it
t_rec = [e for i, e in enumerate(t_rec) if i == 0 or e[0] - t_rec[i-1][0] > 0.1]
iv3 = [round((t_rec[i+1][0]-t_rec[i][0])*1000) for i in range(len(t_rec)-1)]
check("slave 3 back on 500 ms normal polling", len(t_rec) >= 3 and all(495 <= x <= 600 for x in iv3), str(iv3))
check("latest_data populated (DI)", dev[1]["latest_data"] and dev[1]["latest_data"][0][0] == "DI1", str(dev[1]["latest_data"]))

# Checkbox survives live updates
view.device_table.item(0, 0).setCheckState(mdv.Qt.Checked)
pump(1.0)
check("table checkbox kept while polling", view.device_table.item(0, 0).checkState() == mdv.Qt.Checked)
view.device_table.item(0, 0).setCheckState(mdv.Qt.Unchecked)

# Stop device 1
view._stop_device(1); pump(0.3); n1 = len([e for e in bus.log if e[2] == 1]); pump(1.5)
check("stopped device not polled", len([e for e in bus.log if e[2] == 1]) == n1 and dev[1]["status"] == "DISABLED")
view._run_device(1); pump(1.0)
check("re-run device polls again", dev[1]["status"] == "ONLINE")

# Clear
cfg_before = {s: (d["name"], d["polling"], d["scan_rate"], d["timeout"], d["max_retries"]) for s, d in dev.items()}
view._clear_terminal_and_statistics()
check("Clear resets stats, keeps devices/config/connection",
      len(dev) == 5 and view._connected and all(v == 0 for k, v in view._stats.items() if k != "last_response")
      and all(all(v == 0 for v in d["stats"].values()) for d in dev.values())
      and cfg_before == {s: (d["name"], d["polling"], d["scan_rate"], d["timeout"], d["max_retries"]) for s, d in dev.items()})
pump(1.0)
check("polling continues after Clear", view._stats["tx"] > 0)

# Disconnect keeps devices
view._disconnect(); pump(1.0)
check("disconnect: port closed, devices kept, NOT POLLED + stopped",
      bus.closed and len(dev) == 5 and all(d["status"] == "NOT_POLLED" and not d["enabled"] for d in dev.values())
      and view.connect_button.isEnabled() and view._scanner is None)
nb = len(bus.log); pump(0.5)
check("no traffic after disconnect", len(bus.log) == nb)

# Reconnect and run again
view._connect(); bus2 = FakeBus.instances[-1]; view._run_all(); pump(1.5)
check("reconnect + Run All polls again", len(bus2.log) > 5 and dev[2]["status"] == "ONLINE" and bus2.violations == 0)

check("GUI responsive (max event-loop gap < 100 ms)", max(gaps[5:]) < 100, f"max gap {max(gaps[5:])} ms")
view._disconnect(); pump(0.6)
print("\n--- terminal sample ---")
print("\n".join(view.terminal.toPlainText().splitlines()[:45]))
print("\nRESULT:", sum(results.values()), "/", len(results), "passed")
view.grab().save("/home/claude/tests/running.png")