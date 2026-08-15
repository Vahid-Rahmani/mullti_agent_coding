# usestrix/strix

- **Repository:** `usestrix/strix`
- **URL:** https://github.com/usestrix/strix
- **License:** Apache-2.0
- **Source type:** Open-source AI penetration-testing tool (multi-agent)
- **Main purpose:** Autonomous AI pentesting agents that run code dynamically,
  find vulnerabilities, and validate them through proofs-of-concept.
- **Important directories/files:** agent skills (`penetration-testing`,
  `fix-security-vulnerabilities`, `ci-security-scanning`, `managed-pentesting`),
  agent orchestration, sandbox tooling.
- **Useful concepts:** security-agent architecture, tool orchestration,
  sandboxing, reconnaissance, vulnerability discovery, finding structure,
  validation, proof-of-concept workflows, remediation, re-scan, security
  reporting, agent/tool boundaries.
- **Useful prompts/skills:** find → validate (PoC) → fix → re-scan → report.
- **Useful workflow patterns:** Analyze → Security Scan → Findings → Validate →
  Fix → Re-scan → Verify → Report.
- **Useful architectural patterns:** evidence-grounded findings (working PoCs,
  not static-analysis noise); remediation followed by re-scan verification.
- **MultiAgentCoding integration:** `security-pentest-validator` prompt profile
  plus the `security-audit` workflow template (a native MultiAgentCoding graph
  with a bounded fix/re-scan loop). The external project itself is not copied.
- **Recommended integration target:** Prompt Library + Workflow Template
  (future Security workflow).
- **License restrictions:** Apache-2.0 — preserve copyright/notice and state
  changes in any reuse.
- **Code reuse allowed:** Yes (with attribution) — we adapt the workflow, not
  the code.
- **Extraction mode:** Ideas / workflow design (no code copied).
