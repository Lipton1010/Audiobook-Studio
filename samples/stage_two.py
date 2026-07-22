import sys, os, re, json

if len(sys.argv) < 2:
    print("Usage: python stage_two.py <glm_output.md>")
    sys.exit(1)

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    raw = f.read()

lines = [ln.rstrip() for ln in raw.splitlines()]

def is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2

def is_heading(ln):
    s = ln.strip().strip("*").strip()
    if len(s) < 2 or len(s) > 60:
        return False
    if s[-1] in ".?!:,;":
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters)

def is_dialogue(ln):
    s = ln.strip().strip("*").strip()
    m = re.match(r"^([A-Z][a-zA-Z]+)(\s[A-Z][a-zA-Z]+)?:\s+\S", s)
    return bool(m)

def is_number_heavy_list(ln):
    s = ln.strip()
    if not (s.startswith("-") or s.startswith("•")):
        return False
    s = s.lstrip("-•").strip()
    # strip a short leading label like "Ogre A:" so it doesn't count as a word
    s = re.sub(r"^[A-Za-z][A-Za-z0-9 ]{0,15}:\s*", "", s)
    tokens = s.split()
    if not tokens:
        return False
    numeric = sum(1 for t in tokens if re.fullmatch(r"\d+|dead", t.strip(".,;")))
    return numeric >= max(1, len(tokens) // 2)

blocks = []
i = 0
n = len(lines)
while i < n:
    ln = lines[i]
    if not ln.strip():
        i += 1
        continue
    stripped = ln.strip()
    if stripped.isdigit() and len(stripped) <= 4:
        i += 1
        continue
    if is_table_row(ln):
        while i < n and (is_table_row(lines[i]) or not lines[i].strip()):
            if not lines[i].strip():
                if i + 1 < n and is_table_row(lines[i + 1]):
                    i += 1
                    continue
                else:
                    break
            i += 1
        blocks.append({"type": "table", "text": "A reference table is omitted here."})
        continue
    if is_number_heavy_list(ln):
        while i < n and (is_number_heavy_list(lines[i]) or not lines[i].strip()):
            if not lines[i].strip():
                if i + 1 < n and is_number_heavy_list(lines[i + 1]):
                    i += 1
                    continue
                else:
                    break
            i += 1
        blocks.append({"type": "omitted_data", "text": "A data list is omitted here."})
        continue
    if is_heading(ln):
        blocks.append({"type": "heading", "text": ln.strip().strip("*").strip()})
        i += 1
        continue
    if is_dialogue(ln):
        blocks.append({"type": "dialogue", "text": ln.strip().strip("*").strip()})
        i += 1
        continue
    blocks.append({"type": "body", "text": ln.strip()})
    i += 1

out_path = os.path.splitext(path)[0] + ".tagged.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"blocks": blocks}, f, ensure_ascii=False, indent=2)

print("===== TAGGED BLOCKS =====")
for b in blocks:
    label = b["type"].upper().ljust(12)
    preview = b["text"][:76] + ("..." if len(b["text"]) > 76 else "")
    print(f"{label}| {preview}")
print("===== END =====")
print("Saved to", out_path)