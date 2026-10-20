
from llm_client import ask_agent


SYSTEM = """
You are the Nexus Forge Theory Generator.

Generate exactly six distinct, plausible theories answering
the research question.

Each theory must include:
- id: T1 through T6
- title
- mechanism: how the proposed explanation could work
- evidence_needed: what observations would support it
- disconfirming_evidence: what would weaken it
- predictions: observable outcomes if it is true

Use the supplied observations as leads, not as proof.
Do not invent data or claim causation without evidence.

Return JSON:
{
  "theories": [
    {
      "id": "T1",
      "title": "...",
      "mechanism": "...",
      "evidence_needed": [],
      "disconfirming_evidence": [],
      "predictions": []
    }
  ]
}
"""


def generate(question: str, data_analysis: dict) -> dict:
    result = ask_agent(
        SYSTEM,
        {
            "research_question": question,
            "data_analysis": data_analysis,
        },
    )

    theories = result.get("theories", [])

    if len(theories) != 6:
        raise ValueError(
            f"Expected six theories, got {len(theories)}"
        )

    return result
