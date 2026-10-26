# desk-idle (Alex, 2026-10-26): an hourly Hermes cron job (local Gemma) that
# puts the desk to sleep when nobody is using it, and tells Alex only when it
# did. The checks are plain English with the exact commands to use; this job
# alone gets a terminal (no web: its only inputs are the desk's own state).
{
  aiBox.hermesCron.desk-idle = {
    # :30, clear of the hourly upgrade (~:01) that restarts the gateway.
    schedule = "30 * * * *";
    toolsets = [
      "terminal"
      "vision"
    ];
    prompt = ''
      You check whether Alex's desk (a robot arm, a projector, a ring light
      called "Desk light") is idle, and if so put it to sleep. Use only the
      commands below.

      1. Is anything awake? `box desklab arm state --json` (field power: 1 =
         motors on) and `box matter switches --json` (state.on of "Desk light"
         and "Projector"). If the motors are off and both switches are off,
         answer exactly [SILENT] and stop.

      2. Is anyone using it? It is in use if ANY of these is true:
         - `box desklab hover session --json`, `box desklab experiment --json`
           or `box desklab calibrate status --json` has a state like running,
           waiting or needs_alex (done, halted, interrupted, approved and
           errors are not in use);
         - the arm was commanded in the last 60 minutes:
           `box desklab arm events --json | jq '[.[] | select(.kind == "command")][-1] | (now - .t) / 60 | floor'`
           prints the minutes since;
         - Claude Code worked on desklab in the last 60 minutes:
           `find /var/lib/hermes/.claude/projects/-var-lib-hermes-sites-desklab -name '*.jsonl' -mmin -60`
           prints anything;
         - a person, hand or human arm is at the desk: take a photo with
           `box desklab cameras snapshot top -o /var/lib/hermes/.hermes/cache/desk-idle.jpg`
           and look at it with the vision tool. The robot arm, cameras, a
           foam block and paper are always there.
         If it is in use, or you are unsure, answer exactly [SILENT] and stop.

      3. Put it to sleep, only what is awake:
         - arm motors on: `box desklab hover session dock --by desk-idle`, then
           every 15 seconds `box desklab hover session --json` until state is
           not running (at most 10 minutes). done = docked, motors released.
           Anything else: the arm holds where it stopped; don't retry, report it.
         - Desk light on: `box desklab lights off`.
         - Projector on: `box matter switches off <id>` with the Projector's id
           from step 1.

      4. Answer with one short line for Alex: what you switched off, why the
         desk counted as idle, and any problem (quote the error).
    '';
  };
}
