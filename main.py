import machine
import time

# Ορίζουμε το pin 26 για το διάβασμα της τάσης (μέσω του διαιρέτη)
battery_adc = machine.ADC(26)

# --- ΣΥΝΑΡΤΗΣΕΙΣ ΥΠΟΛΟΓΙΣΜΟΥ ---

def get_voltage_mv():
    """Διαβάζει το pin και υπολογίζει την πραγματική τάση της μπαταρίας"""
    raw_value = battery_adc.read_u16() # Επιστρέφει 0 - 65535
    
    # Μετατροπή της τιμής σε Volt που φτάνουν στο pin (max 3.3V)
    pin_voltage = (raw_value / 65535.0) * 3.3
    
    # Μαθηματικά διαιρέτη τάσης: V_in = V_out * ((R1 + R2) / R2)
    # R1 = 100k, R2 = 33k -> Συντελεστής = 133 / 33 = 4.0303
    real_voltage = pin_voltage * 4.0303
    
    return int(real_voltage * 1000) # Επιστροφή σε mV

def get_soc(voltage_mv):
    """Μετατρέπει την τάση σε ποσοστό % (12.6V = 100%, 9.0V = 0%)"""
    if voltage_mv >= 12600: return 100
    if voltage_mv <= 9000: return 0
    # Υπολογισμός ποσοστού γραμμικά
    return int(((voltage_mv - 9000) / 3600) * 100)


# --- Η ΛΟΓΙΚΗ ΤΟΥ ΕΜULATOR (I2C SLAVE) ---
# Προσοχή: Για να τρέξει κανονικά ως Slave, χρειάζεται μια βιβλιοθήκη i2c_responder.
# Εδώ δείχνουμε τη λογική του πώς απαντάει στο Laptop όταν "ρωτηθεί".

def handle_laptop_request(register_requested):
    """Αυτή η συνάρτηση τρέχει κάθε φορά που το laptop ζητάει δεδομένα"""
    
    current_mv = get_voltage_mv()
    current_soc = get_soc(current_mv)
    
    if register_requested == 0x09:
        # Το laptop ρωτάει: "Τάση;"
        return current_mv
        
    elif register_requested == 0x0D:
        # Το laptop ρωτάει: "Ποσοστό %;"
        return current_soc
        
    elif register_requested == 0x16:
        # Το laptop ρωτάει: "Έχεις Battery Status / Σφάλματα;"
        return 0x0000 # Απαντάμε: "0 σφάλματα, όλα τέλεια!"
        
    elif register_requested == 0x10:
        # Το laptop ρωτάει: "Full Charge Capacity;"
        return 2200 # Του λέμε 2200 mAh
        
    elif register_requested == 0x17:
        # Το laptop ρωτάει: "Κύκλοι Φόρτισης;"
        return 5 # Του λέμε ότι είμαστε καινούργια μπαταρία!
        
    else:
        # Αν ρωτήσει κάτι που δεν ξέρουμε, στέλνουμε μια "άδεια" απάντηση
        return 0xFFFF

# Κύρια Λούπα λειτουργίας
print("Smart Battery Emulator Started...")
while True:
    # Εδώ το πρόγραμμα θα περιμένει αιτήματα I2C
    # και θα καλεί την handle_laptop_request(register)
    
    # Για debugging, τυπώνουμε τι βλέπει το Pico:
    v = get_voltage_mv()
    s = get_soc(v)
    print(f"Πραγματική Τάση: {v}mV | Ποσοστό: {s}%")
    time.sleep(2)