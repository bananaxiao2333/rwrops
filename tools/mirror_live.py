import json, os, sys, urllib.request, concurrent.futures as cf

SITE = sys.argv[1]; OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)

def get(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())

for name in ("result.json", "metadata.yaml", "index.html"):
    try:
        get(f"{SITE}/{name}", f"{OUT}/{name}")
        print(f"  {name}: {os.path.getsize(f'{OUT}/{name}'):,} B")
    except Exception as e:
        print(f"  {name}: 跳过 ({e})")

idx = json.load(open(f"{OUT}/assets/_index.json")) if os.path.exists(f"{OUT}/assets/_index.json") else None
if idx is None:
    get(f"{SITE}/assets/_index.json", f"{OUT}/assets/_index.json")
    idx = json.load(open(f"{OUT}/assets/_index.json"))

files = sorted(set(idx.values()))
print(f"  资源 {len(files)} 个，开始镜像…")

def one(fn):
    try:
        get(f"{SITE}/assets/{fn}", f"{OUT}/assets/{fn}")
        return 0
    except Exception:
        return 1

done = 0; total = 0
with cf.ThreadPoolExecutor(16) as ex:
    for i, rc in enumerate(ex.map(one, files), 1):
        done += rc; total += 1
        if i % 200 == 0: print(f"    {i}/{len(files)}")
print(f"  完成 {total-done}/{total}，失败 {done}")
sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
print(f"  总计 {sz/1e6:.1f} MB")
