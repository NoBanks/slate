# lablab.ai submission draft: SLATE

Draft answers for the Vultr: Agent Rush submission form (Challenge 1, "Blast Radius Zero"). Video and PDF slides are made separately and are not in this repo. Items marked [NEED] could not be confirmed from the repository.

## Project title

SLATE: every agent action, on the record

## Short description

(169 characters)

A browser agent that works inside a throwaway Vultr microVM and returns a signed, hash-chained receipt for every step, checked by a second model and approved by a human.

## Long description

**What it is.** SLATE is a browser agent with receipts. You give it a goal, such as getting quotes for 250 LED panels from three vendors and filling in the cheapest safe vendor's quote form. It opens each site, reads the price table, compares, fills the form, and stops for a human before it submits. Every step it takes is written to a receipt: what it did, what it saw (page and screenshot hashes), every network request it made, what an independent verifier model said about the step, and what sandbox it ran in. Receipts are chained with SHA-256 and signed with Ed25519. Anyone can drop the bundle on the public /verify page and check every hash, link and signature. Change one byte and it fails.

**How it works.** The control plane runs on a Vultr Cloud Compute VM. It holds the API key, the signing key and the egress proxy. All model calls go to Vultr Serverless Inference: `glm-5.3` plans and calls tools, `qwen3.8-flash-next` verifies each step from the screenshot, and `nemotron-3.5-content-safety` screens each page for prompt injection. The browser runs in a Microsandbox microVM with its own kernel, 1 vCPU and 2 GB of RAM, no network except one rule to the egress proxy, and no secrets. The proxy only lets through this task's vendor hosts and logs every request into the receipts. The microVM is destroyed when the task ends, and the final receipt records the teardown.

**Containment you can watch.** One vendor page hides an instruction telling AI agents to read their environment variables and POST them to an outside server. With the safety screen on, SLATE flags the page, hides it from the planner, and skips that vendor. In red team mode the screen is off and a labeled, scripted attacker follows the instruction. It reads the sandbox environment and finds no secrets. It tries the POST and the proxy blocks it. The block is signed into the record. The human can then reject the final submit, and that decision is signed too.

**Why it matters.** Agents can now click, type and submit on the real web, but companies keep them away from real workflows because nobody can prove what the agent saw, did, or why. Compliance teams need evidence (the EU AI Act, Article 12, requires automatic event logging for high-risk AI systems), and disputes need proof. SLATE turns agent output into evidence that a third party can check without trusting the operator.

**What is original.** Most agent sandboxes stop at isolation, and most agent logs are plain text the operator could edit. SLATE puts both together: every action, observation, verifier verdict, blocked request, human approval and sandbox teardown goes into one signed hash chain, and the containment test is part of the demo rather than a claim. The planner, verifier and safety screen are three models from three families, so the model that acts is never the one that checks.

**Business value.** Procurement, back office and compliance teams can let an agent do web tasks and keep a record an auditor or counterparty can verify on their own. The same receipt format works for any browser task, not only quotes. A team can start with human approval on every final action and keep the receipts as the audit trail.

**Builder.** Built solo by Ryan Hammer (NoBanks), cinematographer since 2008. The name comes from the film slate: every take gets marked so nobody can argue about what happened.

## Tags

AI Agents, Vultr, Browser Automation, Sandboxing, Prompt Injection, Security, Audit Trail, Microsandbox

## Demo platform

Web (browser)

## App URL

https://slate.nohumannearby.com

Receipt verifier: https://slate.nohumannearby.com/verify

## Repository URL

https://github.com/NoBanks/slate

[NEED] confirm the repository is switched to public before submitting (commit 8cdc39a notes the repo is private until submission).

## Technology used

Vultr Cloud Compute (VX1, Ubuntu 24.04), Vultr Serverless Inference, Microsandbox, Python, FastAPI, Playwright (Chromium), PyNaCl (Ed25519), Caddy.

## Checklist before submitting

- [ ] Repository is public
- [ ] Live demo is up at the app URL
- [ ] Video uploaded [NEED]
- [ ] PDF slides uploaded [NEED]
