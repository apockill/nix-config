# desk-idle: puts Alex's desk to sleep (arm rested and released, desk light and projector off)
# once nothing has used it for an hour. monitor.py is only a cheap gate: while everything is off
# no model runs; while something is on, a Claude agent (Alex, 11-13: smarter than the local model,
# which twice switched the projector off while the desk was in use) decides once an hour. The job
# needs terminal and vision (Alex's explicit OK for this job); its toolsets are set on the job.
{
  aiBox.hermesCron.desk-idle = {
    schedule = "30 * * * *";
    monitorScript = ./monitor.py;
    prompt = ''
      The line above is desk-idle's gate. ASLEEP: answer exactly [SILENT]. AWAKE ... lists
      what is on (arm-motors, Desk-light, Projector). Decide whether Alex's desk is in use and,
      only if it is clearly idle, put it to sleep. The desk is a robot cell run by the lab apps
      in /var/lib/hermes/sites (`box <instance> --help` lists each one's calls).

      Your whole answer is one of exactly two things, with nothing before or after it:
      - [SILENT] when you switch nothing off (asleep, in use, or in doubt). Never say why: any
        other word is posted to Alex.
      - one line saying what you switched off, e.g. `desk-idle: switched off Projector,
        Desk-light`, quoting any error on that same line.

      It is in use if any of these, or anything else that tells you someone or something is
      using it:
      - a lab instance (lab-motion, lab-arm, lab-calibration, lab-scanner, lab-world,
        lab-projector) is running a goal or holds a lease (`box <inst> health --json`)
      - the arm took a command in the last 60 minutes (`box lab-arm events --json`)
      - an agent job is working or wrote to its transcript in the last 60 minutes
        (`agent list`, `agent peek <job> 40`)
      - the overhead photo shows a person, a hand or a human arm
        (`box lab-cam-top snapshot -o /var/lib/hermes/.hermes/cache/desk-idle.jpg`, then the
        vision tool; the robot arm, cameras, blocks and paper are always there)
      When in doubt, it is in use.

      Only read-only calls while deciding. If idle, switch off only what is on, with exactly:
      - arm-motors: box lab-motion rest --json, then box lab-arm release --json
      - Desk-light: box lab-projector set-light --no-on --json
      - Projector: box lab-matter switches off <the Projector's id from box lab-matter switches>
      Then run box lab-arm state --json and box lab-matter switches --json to check, and answer
      with that one line. Never move the arm any other way, never touch other switches, never
      stop a job.
    '';
  };
}
