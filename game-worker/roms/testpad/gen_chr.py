"""Generate 254 deterministic 'noise' tiles (2 bitplanes each) for TestPad's background."""
import random
from pathlib import Path

rng = random.Random(1985)
data = bytearray()
for tile in range(254):
    density = 0.25 + 0.5 * (tile % 7) / 6
    for plane in range(2):
        for row in range(8):
            data.append(sum((rng.random() < density) << b for b in range(8)))
Path(__file__).with_name("noise.chr").write_bytes(bytes(data))
print(len(data), "bytes")
