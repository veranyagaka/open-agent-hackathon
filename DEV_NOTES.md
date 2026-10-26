# DEV NOTES — Internal Reference Only

> ⚠️ Do not commit this file or share it publicly. It contains ground truth answer keys that the agent must never see.

---

## Test Cases & Ground Truth

### Normal cases (noise_level = 1.0)

```bash
python run.py --dataset data/cases/normal/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03
# ✅ demand_surge
```

```bash
python run.py --dataset data/cases/normal/case_02 --facility FAC-020 --commodity "magnesium sulphate inj" --month 2026-03
# ✅ supplier_underfill
```

```bash
python run.py --dataset data/cases/normal/case_03 --facility FAC-016 --commodity "oxytocin 10IU inj" --month 2026-03
# ✅ expiry  (also: supplier_underfill)
```

```bash
python run.py --dataset data/cases/normal/case_04 --facility FAC-020 --commodity "zinc 20mg tab" --month 2026-03
# ✅ record_error
```

```bash
python run.py --dataset data/cases/normal/case_05 --facility FAC-030 --commodity "magnesium sulphate inj" --month 2026-03
# ✅ national_disruption
```

```bash
python run.py --dataset data/cases/normal/case_06 --facility FAC-022 --commodity "iron-folate tab" --month 2026-03
# ✅ late_order
```

```bash
python run.py --dataset data/cases/normal/case_07 --facility FAC-001 --commodity "zinc 20mg tab" --month 2026-03
# ✅ late_order  (also: demand_surge)
```

```bash
python run.py --dataset data/cases/normal/case_08 --facility FAC-027 --commodity "iron-folate tab" --month 2026-03
# ✅ payment_arrears
```

---

### Noisy cases (noise_level = 2.5)

```bash
python run.py --dataset data/cases/noisy/case_01 --facility FAC-019 --commodity "iron-folate tab" --month 2026-03
# ✅ late_order
```

```bash
python run.py --dataset data/cases/noisy/case_02 --facility FAC-015 --commodity "iron-folate tab" --month 2026-03
# ✅ payment_arrears
```

```bash
python run.py --dataset data/cases/noisy/case_03 --facility FAC-008 --commodity "iron-folate tab" --month 2026-03
# ✅ record_error
```

```bash
python run.py --dataset data/cases/noisy/case_04 --facility FAC-006 --commodity "zinc 20mg tab" --month 2026-03
# ✅ expiry  (also: supplier_underfill)
```

```bash
python run.py --dataset data/cases/noisy/case_05 --facility FAC-013 --commodity "magnesium sulphate inj" --month 2026-03
# ✅ supplier_underfill
```

```bash
python run.py --dataset data/cases/noisy/case_06 --facility FAC-026 --commodity "amoxicillin dispersible tab" --month 2026-03
# ✅ late_order  (also: demand_surge)
```

```bash
python run.py --dataset data/cases/noisy/case_07 --facility FAC-006 --commodity "zinc 20mg tab" --month 2026-03
# ✅ demand_surge
```

```bash
python run.py --dataset data/cases/noisy/case_08 --facility FAC-027 --commodity "zinc 20mg tab" --month 2026-03
# ✅ national_disruption
```

---

## Cause coverage summary

All 7 hypothesis types are covered across the 16 cases:

| Cause | Normal | Noisy |
|-------|--------|-------|
| demand_surge | case_01 | case_07 |
| supplier_underfill | case_02 | case_05 |
| expiry | case_03 | case_04 |
| record_error | case_04 | case_03 |
| national_disruption | case_05 | case_08 |
| late_order | case_06, case_07 | case_01, case_06 |
| payment_arrears | case_08 | case_02 |

---

## Shorthand (using --case flag)

```bash
python run.py --case data/cases/normal/case_01   # demand_surge
python run.py --case data/cases/normal/case_02   # supplier_underfill
python run.py --case data/cases/normal/case_03   # expiry
python run.py --case data/cases/normal/case_04   # record_error
python run.py --case data/cases/normal/case_05   # national_disruption
python run.py --case data/cases/normal/case_06   # late_order
python run.py --case data/cases/normal/case_07   # late_order + demand_surge
python run.py --case data/cases/normal/case_08   # payment_arrears
```

---

## Useful flags

| Flag | Purpose |
|------|---------|
| `--no-review` | Skip pharmacist approval prompt (CI / batch runs) |
| `--output results/case_XX.json` | Save full JSON output |
| `SAMPLE_MODE=true` | Use `data/sample/` (no dataset arg needed) |

Example batch run without interactive prompts:

```bash
for i in 01 02 03 04 05 06 07 08; do
  python run.py --case data/cases/normal/case_$i --no-review --output results/normal_case_$i.json
done
```
