
from llm_client import ask_agent


SYSTEM = """
You are the Nexus Forge Evidence Investigator.

Evaluate every proposed theory using the supplied data profile,
actual computed test results, and evidence references.

For each theory:
- assess whether evidence supports its predictions
- identify contradictory or missing evidence
- distinguish statistical association from causation
- state what the tests cannot establish
- assign supported, weakened, or inconclusive

Never invent a test result, statistic, row, or citation.
A low p-value alone does not establish causation or importance.

Return JSON:
{
  "evaluations": [
    {
      "theory_id": "T1",
      "verdict": "inconclusive",
      "supporting_evidence_ids": [],
      "contradicting_evidence_ids": [],
      "reasoning": "...",
      "limitations": [],
      "additional_analysis_needed": []
    }
  ],
  "analysis_requests": []
}
"""


def investigate(
    question: str,
    theories: dict,
    data_analysis: dict,
    test_results: list,
) -> dict:
    return ask_agent(
        SYSTEM,
        {
            "research_question": question,
            "theories": theories,
            "data_analysis": data_analysis,
            "computed_test_results": test_results,
        },
    )
