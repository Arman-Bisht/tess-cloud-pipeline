import pandas as pd
import numpy as np

df = pd.read_csv("master_discoveries.csv")
print(f"Total targets: {len(df)}")

# 1. Variables with peak-to-peak amplitude < 0.001 (1000 ppm)
df['amp_float'] = pd.to_numeric(df['amplitude'], errors='coerce')
low_amp = df[df['amp_float'] < 0.001]
print(f"\n1. Targets with amplitude < 1000 ppm (TESS noise floor / microvariability): {len(low_amp)}")
for _, r in low_amp.head(15).iterrows():
    print(f"   {r['name']}: amp={r['amp_float']*1e6:.1f} ppm, P={r['period']} d, cat={r['category']}")

# 2. Spurious ~19-day periods (18.0 - 19.6 days)
df['p_float'] = pd.to_numeric(df['period'], errors='coerce')
p_19 = df[(df['p_float'] >= 18.0) & (df['p_float'] <= 19.6)]
print(f"\n2. Targets with period ~18-19.6 days (TESS Sector/Gap Window Artifact): {len(p_19)}")
for _, r in p_19.iterrows():
    print(f"   {r['name']}: P={r['p_float']:.3f} d, depth={r['depth']}, cat={r['category']}")

# 3. Artifact dips with depth > 50%
df['d_float'] = pd.to_numeric(df['depth'], errors='coerce')
deep_dips = df[df['d_float'] > 0.50]
print(f"\n3. Targets with depth > 50% (probable edge/stitching divergence): {len(deep_dips)}")
for _, r in deep_dips.iterrows():
    print(f"   {r['name']}: depth={r['d_float']*100:.1f}%, cat={r['category']}")
