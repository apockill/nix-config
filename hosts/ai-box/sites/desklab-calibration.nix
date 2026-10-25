# desklab's calibration pipeline pauses with a question when a stage needs
# judgement (needs_attention) or Alex (needs_alex, e.g. approving a new run).
# This cron job notices within minutes and tells Alex on Discord; the agent
# answers in that conversation with `box desklab calibrate answer`. (Cron jobs
# can't run commands themselves, so the answer can't happen inside the job.)
{ ... }:
{
  aiBox.hermesCron.desklab-calibration = {
    schedule = "every 2m";
    monitorScript = ./desklab-calibration-monitor.py;
    prompt = ''
      You watch desklab's calibration pipeline on ai-box (Alex's desk robotics
      workstation). The monitor block above shows what changed. Write a short
      Discord message for Alex, under 100 words:
      - NEEDS ATTENTION: say the calibration is paused at that stage, quote the
        question in one or two plain sentences, list the possible answers, and end
        with: "Reply here and I'll look at the evidence and answer it."
      - NEEDS ALEX: say what's waiting for him (usually approving a new
        calibration) in one line, with the bundle id.
      - Back to OK after a pause: one line saying the pipeline continued.
      - Otherwise respond with [SILENT].
      Don't add anything the monitor block doesn't say.
    '';
  };
}
