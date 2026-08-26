path = "/home/dhruv/datadna/backend/app/api/datasets.py"

with open(path, "r") as f:
    content = f.read()

marker = "from datetime import datetime, timezone"

if "import json" in content:
    print("ABORT: 'import json' already present in the file — nothing to do.")
else:
    if content.count(marker) != 1:
        print(f"ABORT: expected exactly 1 occurrence of marker line, found {content.count(marker)}. Not touching the file.")
    else:
        new_content = content.replace(marker, "import json\n" + marker, 1)
        with open(path, "w") as f:
            f.write(new_content)
        print("Done: 'import json' inserted successfully.")
