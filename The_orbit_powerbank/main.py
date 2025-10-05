import json
import time

#-------------------USER INTERFACE--------------
KEY_WORD="id"
THRESHOLD=20         # % do alertu
BATCH_SIZE=5
SAFE_BATTERY=0.9     # do ilu procent pojemności ładujemy
PREDICT_STEPS = 5
REFRESH=1            # sekundy
MANEUVERS=5
SAFETY_MARGIN=0.1
CHARGING_POWER=1     # jednostki energii / s

#----------------FUNKCJE---------------
def predict_failure(sat):
    energy = sat["energy"]
    distance = sat["distance_to_station"]
    consumption = sat.get("power_consumption", 1)
    km_per_step = sat.get("speed_km_per_sec", 20) * REFRESH
    for step in range(1, PREDICT_STEPS + 1):
        safe_threshold = distance * sat.get("energy_per_km", 0.1) + MANEUVERS + SAFETY_MARGIN * sat["capacity"]
        energy -= km_per_step * sat.get("energy_per_km", 0.1)
        energy -= consumption
        distance -= km_per_step
        if energy <= safe_threshold:
            return True, step
    return False, step + 5

def check_energy(records):
    alerts = []
    for record in records:
        energy_to_dock = record["distance_to_station"] * record.get("energy_per_km", 0.1) + MANEUVERS
        safe_threshold = energy_to_dock + SAFETY_MARGIN * record["capacity"]
        record["priority"] = BATCH_SIZE + 5
        if record["energy"] <= safe_threshold:
            alerts.append((1, record))
            record["status"] = "ALERT"
            record["priority"] = 1
        else:
            result, steps = predict_failure(record)
            if result:
                shortage = steps * REFRESH
                record["status"] = f"energy shortage in approx. {shortage} sec"
                alerts.append((1 + steps, record))
                record["priority"] = steps + 1
    return alerts, records

def generate_alerts(alerts):
    messages = []
    for priority, sat in alerts:
        if sat["status"] != "charged":
            energy_percent = sat['energy'] / sat['capacity'] * 100
            msg = f"ALERT: {sat['id']} energy={energy_percent:.1f}% | status={sat['status']} | distance={sat['distance_to_station']} km"
            messages.append(msg)
    return messages

def docking_operation(sat):
    distance = min(sat.get("speed_km_per_sec", 20) * REFRESH, sat["distance_to_station"])
    sat["distance_to_station"] -= distance
    sat["energy"] -= distance * sat.get("energy_per_km", 0.1)
    sat["status"] = "docking..."
    return sat

def charging(sat):
    # ile energii brakuje do SAFE_BATTERY*capacity
    remaining = SAFE_BATTERY * sat["capacity"] - sat.get("energy", 0)
    charge_step = min(CHARGING_POWER * REFRESH, max(remaining, 0))
    sat["energy"] += charge_step
    sat["status"] = "charging..."
    return sat

#-----------------LOAD DATA--------------------
with open("satellites_static.json") as f:
    static_data = json.load(f)

with open("satellites_dynamic.json") as f:
    live_data = json.load(f)

#--------------------------MAIN--------------------
currently_charging = False
docking = False
id_currently_charging = None
id_docking = None
energy_docked = 0

for i in range(0, len(live_data), BATCH_SIZE):
    batch = live_data[i:i+BATCH_SIZE]
    records = []
    timestamp = None
    for data in batch:
        key = data[KEY_WORD]
        timestamp = data["time"]
        temp = {**static_data[key], **data}
        if "status" not in temp:
            temp["status"] = "charged"
        records.append(temp)

    alerts, records = check_energy(records)
    messages = generate_alerts(alerts)
    print("ALERTS:")
    for msg in messages:
        print(msg)
    print(f"OPERATIONS:{timestamp}")

    sorted_rec = sorted(records, key=lambda x: (x["priority"], x["distance_to_station"]))
    sat = sorted_rec[0]

    if sat["priority"] <= BATCH_SIZE + 2:
        if not currently_charging:
            if not docking:
                docking = True
                id_docking = sat[KEY_WORD]
                sat = docking_operation(sat)
                if sat["distance_to_station"] == 0:
                    docking = False
                    currently_charging = True
                    id_currently_charging = sat[KEY_WORD]
                    sat = charging(sat)
                    energy_docked = sat["energy"]
            else:
                if sat["distance_to_station"] > 0:
                    sat = docking_operation(sat)
                else:
                    currently_charging = True
                    id_currently_charging = sat[KEY_WORD]
                    sat = charging(sat)
                    energy_docked = sat["energy"]
        else:
            if sat["energy"] >= SAFE_BATTERY * sat["capacity"]:
                sat["status"] = "charged"
                currently_charging = False
            else:
                sat["energy"] = energy_docked
                sat = charging(sat)
                energy_docked = sat["energy"]

    sorted_rec[0] = sat

    #------PRINT STATUS WITH PROGRESS BAR------
    for sat in sorted_rec:
        progress = int((sat['energy']/sat['capacity'])*100)
        bar = '#' * progress + '.' * (100 - progress)
        energy_percent = sat['energy'] / sat['capacity'] * 100
        print(f"{sat['id']} [{bar}] {energy_percent:.1f}% | {sat['status']} | distance={sat['distance_to_station']} km")
    print("-"*65 + "\n\n")
    time.sleep(REFRESH)