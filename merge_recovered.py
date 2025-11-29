import json

main = json.load(open("presentser_data.json"))
recovered = json.load(open("recovered_records.json"))

for key, rec in recovered.items():
    if key not in main:
        main[key] = rec
    else:
        # merge without overwriting existing values
        for field, val in rec.items():
            if val not in (None, "", []):
                main[key][field] = val

json.dump(main, open("presentser_data.json", "w"), indent=2, ensure_ascii=False)

print("Merge complete!")