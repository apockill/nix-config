# arm-alert: tells Alex on Discord when the desk's robot arm raises an alert (e.g. servo_dropout,
# its gripper's servo gone silent) or sits powered out of its rest, stuck (Alex, 11-18: "I hate
# the idea that I go to bed and the robot is just stuck there for the whole night"), and what
# the recovery did (lab-motion docks and releases an arm its silent gripper left out, after
# 120 s). monitor.py is a cheap gate printing the alert and where the arm is; the model runs only
# when that changes, and only words the message: it has the default cron toolsets, no terminal.
{
  aiBox.hermesCron.arm-alert = {
    # The gate is four small calls to lab-arm, so ticking often is free; STUCK needs the arm
    # still for 5 minutes, so Alex hears within about 7.
    schedule = "every 2m";
    monitorScript = ./monitor.py;
    prompt = ''
      The monitor block above is arm-alert's gate for the robot arm on Alex's desk (a myArm
      M750 run by the lab-arm app; lab-motion plans its moves). Two lines:
      - `alert:` the arm's active alert: its kind, when it was raised, its message, and
        `(later also: ...)` for other kinds folded into it while it stays uncleared; or `none`.
        Kinds: servo_dropout = a servo stopped answering (the gripper's, J7, so far; lab-arm
        sent the controller's clear-error, and lab-motion docks the arm at its rest and powers
        it off if it is left out of its rest for 120 s); temp_rise / temp = a servo heating;
        servo_error = a servo reported an error; power = the motors' power changed unasked.
      - `arm:` where the arm is: `released at its rest [at <time>]` (motors off, the safe
        state), `powered at its rest`, `powered out of its rest` (normal while someone works),
        `unknown` (lab-arm lost its link to the arm), or `STUCK ...`: powered out of its rest
        and not moving for over 5 minutes (30 while a lab stretch is held), which joints are
        away from the rest, whether the gripper's servo is silent, and who holds the stretch.

      Decide from the current output and the diff:
      - A new alert (none before, or a different kind or time), or a new kind under `later
        also`: tell Alex what it is (kind, time, message in plain words) and where the arm is
        now. If it is out of its rest, say lab-motion should dock it within about 2 minutes
        (servo_dropout) and that you will report if it stays stuck.
      - `arm:` became STUCK: tell Alex the arm is stuck out of its rest, since when, which
        joints, whether the gripper servo is silent, and that lab-motion's automatic dock did
        not bring it home. Recovery for Hermes or Alex: `box lab-motion rest`, then
        `box lab-arm release`; if moves are refused, the arm needs a hand at the desk.
      - `arm:` became unknown: say lab-arm lost its link to the arm, so nothing can tell
        where it is or dock it.
      - `arm:` left STUCK or unknown: one short line on where it is now (e.g. "The arm is back:
        released at its rest at 02:14.").
      - With an alert active, `arm:` went to released or powered at its rest from out of its
        rest: one short line on what the recovery did (e.g. "Recovered: the arm docked itself
        at its rest and powered off at 02:12.").
      - Anything else - the alert going to `none` (someone cleared it), the arm moving in and
        out of its rest with no alert, the baseline with `alert: none` and the arm not STUCK:
        answer exactly [SILENT].
      A baseline (first run) with an alert or STUCK: report it like a new one.

      You only report; you can't move the arm or clear its alert. Answer with one Discord
      message for Alex, under 100 words, plain and specific, quoting
      times as the monitor gives them.
    '';
  };
}
