import json
import ast

LOG_FILE = "render_logs.txt"
OUT_FILE = "recovered_records.json"

records = {}

with open(LOG_FILE, "r", errors="ignore") as f:
    for line in f:
        if "autosave" not in line:
            continue
        if "payload=" not in line:
            continue

        try:
            # Split at payload=
            before, after = line.split("payload=", 1)

            # Extract key=
            key_part = before.split("key=", 1)[1].strip()
            key = key_part.split()[0].strip()

            # Extract the { ... }
            payload_text = after.strip()

            # Cut everything after the ending brace
            start = payload_text.find("{")
            end = payload_text.rfind("}")
            payload_text = payload_text[start:end + 1]

            # Convert Python dict → real dict
            payload = ast.literal_eval(payload_text)

            # Clean key using username if present
            if payload.get("username"):
                key = payload["username"].strip()

            # Save last version
            records[key] = payload

        except Exception as e:
            print("FAILED:", line)
            print(e)
            continue

# Save output
with open(OUT_FILE, "w") as f:
    json.dump(records, f, indent=2)

print("Recovered", len(records), "records.")
print("Saved to", OUT_FILE)