
from pathlib import Path
import pandas as pd


def read_data(path: str) -> dict:
    file = Path(path)

    if not file.exists():
        raise FileNotFoundError(path)

    if file.suffix.lower() == ".csv":
        sheets = {"data": pd.read_csv(file)}
    elif file.suffix.lower() in {".xlsx", ".xls"}:
        sheets = pd.read_excel(file, sheet_name=None)
    else:
        raise ValueError("Supported files: CSV, XLSX, XLS")

    result = {}

    for name, df in sheets.items():
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        result[name] = {
            "data": df,
            "profile": {
                "rows": len(df),
                "columns": list(df.columns),
                "missing": df.isna().sum().to_dict(),
                "duplicates": int(df.duplicated().sum()),
                "numeric_summary": (
                    df.select_dtypes(include="number")
                    .describe()
                    .round(3)
                    .to_dict()
                ),
            },
        }

    return result
