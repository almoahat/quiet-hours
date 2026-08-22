# quiet-hours
Quiet Hours is an agent that watches your logs so you do not have to.


Local-first incident root cause analysis. Reads multiple log sources, builds one unified timeline, and explains the likely root cause in plain English with every claim cited back to a specific log line. Runs entirely on a Dell Pro Max with GB10. No cloud API calls.

Built at the Dell x NVIDIA AI Hackathon, New York, August 22, 2026.

The problem

When production breaks, the evidence is scattered across tools that don't talk to each other. Different query languages, different timestamp formats, different field names for the same concepts. During an incident, a human becomes the correlation engine, holding the timeline together in their head while the clock runs.



Demo

coming soon
<!-- TODO: drop demo.gif here. Split screen: raw streams left, cited timeline assembling right. -->



How it works

<img width="574" height="358" alt="CloudWatch" src="https://github.com/user-attachments/assets/299bdc7f-ca3e-413f-8a88-9641d3d386d1" />

Four stages. Only one of them calls a model.

Stage	What it does	Implementation
1. Normalize	Parses each source format into a common event shape	Deterministic parser
2. Localize	Merges, sorts by normalized UTC time, selects the incident window	Deterministic
3. Diagnose	Proposes a root cause, or reports insufficient evidence	Single LLM call
4. Evidence	Resolves cited event IDs back to raw log lines	Deterministic lookup

Parsing, sorting, and lookup each have exactly one right answer. Code does them perfectly; a small local model does them worse. Only "what caused this" needs judgment, so that is the only place the model goes.

The practical benefit is separability: when a diagnosis is wrong, we can tell whether the parser broke or the model reasoned badly. In a fully agentic loop those two failures produce the same symptom.

The output contract

The model must return a structured Diagnosis. Every claim carries a list of event_id references, and a validation gate rejects any response with an uncited claim or a hallucinated event ID, feeding the errors back for one retry.

Citations are therefore a property of the system, enforced in code, rather than a hope about the prompt.

insufficient_evidence is a first-class outcome. The agent is allowed to say it doesn't know, and an unexplained field lists events that don't fit the proposed story.

Why it runs locally

Economics. Reading full log volume continuously is priced out at API token rates. On hardware you own, it is free, so the agent never stops reading.

Policy. Air-gapped and data-residency environments cannot send a log line off-premise under any contract. That segment is not served today.

To be clear about what this does not claim: regulated organizations do use cloud logging vendors under BAAs, and several open-source RCA tools support local inference. The specific combination here is raw heterogeneous log text, no instrumentation required, and on-device reasoning.

Stack
NemoClaw + OpenClaw + OpenShell — agent runtime, sandboxing, local-only inference routing
Nemotron (4-bit) served locally on the GB10
Python — parsers, timeline builder, evidence resolver
FastAPI + React + Vite — split-screen interface
Running it
bash
# install
poetry install

# generate synthetic logs (seeded, reproducible)
poetry run python scripts/generate_logs.py --seed 42

# run the pipeline
poetry run python -m quiet_hours.run --window auto

# frontend
cd web && npm install && npm run dev
Design decisions

Deterministic first, model last. See the table above. This follows the direction the open-source RCA field has taken: Coroot runs a deterministic pipeline and gives the model one prepared context, and K8sGPT runs deterministic analyzers with an LLM only explaining findings. HolmesGPT represents the other camp, a full ReAct loop over many toolsets. We picked the first approach and applied it to raw heterogeneous log text rather than instrumented telemetry.

Synthetic logs, not live connectors. Wiring up real vendor APIs is auth and VPN work, not the interesting problem. The hard part is schema and clock mismatch across sources, and synthetic data reproduces that faithfully while staying reproducible. The generator is seeded, so every run produces identical output.

Citations enforced, not requested. A small model will produce confident, plausible, wrong answers. Structural validation is the only reliable defense.

Ground truth committed. data/fixtures/incident.json records which event is the true root cause, so correctness is checkable rather than a matter of whether the output reads well.

Limitations
Runs against synthetic logs. No live Splunk, Sumo, or CloudWatch connectors.
Two source formats implemented. The parser interface is source-agnostic, so adding a third is one file.
Single incident at a time. No ranking across concurrent incidents.
One-day build. Test coverage is partial and error handling is thin in places.
What's next
Live connectors. Adapters for real sources. The parser is the only source-specific code.
GPU cluster telemetry. The same pipeline against a failed distributed training run: which node died, and why. Different corpus, identical architecture.
Concurrent incidents. Multiple timelines at once, ranked by severity.
Evaluation harness. A corpus of scripted incidents with known causes, to measure diagnosis accuracy rather than eyeballing it.
