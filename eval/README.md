# Evaluation

`answer_key.csv` holds the true primary cause (and any contributing cause) for each of the 16 cases in
`data/cases/`. It exists so we can measure how often StockWhy finds the right cause, in normal and noisy data.

Rules:
- Only evaluation code reads this folder. The agent, its tools and its prompts must never read it.
- Run the agent on `data/cases/questions.csv`, then compare its answers here.
