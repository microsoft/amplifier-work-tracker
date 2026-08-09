"""amplifier-work-tracker -- user feedback to engineering work, on Beads.

Layering (enforced by convention, verified by `amplifier-work-tracker doctor`):
  amplifier_work_tracker.adapter   the ONLY module that knows Beads exists
  amplifier_work_tracker.contract  executable assumptions about Beads, run via `doctor`
  amplifier_work_tracker.custody   liveness/custody domain logic
  amplifier_work_tracker.gateway   the Feedback Gateway -- the only writer of user reports
  amplifier_work_tracker.cli       the CLI surface
"""
