# Rules, rubric, submission, deadlines

All quotes are from the official event page unless marked otherwise:
https://hackathon.genai.works/event/open-agent-hackathon-2026 (accessed 2026-10-23, read without login; the
collapsed rule sections were read from the page's embedded data, which is the same text the "Expand all" button shows).

> **Logged-in pass done 2026-10-23.** HackOS documents (Resources tab) and announcements were read with Claude in
> Chrome. Their findings are in the section "HackOS requirements" below. Where HackOS and the event page disagree,
> both are quoted. HackOS's own Official Rules copy says: "Draft status. The binding Official Rules are published on
> the event page".

## HackOS requirements (logged-in pass)

Source paths are HackOS Resources document titles (https://hackathon.genai.works/resources) unless marked otherwise.

**Mandatory technology (Disqualification Checklist):**
| Requirement | Rule (exact) |
|---|---|
| Zetaris | "Must be your project's data layer." |
| Meterless | "At least one Meterless Engine (H-MEM, Markovian, World Model or Scout Intent) working in a feature, and Meterless Nightshift as your primary AI provider." |
| Required components | "Demo video (1–4 minutes), slide deck, public GitHub repository with README, sponsor technology explanation." |
| Pre-existing work | "Work committed before 22 October, 00:00 UTC is not eligible unless declared in the submission form." |
| One track | "Each submission selects exactly one primary track." |

- Event Calendar and Hackathon Overview: "The project must use Zetaris as its data layer, implement at least one
  Meterless Engine in a working feature, use Meterless Nightshift as its primary AI provider, and use NVIDIA
  technology wherever it contributes. Cursor is optional."
- Participant Setup Guide (last updated 21 Oct): "Zetaris and Meterless must be running on your machine to be
  eligible for this hackathon." "For this hackathon, everyone runs Zetaris locally in Docker."
- Setup Guide, Build: "A working integration is required. Simply mentioning an engine in your submission, copying a
  prompt or adding an unused dependency does not satisfy the Build rule." And: the "POWER → Add Meterless as a
  provider prompt ... On its own, it doesn't meet the Build requirement to implement at least one Meterless Engine."
- Setup Guide, Power: "The Power rule: your app must support Meterless Nightshift as a primary AI provider."
  "Meterless is a working primary AI provider in your app, not just a dependency in your README."
- HackOS Official Rules (draft) §16 disqualification list includes "Does not integrate Zetaris, at least one
  Meterless Engine and Meterless Nightshift", "Includes undeclared pre-existing work" and "Shows no evidence of how
  the agent reached its output". §18 asks for disclaimers on medical use cases and human review.

**Cursor conflict (unresolved, see OPEN_QUESTIONS.md):**
- Event page Rule 5: "teams must use Cursor for development."
- HackOS FAQ: "Do I have to use Cursor? No. Cursor is optional and recommended."
- Announcement (HackOS Messages > Announcement, 22 Oct, Isreal Hosana): "1. Cursor is now optional" and "2. No free
  Cursor credits are included with this event".
- The HackOS "Help Cursor" channel description still says "Cursor is the required development environment for every
  submission". The onboarding deck (21 Oct) also labels Cursor "REQUIRED".

**Submission form (Submission Form Preview; Submission Requirements):** project name and description, track, team
members (full name, HackOS email, GitHub username, role, primary contact), public GitHub URL, demo video 1–4 min,
slide deck ("covering all eight points"), sponsor technology explanation (Zetaris, Meterless, Cursor, NVIDIA, what
was unique), pre-existing components, Colab links. "Data prepared before the build window must be declared as a
pre-existing component." "Your team locks at first submission" (onboarding deck).

**What judges must be able to run (Disqualification Checklist):** "Repository is **public** by the deadline";
"`.env.example` exists, placeholders only"; "Sample inputs and matching outputs are included"; "`logs/` exists or is
created at runtime"; "There's a programmatic way in, not just a UI"; "It needs no interactive input"; "`SAMPLE_MODE=true`
runs the whole thing without Zetaris, Nightshift or live credentials"; "It still runs real agent logic on cached data,
rather than replaying a saved output"; "Output isn't read from `output_examples/`"; "No local GPU required; NVIDIA
models are reached through Nightshift's hosted endpoints". Submission Requirements: "At least three sample inputs and
their outputs".

**metadata.json:** each sponsor overview says "Say where ... sits in your build in your README and `metadata.json`".
No template or schema was found in any HackOS document, and the submission form preview has no metadata field
(see metadata.template.json).

## Key dates (all UTC)

| Event | Exact wording / time |
|---|---|
| Registration opens | Aug 14, 2026, 00:00 UTC |
| Build window opens | Oct 22, 2026, 00:00 UTC |
| Judging opens | Oct 27, 2026, 00:00 UTC |
| Registration closes | Oct 27, 2026, 23:45 UTC, "Hard deadline" |
| Submissions close | Oct 27, 2026, 23:45 UTC, "Hard deadline" |
| Results announced | Nov 6, 2026, 16:00 UTC |

Rule 4: "Building starts 22 October 2026 at 00:00 UTC and ends 27 October 2026 at 23:45 UTC." /
"Work committed before the window opens is not eligible, except for clearly declared pre-existing components." /
"Time zones do not extend the window; all deadlines are UTC."

Nairobi equivalent of the deadline: **28 Oct 2026, 02:45 EAT** (UTC+3). Note that "Judging opens" (27 Oct 00:00 UTC)
comes *before* the submission deadline. HackOS (Event Calendar, Official Rules draft, onboarding deck) instead says
"**28 October** | Judging opens | Judges | Judging begins immediately after submissions close." HackOS also gives
mid-sprint call 24 Oct 14:00 UTC; see SCHEDULE.md.

**Conflicting source:** the Meterless repo's hackathon guide says "Dates | October 15 to 20, 2026"
(https://github.com/meterless/meterless/blob/main/docs/community/hackathon-guide.md, commit 1742dec). The event page
wins. Treat the Meterless page as stale.

## Tracks (exact)

- Track 01 **Solving Fragmented Intelligence**: "Demonstrate a clever ability to discover and work across fragmented data sources."
- Track 02 **The Agent That Can Explain Why** (our track): "Build agents that investigate complex questions across multiple data sources, connect findings, and produce evidence-backed answers or recommendations."
- Track 03 **Reasoning Architecture**: "Demonstrate a novel ability to turn data, knowledge, memory, and reasoning into reliable decisions and actions."
- Bonus **Wildcard [Tinkerer]: Bring Your Own Project**: "Bring an existing project, prototype or concept and extend it using sponsor technology such as Meterless and Zetaris. Entries are judged on the same criteria as the other tracks, must integrate Zetaris and Meterless, and are scored on the new work rather than prior development."

Rule 3: "Every submission selects exactly one primary track, which determines the judging panel and the prizes it competes for." / "You may change track any time before the submission deadline from your team workspace." / "Cross-track relevance is welcome but is not scored twice."

## Judging rubric (100 points)

Rule 7: "Scoring out of 100: Impact 30, Technical 20, Innovation 15, Demo 15, Product & UX 10, Sponsor tech 10."

| Criterion | Points | Exact description |
|---|---:|---|
| Impact | 30 | "Consistency with the challenge statements: how effectively the solution addresses a meaningful real-world problem for its intended users." |
| Technical | 20 | "How well the solution is built, including its technical implementation, reliability and architecture." |
| Innovation | 15 | "How original or creative the approach to solving the problem is." |
| Demo | 15 | "How clearly the demo shows the solution, its functionality, and the value it provides to its intended users." |
| Product & UX | 10 | "How intuitive, accessible, and easy to use the product is for its intended users." |
| Sponsor tech | 10 | "How effectively the solution uses the sponsors' technology to address the problem and enhance the overall product." |

- "Each submission is reviewed by at least three judges."
- "Ties are resolved on the Impact score, then on submission timestamp." (INFERRED: submitting earlier wins a tie.)

Judges listed: Michael Hay (CTO, Zetaris), Michael Armentano (Head of Technical Partnerships, SpaceXAI), Sam Cummings
(VP of AI Engineering, GenAI Works), Shestakov Vladyslav (Head of Engineering, GenAI Works), Remus Ranca (Education
Operations Lead, GenAI Works).

**Conflicting rubric:** the Meterless hackathon guide lists a different rubric ("Usefulness 30% / Meterless engine
usage 25% / Local-first and privacy design 15% / Quality of demo 15% / Creativity 10% / Documentation 5%"). It does not
match the event page and is probably from an older or Meterless-only event. Use the event page rubric.

## Mandatory technology (Rule 5, "What you can use")

- "Every submission must integrate Zetaris and Meterless, and teams must use Cursor for development."
- "Integrate NVIDIA technology wherever it contributes to your project, workflow or use case."
- "Any language, framework, model or cloud, including closed-source APIs and sponsor credits."
- "Pre-existing open-source libraries are fine. Pre-existing product code must be declared in the submission form."
- "Generated code is allowed and expected, you own the result and are accountable for it."

Bright Data is **not mentioned** anywhere on the event page (see SPONSORS.md).

## Submission requirements (Rule 6, exact)

1. "A demo video of 1-4 minutes that shows the main workflow, how the agent solves the selected challenge, its key features, and how Zetaris and Meterless are integrated."
2. "A slide deck covering the problem and target users, the solution, the agent workflow or architecture, the technical stack, how Zetaris and Meterless were used, what was unique about your use of the sponsor technologies, product visuals, and future enhancements."
3. "A GitHub repository with all source code and a README covering setup, usage and dependencies. If your agents run in Google Colab, include the Colab links."
4. "A clear explanation of how Zetaris and Meterless were integrated, how Cursor was used during development, where NVIDIA technology contributes, and what was unique about your use of the sponsor technologies."

Submission form fields: see "HackOS requirements" above. Character/file limits: **NOT FOUND**.
metadata.json template: **NOT FOUND** in HackOS either (see metadata.template.json).

## Disqualification checklist

The event page has no checklist titled "disqualification". Every rule that can disqualify an entry or make work ineligible:

| Rule | Exact wording | Our check |
|---|---|---|
| 1.3 | "One account per participant. Duplicate accounts disqualify the whole team." | Each member has exactly one account |
| 1.1 | "Open worldwide to anyone aged 16 or older at the start of the build window." | All members 16+ |
| 2 | "A participant may belong to exactly one team." | No one on two teams |
| 2 | "Team composition locks when your first submission is created" | Finalise team before first submission |
| 4 | "Work committed before the window opens is not eligible, except for clearly declared pre-existing components." | **Our repo has 3 commits before the window**: `b2bebb7` 2026-10-14, `287305b` and `7233d97` 2026-10-20 ("rough drafts of the 4 agents"). Declare them as pre-existing, or rebuild that code inside the window |
| 5 | "Every submission must integrate Zetaris and Meterless, and teams must use Cursor for development." | All three visible in the repo and the demo |
| 5 | "Pre-existing product code must be declared in the submission form." | Declare the earlier agent drafts |
| 6 | The four submission items above | Video 1–4 min, deck, repo + README, integration write-up |
| 10 | "Disqualification decisions are final and are communicated with a reason to the team lead." | n/a |

## Prizes (Rule 8, exact)

- "Up to $20,000 in total prize value: $13,000 in cash prizes and $7,000 in in-kind rewards for selected winners."
- "Cash prizes per track (1st / 2nd / 3rd): Solving Fragmented Intelligence $1,600 / $1,200 / $900; The Agent That Can Explain Why $1,600 / $1,200 / $900; Reasoning Architecture $1,500 / $1,200 / $900; Wildcard [Tinkerer] $1,000 / $600 / $400."
- "In-kind rewards: Best use of NVIDIA Nemotron - NVIDIA DGX Spark AI Supercomputer (Founder's Edition), $4,699."
- HackOS Hackathon Overview itemises the in-kind rewards: "Best use of NVIDIA Nemotron | NVIDIA DGX Spark (Founder's Edition) | $4,699" and "Best Cursor-built product | Cursor API credits | $2,301" ($7,000 total).
- Bright Data bounty: **NOT FOUND** on the event page, the academy page or any HackOS document. The only HackOS mention is a "Help Bright Data" channel named in the 22 Oct "build window is open" announcement; no such channel appears in the Messages channel list.
- Cash prizes: "paid by bank transfer within 30 days", "split equally among team members unless the team submits a different split in writing", "Taxes and any local charges are the recipient's responsibility."
- 1.2: "Employees of the organizer and of judging sponsors may participate but are not eligible for cash prizes."

NVIDIA award criteria (Hackathon Overview): "a submission must use at least one Nemotron model through Meterless Nightshift in a working feature, and show which model handled the request." Setup Guide: "Suggested judging criteria: technical depth, usefulness and polish."

## Intellectual property (Rule 9)

"You keep all rights to what you build." / "By submitting you grant the organizer a license to show your demo, screenshots and description in event coverage." / "Sponsor-track submissions grant that sponsor the same non-exclusive promotional license."

## Contact and changes (Rule 10)

- "The organizer may adjust the schedule for technical reasons; changes are announced on this page and in Discord."
- "Questions go to hackathons@genai.works - expect a reply within one working day."
- Discord: https://discord.gg/tfwSeqVWmR ("Discord is for announcements and post event activities.")

## FAQ (exact)

- Cost: "No. Registration, the platform workspace, mentor office hours and submission are all free."
- No team: "Yes. Register solo and use Team Finder on the platform; most teams form during the first evening. You can also compete alone."
- Online: "Yes. Kickoff, office hours, judging and results all happen online in Discord and on the platform. No travel, no local chapter required."
- Closed-source and paid APIs: "Yes, including sponsor credits. Just declare anything pre-existing in your submission so judges can see what you built during the window."
- After Register: "You land in your hackathon workspace with the schedule, resources and submission form."
- Students: "University organisers can request a cohort code so every registration from a campus is grouped together - email hackathons@genai.works."
