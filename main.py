# ==============================================================
# Clevo W940 Smart Battery Emulator για Raspberry Pi Pico
# ==============================================================
# ΑΠΑΙΤΕΙΤΑΙ: Βάλε το αρχείο i2c_responder.py στο Pico πριν τρέξεις.
# Κατέβασε από: https://github.com/Sandbo00/i2c-responder
# ==============================================================

import machine
import time
from i2c_responder import I2CResponder

# ==============================================================
# ΡΥΘΜΙΣΕΙΣ HARDWARE
# ==============================================================

BATTERY_ADC_PIN = 26   # GP26 (ADC0) — σύνδεση κόμβου διαιρέτη τάσης
I2C_SDA_PIN     = 0    # GP0 (Pin 1) — D (Data) του κονέκτορα laptop
I2C_SCL_PIN     = 1    # GP1 (Pin 2) — C (Clock) του κονέκτορα laptop
SBS_ADDRESS     = 0x0B # Σταθερή I2C διεύθυνση Smart Battery (SBS spec)

# ==============================================================
# ΧΑΡΑΚΤΗΡΙΣΤΙΚΑ ΜΠΑΤΑΡΙΑΣ — Clevo W940 (3S Li-ion)
# Άλλαξε το CELL_CAPACITY_MAH βάσει των κελιών σου (π.χ. 2600 για Samsung 26F)
# ==============================================================

CELL_CAPACITY_MAH   = 2600   # mAh ανά κελί 18650 (3 κελιά σε σειρά)
DESIGN_CAPACITY_MAH = CELL_CAPACITY_MAH
DESIGN_VOLTAGE_MV   = 11100  # mV (3 κελιά × 3.7V nominal)
FULL_CHARGE_MAH     = int(DESIGN_CAPACITY_MAH * 0.98)  # 2% degradation
CYCLE_COUNT         = 8      # Εμφανίζουμε σχεδόν καινούργια μπαταρία
SERIAL_NUMBER       = 0x0057

# ManufactureDate: encoded ως (year-1980)<<9 | month<<5 | day
MANUFACTURE_DATE = ((2024 - 1980) << 9) | (3 << 5) | 10  # 2024-03-10

MANUFACTURER_NAME = "Clevo"
DEVICE_NAME       = "W940BAT-3"
DEVICE_CHEMISTRY  = "LION"

# ==============================================================
# ΑΝΑΓΝΩΣΗ ΤΑΣΗΣ ΑΠΟ ADC (Διαιρέτης R1=100kΩ, R2=33kΩ)
# ==============================================================

battery_adc = machine.ADC(BATTERY_ADC_PIN)

def get_voltage_mv():
    """Διαβάζει την πραγματική τάση της μπαταρίας σε mV.
    Χρησιμοποιεί μέσο όρο 16 δειγμάτων για μείωση θορύβου ADC."""
    raw = sum(battery_adc.read_u16() for _ in range(16)) // 16
    pin_voltage = (raw / 65535.0) * 3.3
    # V_in = V_out × (R1 + R2) / R2 = V_out × 133/33 = V_out × 4.0303
    return int(pin_voltage * 4.0303 * 1000)

# ==============================================================
# ΥΠΟΛΟΓΙΣΜΟΣ SOC (State of Charge)
# Κομματιαστή γραμμική προσέγγιση καμπύλης Li-ion 3S
# ==============================================================

# Ζεύγη (τάση_mV, SOC%) — βαθμονομημένα για Li-ion 3S (9.0V–12.6V)
_SOC_CURVE = [
    (12600, 100), (12420, 90), (12180, 80), (11940, 70),
    (11700, 60),  (11520, 50), (11340, 40), (11100, 30),
    (10800, 20),  (10200, 10), (9900,  5),  (9000,  0),
]

def get_soc(voltage_mv):
    """Μετατρέπει τάση σε SOC% χρησιμοποιώντας κομματιαστή γραμμική παρεμβολή."""
    if voltage_mv >= _SOC_CURVE[0][0]:
        return 100
    if voltage_mv <= _SOC_CURVE[-1][0]:
        return 0
    for i in range(len(_SOC_CURVE) - 1):
        v_high, s_high = _SOC_CURVE[i]
        v_low,  s_low  = _SOC_CURVE[i + 1]
        if voltage_mv >= v_low:
            ratio = (voltage_mv - v_low) / (v_high - v_low)
            return int(s_low + ratio * (s_high - s_low))
    return 0

# ==============================================================
# ΒΟΗΘΗΤΙΚΕΣ ΣΥΝΑΡΤΗΣΕΙΣ — Κωδικοποίηση SBS/SMBus
# ==============================================================

def _word(value):
    """16-bit unsigned → [low_byte, high_byte] (little-endian)."""
    v = int(value) & 0xFFFF
    return [v & 0xFF, (v >> 8) & 0xFF]

def _signed_word(value):
    """16-bit signed → [low_byte, high_byte].
    Αρνητικές τιμές κωδικοποιούνται ως two's complement."""
    if value < 0:
        value += 65536
    return _word(value)

def _block_string(s):
    """SMBus block string → [length_byte, char1, char2, ...]."""
    encoded = s.encode('ascii')
    return [len(encoded)] + list(encoded)

# ==============================================================
# ΚΕΝΤΡΙΚΗ ΛΟΓΙΚΗ: ΑΝΤΙΣΤΟΙΧΙΣΗ REGISTERS → ΤΙΜΕΣ
# ==============================================================

def build_response(register):
    """Χτίζει την απάντηση για κάθε SBS register.
    Επιστρέφει λίστα bytes που στέλνονται στο laptop."""

    v_mv   = get_voltage_mv()
    soc    = get_soc(v_mv)
    remain = int(FULL_CHARGE_MAH * soc / 100)
    # Εκτιμώμενο ρεύμα εκφόρτισης (~20W σε 11V ≈ 1800mA)
    discharge_current_ma = 1800

    tte_min = int(remain * 60 / discharge_current_ma) if discharge_current_ma > 0 else 65535
    tte_min = min(tte_min, 65535)

    # --- Word registers (2 bytes) ---

    if   register == 0x01:  # ManufacturerAccess
        return _word(0x0000)

    elif register == 0x02:  # RemainingCapacityAlarm (mAh) — προειδοποίηση στο 10%
        return _word(int(DESIGN_CAPACITY_MAH * 0.10))

    elif register == 0x03:  # RemainingTimeAlarm (minutes)
        return _word(10)

    elif register == 0x04:  # BatteryMode
        # Bit 15=0: CAPACITY_MODE=mAh, Bit 13=1: PRIMARY_BATTERY, Bit 14=1: INTERNAL_CHARGE_CONTROLLER
        return _word(0x6000)

    elif register == 0x05:  # AtRate (mA)
        return _signed_word(0)

    elif register == 0x06:  # AtRateTimeToFull
        return _word(65535)

    elif register == 0x07:  # AtRateTimeToEmpty
        return _word(tte_min)

    elif register == 0x08:  # AtRateOK
        return _word(1)

    elif register == 0x09:  # Voltage (mV) — η πραγματική τάση!
        return _word(v_mv)

    elif register == 0x0A:  # Current (mA, signed) — αρνητικό = εκφόρτιση
        return _signed_word(-discharge_current_ma)

    elif register == 0x0B:  # AverageCurrent (mA, signed)
        return _signed_word(-discharge_current_ma)

    elif register == 0x0C:  # MaxError (%)
        return _word(1)

    elif register == 0x0D:  # RelativeStateOfCharge (%) — το ποσοστό φόρτισης!
        return _word(soc)

    elif register == 0x0E:  # AbsoluteStateOfCharge (%)
        return _word(soc)

    elif register == 0x0F:  # RemainingCapacity (mAh)
        return _word(remain)

    elif register == 0x10:  # FullChargeCapacity (mAh)
        return _word(FULL_CHARGE_MAH)

    elif register == 0x11:  # RunTimeToEmpty (minutes)
        return _word(tte_min)

    elif register == 0x12:  # AverageTimeToEmpty (minutes)
        return _word(tte_min)

    elif register == 0x13:  # AverageTimeToFull — N/A όταν εκφορτίζουμε
        return _word(65535)

    elif register == 0x14:  # ChargingCurrent — 0 = δεν φορτίζουμε τώρα
        return _word(0)

    elif register == 0x15:  # ChargingVoltage — 0 = δεν φορτίζουμε τώρα
        return _word(0)

    elif register == 0x16:  # BatteryStatus
        # Bit 7 (0x80): INITIALIZED — η μπαταρία είναι βαθμονομημένη
        # Bit 6 (0x40): DISCHARGING — εκφορτίζουμε αυτή τη στιγμή
        return _word(0x00C0)

    elif register == 0x17:  # CycleCount
        return _word(CYCLE_COUNT)

    elif register == 0x18:  # DesignCapacity (mAh)
        return _word(DESIGN_CAPACITY_MAH)

    elif register == 0x19:  # DesignVoltage (mV)
        return _word(DESIGN_VOLTAGE_MV)

    elif register == 0x1A:  # SpecificationInfo (SBS v1.1, revision 1)
        return _word(0x0031)

    elif register == 0x1B:  # ManufactureDate
        return _word(MANUFACTURE_DATE)

    elif register == 0x1C:  # SerialNumber
        return _word(SERIAL_NUMBER)

    # --- Block/String registers ---

    elif register == 0x20:  # ManufacturerName
        return _block_string(MANUFACTURER_NAME)

    elif register == 0x21:  # DeviceName
        return _block_string(DEVICE_NAME)

    elif register == 0x22:  # DeviceChemistry
        return _block_string(DEVICE_CHEMISTRY)

    elif register == 0x23:  # ManufacturerData
        return [2, 0x00, 0x00]

    # Άγνωστο register — απαντάμε με 0xFFFF
    return _word(0xFFFF)

# ==============================================================
# ΚΥΡΙΑ ΛΟΥΠΑ
# ==============================================================

print("=" * 40)
print("Clevo W940 Smart Battery Emulator")
print(f"SBS Address : 0x{SBS_ADDRESS:02X}")
print(f"Design Cap  : {DESIGN_CAPACITY_MAH} mAh")
print(f"Design Volt : {DESIGN_VOLTAGE_MV} mV")
print("=" * 40)

# Αρχικοποίηση I2C Slave
i2c_slave = I2CResponder(
    i2c_id=0,
    sda_gpio=I2C_SDA_PIN,
    scl_gpio=I2C_SCL_PIN,
    responder_address=SBS_ADDRESS
)

current_register = 0x00
last_debug_ms    = time.ticks_ms()
DEBUG_INTERVAL   = 5000  # ms

while True:
    # --- Βήμα 1: Το laptop έγραψε τον register που θέλει να διαβάσει ---
    if i2c_slave.write_data_is_available():
        data = i2c_slave.get_write_data(max_size=2)
        if data:
            current_register = data[0]

    # --- Βήμα 2: Το laptop ζητάει ανάγνωση — απαντάμε ---
    if i2c_slave.read_is_pending():
        response = build_response(current_register)
        i2c_slave.put_read_data(response)

    # --- Debug: εκτύπωση κάθε 5 δευτερόλεπτα ---
    now = time.ticks_ms()
    if time.ticks_diff(now, last_debug_ms) >= DEBUG_INTERVAL:
        v = get_voltage_mv()
        s = get_soc(v)
        r = int(FULL_CHARGE_MAH * s / 100)
        print(f"Τάση: {v}mV | SOC: {s}% | Remaining: {r}mAh | Last reg: 0x{current_register:02X}")
        last_debug_ms = now
