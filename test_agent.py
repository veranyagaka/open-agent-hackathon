from agents.data_analyst import analyze

profile = {
    "Monthly_Summary": {
        "columns": ["month", "forecast_demand_units", "actual_demand_units"],
        "row_count": 2,
        "sample_records": [
            {
                "month": "2026-03",
                "forecast_demand_units": 90,
                "actual_demand_units": 92
            },
            {
                "month": "2026-06",
                "forecast_demand_units": 95,
                "actual_demand_units": 158
            }
        ]
    }
}

question = "Investigate whether stockouts are associated with late orders or demand surges."

result = analyze(profile, question)
print(result)