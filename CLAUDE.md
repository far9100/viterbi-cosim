<!-- Purpose: Conventions that Claude Code must follow when generating or modifying code in this project (FEC decoder RTL and bit-accurate co-simulation). -->

# Project Conventions

This document defines the rules Claude Code must follow when working in this project. Read it before making any change. Established 2026-07-14, adapted from the diffusion project's conventions.

The technical specification lives in `docs/fec_viterbi_cosim_spec.md`. Where the two documents overlap, the spec governs technical content (parameters, gates, milestones) and this document governs working process.

## 1. Changelog and Outward-facing Documents

Everything that documents the project's history is version-controlled. There is no local,
unversioned log.

### 1.1 Changelog (published)

`CHANGELOG.md` is the project's update history. **Every completed unit of work adds one line to
`CHANGELOG.md` in the same commit that finishes it.** Work that has not produced its changelog
line is unfinished work.

1. Sections are dated (`## YYYY-MM-DD`), newest first. The `##` heading is also the anchor other
   documents link to (`CHANGELOG.md#2026-07-20`).
2. One line per entry, prefixed by its entry ID and action: ``- `2026-07-20-02` test — …``.
   - The entry ID uses the `YYYY-MM-DD-NN` format, where `NN` is a two-digit sequence number
     starting from `01` indicating which entry of that day it is. The ID identifies the changelog
     entry itself; it does not point to any file outside the tree.
   - `action` is one of: `plan`, `add`, `debug`, `refactor`, `proofread`, `test`, `audit`.
3. The line states what was done and what the conclusion was, in one sentence, with the numbers if
   there are any (e.g. "G2 soft-decision coding gain 4.9 dB @ BER 1e-5, within the pre-set tolerance
   of ±0.3 dB"). It does not narrate process.
4. Goal, result, and follow-up are not written into the changelog. Goal and rationale belong in the
   commit message (§3.1); results and follow-up are reported to the author at the milestone STOP
   (§4.2).

### 1.2 Outward-facing documents (version-controlled)

Freeze declarations, tolerance definitions, and final verdicts must live under `docs/` and be
committed **before** the run they govern, so that their commit timestamp verifiably predates the
run. The reference examples in this project: the falsification condition for the d\* claim
(spec §0) and the M1 test-vector freeze declaration. See §5.

## 2. File Header Comments

Every file in the project must begin with a short comment describing the file's purpose. This
applies equally to Python, C++, SystemVerilog, Makefiles, and OpenLane configuration files.

## 3. Language and Writing Style

1. `README.md`, code comments, analysis and conclusions, and commit messages must be written
   primarily in Traditional Chinese. A commit message states the goal of the change and the reason
   for it, not only what changed.
2. Use plain, direct prose. Avoid unnecessary adjectives or modifiers.
3. Do not use symbols as status markers, such as check marks, crosses, or warning icons.
4. Keep naming consistent across the whole project for variables, functions, files, and folders. Use one name per concept and avoid mixing different terms for the same thing. In particular, the signal and variable names for architectural state (`bm`, `pm`, `survivor`) must be identical across `golden/`, `rtl/`, and `tb/`.

## 4. Minimal Change Principle

1. **MVP first, build up incrementally.** Make the minimal working version fully correct before adding anything on top. It is better to support one fewer quantization configuration than to leave the whole verification chain half-finished.
2. **STOP after each stage.** Stages in this project are the milestones M1–M6 defined in the spec (§9). At the end of each milestone, run `make gates`, present that milestone's gate results, charts, and data to the author, and proceed only after the author confirms. Do not run through multiple milestones in one pass.
3. **For features outside the spec, ask first; do not add them on your own.** The following are explicitly out of scope and must not be started without the author's written confirmation: LDPC (forbidden outright), Polar SC (permitted only after M6 is accepted), FPGA implementation, any new sweep axis, code rate, or channel model.
4. **Code must be readable and commented to explain the modeling and measurement rationale.** Assume the reader is a first-year graduate student new to channel coding and digital design: for each key step, explain what the step does and why (e.g. why the ACS comparison is performed in modulo arithmetic, why traceback depth is tied to the constraint length, why switching activity must come from real channel-driven inputs).

## 5. Freeze, Ordering, and Metadata Conventions

1. **Freeze definition.** A specification is frozen when all four hold: (a) the rule is written in
   prose in a document under `docs/` (§1.2), committed before any run it governs; (b) it is
   expressed in committed code where a computation is involved; (c) it passes its designated dry-run
   gate before the real run — for the L2 golden-model freeze this means gates G1, G2a, G2b, G3, G4
   all green; for the Tier B harness this means **the stimulus manifest's SHA-256 reconciles and the
   decoded-bit XOR against L2's expected output is zero** (see below); and (d) the run's output
   carries a hash or byte-level reconcile against the frozen target — frozen test vectors carry
   SHA-256 digests, and every C2 comparison is byte-level by construction.

   **Amended 2026-07-14.** The original wording required "the fixed-seed 10^5-bit bit-level
   equivalence check against L2" for the Tier B C++ harness. That check is not achievable: numpy's
   PCG64 + ziggurat normal generator cannot be made bit-identical to any independently written C++
   RNG without sharing an implementation, so the requirement could only ever be met by cheating.
   It is replaced, not relaxed. The C++ harness now has **no RNG and no quantizer** — it replays a
   stimulus vector exported from L2/GPU (`stimulus_*.bin`) against L2's expected decoded bits
   (`expected_*.bits`), both pinned by SHA-256 in a `manifest.json`. This is strictly stronger than
   the original: the Tier-B stimulus *is* the L2 stimulus, byte for byte. AWGN correctness is
   established separately and statistically (empirical noise variance against N0/2) inside
   `golden/`, which is where it belongs.
2. **Ordering and implementation independence.** The build order is fixed: L2 golden model →
   G1–G4 green → test vectors frozen (git tag) → RTL. No RTL may be written before the freeze tag
   exists. While writing L2, do not read RTL code; while writing RTL, do not read L2's
   implementation — only its interface definitions and test-vector formats. The golden model must
   be bit-accurate at architectural-state boundaries (per-stage `bm`, `pm`, `survivor`), and must
   not imitate the RTL's pipelining or handshaking. Violating independence invalidates C2 and the
   affected side must be rewritten.
3. **Driver metadata completeness.** Every measurement run — Tier A cocotb, Tier B C++ Monte
   Carlo, GPU design-space sweep, and PPA/SAIF flow — must record, in its output metadata, all
   parameters needed to reproduce the numbers: `start_timestamp`, full `argv`, RNG seed(s), every
   design and analysis parameter (`Q`, `clip`, `W`, `D`, `snr_db`, `frame_len`, `n_bits`), the git
   commit hashes of `golden/` and `rtl/` used in the run, and the environment versions (verilator /
   cocotb / numpy / cupy or torch / cuda, plus PDK and OpenLane versions for PPA runs). Rationale:
   in a previous project, a scalar whose analysis parameter was not stored in metadata could not be
   traced or reconciled afterward; a BER point that cannot be traced to its (seed, configuration,
   commits) is not evidence.
4. **Single data source.** Every number that appears in `README.md`, `docs/`, or `CHANGELOG.md`
   must exist in `data/results.csv` or `data/gates.csv` and be regenerable by a script under
   `scripts/`. Hand-pasted numbers are not accepted.
